# -*- coding: utf-8 -*-
"""多角色 edge-tts 合成。

本模块刻意把 2026-09-21 那次线上事故的三个教训内建进去，任何复用都要保留：
1. 强制 IPv4 —— 本机/云主机的 DNS 对 speech.platform.bing.com 会返回 IPv6 优先，
   而 IPv6 常常不通 → TCP 静默挂起（不返回也不报错）。必须 patch getaddrinfo。
2. 硬超时 —— edge-tts 挂死时 asyncio 会永远等，没有超时重试逻辑永远轮不到执行。
3. 片段缓存 —— 按 sha1(voice|rate|pitch|text) 缓存，中途挂掉重跑只重做失败段。
"""
import asyncio
import hashlib
import json
import os
import shutil
import socket
import time

# ---- 1. 强制 IPv4（必须在 edge_tts 建连之前）----
_orig_getaddrinfo = socket.getaddrinfo


def _v4_only(host, port, family=0, type=0, proto=0, flags=0):
    try:
        res = _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
    except OSError:
        res = None
    return res if res else _orig_getaddrinfo(host, port, family, type, proto, flags)


socket.getaddrinfo = _v4_only

import edge_tts  # noqa: E402  必须在 patch 之后

BACKOFFS = [3, 6, 10]
SYNTH_TIMEOUT = 90


def _cache_path(cache_dir, voice, rate, pitch, text):
    key = hashlib.sha1(f"{voice}|{rate}|{pitch}|{text}".encode("utf-8")).hexdigest()
    return os.path.join(cache_dir, key + ".mp3")


def synth_one(text, voice, rate, pitch, out_path, cache_dir=None, log=print):
    """合成单段。返回 True/False。命中缓存则不联网。"""
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
        cached = _cache_path(cache_dir, voice, rate, pitch, text)
        if os.path.exists(cached) and os.path.getsize(cached) > 0:
            shutil.copyfile(cached, out_path)
            return True

    async def _go():
        kwargs = {"rate": rate}
        if pitch:
            kwargs["pitch"] = pitch
        await edge_tts.Communicate(text, voice, **kwargs).save(out_path)

    def _usable(path):
        return os.path.exists(path) and os.path.getsize(path) > 0

    def _settled(path):
        """超时不等于失败：edge_tts 常把音频写完、却卡在收尾（关连接）不返回。
        此时 await 被 wait_for 取消，但文件其实是好的。
        判据：文件非空，且 2 秒内不再增长 → 视为已写完。"""
        if not _usable(path):
            return False
        s1 = os.path.getsize(path)
        time.sleep(2)
        try:
            return os.path.getsize(path) == s1 and s1 > 0
        except OSError:
            return False

    for attempt in range(len(BACKOFFS) + 1):
        done = False
        try:
            asyncio.run(asyncio.wait_for(_go(), timeout=SYNTH_TIMEOUT))
            done = True
        except asyncio.TimeoutError:
            log(f"    [tts] 超时 {SYNTH_TIMEOUT}s（第{attempt + 1}次）{voice}，检查产物…")
            done = _settled(out_path)
            if done:
                log("    [tts] 产物已完整，按成功处理")
        except Exception as e:  # noqa: BLE001
            log(f"    [tts] 失败：{type(e).__name__} {e}")

        if done and _usable(out_path):
            if cache_dir:
                shutil.copyfile(out_path, _cache_path(cache_dir, voice, rate, pitch, text))
            return True

        # 清掉残留（不管多大）—— 残缺文件留着会被下游当成有效片段
        try:
            if os.path.exists(out_path):
                os.unlink(out_path)
        except OSError:
            pass
        if attempt < len(BACKOFFS):
            time.sleep(BACKOFFS[attempt])
    return False


def synth_all(segments, out_dir, cache_dir=None, log=print):
    """逐段合成。返回 (parts: [路径], degraded: int)"""
    os.makedirs(out_dir, exist_ok=True)
    parts, degraded = [], 0
    for i, seg in enumerate(segments):
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        voice, rate, pitch = seg["voice"], seg["rate"], seg.get("pitch")
        path = os.path.join(out_dir, f"{i + 10:04d}_{seg['role']}.mp3")
        if synth_one(text, voice, rate, pitch, path, cache_dir=cache_dir, log=log):
            parts.append(path)
        else:
            # 兜底：降级为旁白音色，保证这一段有声音（会被记为 degraded）
            if synth_one(text, "zh-CN-XiaoxiaoNeural", "-20%", None, path,
                         cache_dir=None, log=log):
                parts.append(path)
                degraded += 1
                log(f"    [tts] 第 {i} 段降级为旁白音色")
            else:
                log(f"    [tts] 第 {i} 段彻底失败，跳过")
        if (i + 1) % 10 == 0:
            log(f"    [tts] 进度 {i + 1}/{len(segments)}")
    return parts, degraded


def concat(parts, out_path, ffmpeg="ffmpeg"):
    """ffmpeg concat 合并。"""
    import subprocess
    list_file = out_path + ".txt"
    with open(list_file, "w", encoding="utf-8") as f:
        for p in parts:
            f.write(f"file '{os.path.abspath(p)}'\n")
    subprocess.run([ffmpeg, "-y", "-f", "concat", "-safe", "0",
                    "-i", list_file, "-c", "copy", out_path],
                   capture_output=True, check=False)
    try:
        os.unlink(list_file)
    except OSError:
        pass
    return os.path.exists(out_path) and os.path.getsize(out_path) > 0


def dump_json(obj, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
