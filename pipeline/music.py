# -*- coding: utf-8 -*-
"""StepFun 专属配乐（云端简化版：整轨一段，先跑通再谈分块）。

调用格式沿用本机 bedtime_story_music/gen_block_bgm.py：
  POST /v1/audio/music/submit  {"task","model_id","caption","instrumental","response_format"}
  POST /v1/audio/music/query   {"task_id"} -> status SUCCESS 时 audio 为裸 base64

关键教训（本机踩过，这里保留）：
- 出片时长不受控，必须 ffprobe 实测，不能信"请求值"。
- ffmpeg 补长必须用输入级 -stream_loop -1，滤镜 aloop 在本机/云上都是空转。
"""
import base64
import json
import os
import subprocess
import time
import urllib.error
import urllib.request

API_BASE = "https://api.stepfun.com/v1/audio/music"
MODEL_ID = "stepaudio-3-music-preview"


def _http(path, payload, key, timeout=60):
    data = json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(API_BASE + path, data=data, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8",
                 "Authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8", "replace"))
        except Exception:
            return e.code, {"error": {"message": str(e)}}
    except Exception as e:  # noqa: BLE001
        return -1, {"error": {"message": repr(e)}}


def generate(caption, out_path, key, poll=5, timeout=600, log=print):
    """生成一段纯器乐配乐。成功返回 True。"""
    payload = {"task": "text_to_music", "model_id": MODEL_ID,
               "caption": caption, "instrumental": True, "response_format": "mp3"}
    status, r = _http("/submit", payload, key)
    if status != 200 or "task_id" not in r:
        log(f"    [music] submit 失败: {status} {str(r)[:200]}")
        return False
    task_id = r["task_id"]
    waited = 0
    while waited < timeout:
        time.sleep(poll)
        waited += poll
        s2, r2 = _http("/query", {"task_id": task_id}, key)
        st = r2.get("status")
        if st == "SUCCESS":
            with open(out_path, "wb") as f:
                f.write(base64.b64decode(r2["audio"]))
            log(f"    [music] 生成成功 {os.path.getsize(out_path)} 字节")
            return True
        if st in ("FAILED", "ERROR"):
            log(f"    [music] 失败: {str(r2)[:200]}")
            return False
    log(f"    [music] 超时 {timeout}s")
    return False


def duration(path, ffprobe="ffprobe"):
    out = subprocess.run([ffprobe, "-v", "quiet", "-print_format", "json",
                          "-show_format", path], capture_output=True, text=True)
    try:
        return float(json.loads(out.stdout)["format"]["duration"])
    except Exception:  # noqa: BLE001
        return 0.0


def fit_to(src, target_sec, out_path, ffmpeg="ffmpeg", log=print):
    """把配乐铺到 >= target_sec。返回实测时长（来自 ffprobe，不是算式）。"""
    d = duration(src)
    if d <= 0:
        return 0.0
    if d >= target_sec:
        subprocess.run([ffmpeg, "-y", "-i", src, "-t", str(target_sec),
                        "-af", f"afade=t=in:st=0:d=2,afade=t=out:st={max(0, target_sec - 3)}:d=3",
                        "-c:a", "libmp3lame", "-q:a", "4", out_path],
                       capture_output=True)
    else:
        # 输入级循环，不能用 aloop 滤镜（空转）
        subprocess.run([ffmpeg, "-y", "-stream_loop", "-1", "-i", src,
                        "-t", str(target_sec),
                        "-af", f"afade=t=in:st=0:d=2,afade=t=out:st={max(0, target_sec - 3)}:d=3",
                        "-c:a", "libmp3lame", "-q:a", "4", out_path],
                       capture_output=True)
    real = duration(out_path)
    if real + 0.3 < target_sec:
        log(f"    [music] ⚠️ 配乐实测 {real:.1f}s 短于目标 {target_sec:.1f}s")
    return real


def mix(voice_path, bed_path, out_path, ffmpeg="ffmpeg", bg_volume=0.12):
    """人声 + 配乐混音。normalize=0 才不会把人声砍半。"""
    subprocess.run([ffmpeg, "-y", "-i", voice_path, "-i", bed_path,
                    "-filter_complex",
                    f"[1:a]volume={bg_volume}[bg];"
                    f"[0:a][bg]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[am];"
                    f"[am]alimiter=limit=0.97:level=disabled[out]",
                    "-map", "[out]", "-c:a", "libmp3lame", "-q:a", "2", out_path],
                   capture_output=True)
    return os.path.exists(out_path) and os.path.getsize(out_path) > 0
