# -*- coding: utf-8 -*-
"""每日睡前故事云端流水线主入口。

流程：故事生成 → 多角色配音 → 合并 → 专属配乐 → 混音 → 推微信。
设计原则（沿用本机踩过的坑）：
  - 推送闸门：degraded > 0 一律不推，宁可当晚没有，也不发残缺版。
  - 时长一律来自 ffprobe 实测，不信算式。
  - 任何一步失败都不致命：配乐失败就推纯人声，推送失败产物仍在 artifact 里。
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pipeline import music, push, story, tts  # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "out")
WORK = os.path.join(ROOT, "work")
CACHE = os.path.join(WORK, "tts_cache")
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
FFPROBE = os.environ.get("FFPROBE", "ffprobe")


def log(msg):
    print(msg, flush=True)


def _truthy(v):
    return str(v).strip().lower() in ("1", "true", "yes")


def main():
    t0 = time.time()
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(WORK, exist_ok=True)
    date_str = story.today_str()
    log("=" * 52)
    log(f"睡前故事云端流水线　{date_str}")
    log("=" * 52)

    # 1. 故事
    log("[1/5] 生成故事…")
    try:
        data, source = story.generate(date_str, log=log)
    except Exception as e:  # noqa: BLE001
        log(f"  ❌ 故事生成失败：{type(e).__name__} {e}")
        log("  提示：把写好的 stories/<日期>.json 提交到仓库，或设置 LLM_PROVIDER=none")
        return 1
    name = data.get("storyName") or f"睡前故事{date_str}"
    segments = data.get("segments") or []
    log(f"  故事《{name}》　来源={source}　{len(segments)} 段")
    if not segments:
        log("  ❌ 没有任何片段，终止")
        return 1
    with open(os.path.join(OUT, f"{date_str}_story.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # 2. 配音
    voice_path = os.path.join(OUT, f"{name}_语音讲述.mp3")
    if _truthy(os.environ.get("SKIP_TTS")):
        log("[2/5] SKIP_TTS=1，跳过配音")
        degraded = None
    else:
        log(f"[2/5] 多角色配音（{len(segments)} 段）…")
        parts, degraded = tts.synth_all(segments, os.path.join(WORK, "segs"),
                                        cache_dir=CACHE, log=log)
        log(f"  完成 {len(parts)}/{len(segments)} 段，降级 {degraded} 段")
        if not parts:
            log("  ❌ 全部片段失败（多半是 edge-tts 服务故障），终止")
            return 1
        if not tts.concat(parts, voice_path, ffmpeg=FFMPEG):
            log("  ❌ 合并失败")
            return 1
        dur = music.duration(voice_path, ffprobe=FFPROBE)
        log(f"  人声 {dur:.1f}s（{int(dur // 60)}分{int(dur % 60)}秒）")

    # 3. 配乐 + 4. 混音
    final_path = voice_path
    key = os.environ.get("STEPFUN_KEY") or os.environ.get("STEP_API_KEY")
    if _truthy(os.environ.get("SKIP_MUSIC")) or not key or degraded is None:
        log("[3/5] 跳过配乐（未配置 STEPFUN_KEY 或 SKIP_MUSIC）")
    else:
        log("[3/5] 生成专属配乐…")
        dur = music.duration(voice_path, ffprobe=FFPROBE)
        bed_raw = os.path.join(WORK, "bed_raw.mp3")
        caption = (f"温柔安静的儿童睡前纯器乐，钢琴与轻柔弦乐，"
                   f"适合故事《{name}》，舒缓、无鼓组、无人声，约 {int(dur)} 秒")
        if music.generate(caption, bed_raw, key, log=log):
            bed = os.path.join(WORK, "bed.mp3")
            real = music.fit_to(bed_raw, dur, bed, ffmpeg=FFMPEG, log=log)
            log(f"  配乐床实测 {real:.1f}s")
            if real + 0.3 >= dur:
                mixed = os.path.join(OUT, f"{name}_语音+背景音乐.mp3")
                if music.mix(voice_path, bed, mixed, ffmpeg=FFMPEG):
                    final_path = mixed
                    log("  混音完成")
                else:
                    log("  ⚠️ 混音失败，回退纯人声")
            else:
                log("  ⚠️ 配乐不够长，回退纯人声（宁可没配乐，不要尾部静音）")
        else:
            log("  ⚠️ 配乐生成失败，回退纯人声")

    if os.path.exists(final_path):
        log(f"[4/5] 成品：{os.path.basename(final_path)}"
            f"（{os.path.getsize(final_path) / 1024 / 1024:.1f} MB）")
    else:
        log("[4/5] 无音频成品（SKIP_TTS 或配音失败），仅文本")

    # 5. 推送
    log("[5/5] 推送微信…")
    token = os.environ.get("PUSHPLUS_TOKEN")
    if degraded:
        log(f"  ⛔ 有 {degraded} 段降级，按闸门纪律不推送（避免发出残缺版）")
        return 2
    if not token:
        log("  ⚠️ 未配置 PUSHPLUS_TOKEN，跳过推送（产物仍在 out/）")
        return 0
    content = push.build_html(name, date_str, segments, data.get("roles"))
    title = f"🌙 晚安故事 | {name}（{int(date_str[4:6])}月{int(date_str[6:8])}日）"
    ok, info = push.push(token, title, content)
    log(f"  {'✅ 推送成功' if ok else '❌ 推送失败'} {str(info)[:120]}")
    log(f"\n全部完成，用时 {int(time.time() - t0)}s")
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
