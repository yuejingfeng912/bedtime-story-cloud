# -*- coding: utf-8 -*-
"""故事生成 + 角色音色映射。

LLM 可插拔三选一（靠环境变量自动识别，不需要改代码）：
  1. github_models —— GitHub Models，用 Actions 内置 GITHUB_TOKEN，免费、零配置（默认）
  2. openai        —— 任意 OpenAI 兼容接口（OPENAI_BASE_URL + OPENAI_API_KEY）
  3. none          —— 不生成，直接读 stories/<日期>.json（离线 / 手工创作时用）

本机那套写作规范（3-6 岁 / 1500-1750 字 / 100-115 段 / 3-5 角色）固化在 SYSTEM_PROMPT 里。
"""
import datetime
import json
import os
import re

# ---- 角色类型 → 音色 / 语速 / 音调 / 底色（与本机流水线保持一致）----
ROLE_VOICE = {
    "narrator":     {"voice": "zh-CN-XiaoxiaoNeural",        "rate": "-20%", "pitch": "+0Hz",  "color": None},
    "child":        {"voice": "zh-CN-XiaoxiaoNeural",        "rate": "+0%",  "pitch": "+30Hz", "color": "E8F5E9"},
    "young_female": {"voice": "zh-CN-XiaoyiNeural",          "rate": "+0%",  "pitch": "+0Hz",  "color": "FFF3E0"},
    "young_male":   {"voice": "zh-CN-YunxiNeural",           "rate": "+0%",  "pitch": "+0Hz",  "color": "E3F2FD"},
    "old_female":   {"voice": "zh-CN-shaanxi-XiaoniNeural",  "rate": "-25%", "pitch": "-20Hz", "color": "F3E5F5"},
    "old_male":     {"voice": "zh-CN-YunyangNeural",         "rate": "-25%", "pitch": "-20Hz", "color": "E0E0E0"},
}
# 以下音色已从 edge-tts 下线，用了必然失败，禁止出现
BANNED_VOICES = ("Xiaorui", "Xiaomo", "Xiaoshuang", "Xiaohan", "Xiaochen", "Xiaozhen")

SYSTEM_PROMPT = """你是一位儿童睡前故事作家。请为一个 3-6 岁的孩子写一篇中文睡前故事。

硬性要求：
1. 正文 1500-1750 字，拆成 100-115 个片段。
2. 对话必须逐句拆段：一句台词 = 一个片段；旁白叙述另起片段，不要和对白合并。平均每段约 15 字。
3. 3-5 个角色（含旁白）。主角用萌系叠字名或短名，配角可为爷爷/奶奶/妈妈/小动物等。
4. 情节完整，结尾先写一段以"故事寓意。"开头的独立旁白段，再写晚安语。
5. 中文弯引号用 \u201c \u201d。语气温和，适合睡前。
6. 标题不要写成"小XX和XX的XX"这种模板式，推荐事件式/疑问式/地点式/诗意式。
7. 内容可涉及自然、动植物、中国传统文化、各国民俗、节日、科普，面向全世界。

只输出 JSON，不要任何解释文字，格式如下：
{
  "storyName": "故事标题",
  "subtitle": "主题：xx + xx　|　背景：xx　|　风格：xx + xx",
  "roles": {
    "narrator": {"name": "旁白", "type": "narrator"},
    "yueya": {"name": "月牙", "type": "child"},
    "aye": {"name": "阿爷", "type": "old_male"}
  },
  "segments": [
    {"role": "narrator", "text": "很久很久以前……"},
    {"role": "yueya", "text": "\\u201c阿爷你看！\\u201d"}
  ]
}
role 取值必须是 roles 里定义的键。type 只能是：narrator / child / young_female / young_male / old_female / old_male。
segments 数组长度必须 100-115。"""


def _chat(messages, max_tokens=32768, temperature=0.9, log=print):
    """调用 LLM，返回文本。provider 自动识别。"""
    import urllib.error
    import urllib.request

    gh = os.environ.get("GITHUB_TOKEN")
    oai_key = os.environ.get("OPENAI_API_KEY")
    oai_base = (os.environ.get("OPENAI_BASE_URL") or "").rstrip("/")

    if oai_key and oai_base:
        url, token = f"{oai_base}/chat/completions", oai_key
        model = os.environ.get("LLM_MODEL") or "gpt-4o-mini"
        provider = "openai"
    elif gh:
        url, token = "https://models.github.ai/inference/chat/completions", gh
        model = os.environ.get("LLM_MODEL") or "openai/gpt-4o-mini"
        provider = "github_models"
    else:
        raise RuntimeError("未配置任何 LLM 凭据（GITHUB_TOKEN 或 OPENAI_API_KEY+OPENAI_BASE_URL）")

    log(f"    [story] LLM provider = {provider}, model = {model}")
    body = {"model": model, "messages": messages,
            "max_tokens": max_tokens, "temperature": temperature}
    # 推理型模型（DeepSeek V4 等）默认会花掉几千 token 在 reasoning 上，
    # 上限不够时正文被截断、JSON 不闭合。用 LLM_EFFORT=low 压掉大部分推理。
    effort = os.environ.get("LLM_EFFORT", "")
    if effort:
        body["effort"] = effort
        log(f"    [story] effort = {effort}")

    def _post(m):
        payload = dict(body, model=m)
        headers = {"Content-Type": "application/json",
                   "Authorization": f"Bearer {token}"}
        if provider == "github_models":
            # 这两个头缺一不可：没有 Accept 时网关会返回纯文本 "OK"（假 200），不是 JSON
            headers["Accept"] = "application/vnd.github+json"
            headers["X-GitHub-Api-Version"] = "2022-11-28"
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                raw = resp.read()
                status = resp.status
        except urllib.error.HTTPError as e:
            raw = e.read()
            status = e.code
        if not raw:
            raise RuntimeError(f"LLM 返回空响应（HTTP {status}）model={m}")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            raise RuntimeError(
                f"LLM 返回非 JSON（HTTP {status}）model={m} 前 300 字符：{raw[:300]!r}")

    # 模型名兜底：GitHub Models 的可用模型会变，主模型失败就换备选再试一次
    candidates = [model]
    if provider == "github_models" and "/" not in model:
        candidates.append("openai/" + model)
    if provider == "github_models" and model == "openai/gpt-4o-mini":
        candidates += ["openai/gpt-4.1-mini", "openai/gpt-4o"]

    last_err = None
    for m in candidates:
        try:
            data = _post(m)
            return data["choices"][0]["message"]["content"]
        except RuntimeError as e:
            last_err = e
            log(f"    [story] 模型 {m} 失败：{e}")
    raise last_err


def _extract_json(text):
    """从 LLM 输出里抠出第一个完整 JSON 对象（容忍 ```json 包裹和前后废话）。"""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.M)
    start = text.find("{")
    if start < 0:
        raise ValueError("响应里没有 JSON")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("JSON 未闭合")


def _apply_voices(data, log=print):
    """把 role type 展开成 voice/rate/pitch，并做音色黑名单校验。"""
    roles = data.get("roles") or {}
    out = []
    for seg in data.get("segments") or []:
        role = seg.get("role")
        spec = ROLE_VOICE.get((roles.get(role) or {}).get("type", "narrator"),
                              ROLE_VOICE["narrator"])
        if any(b in spec["voice"] for b in BANNED_VOICES):
            raise ValueError(f"音色已下线: {spec['voice']}")
        out.append({"text": seg.get("text", ""), "role": role,
                    "voice": spec["voice"], "rate": spec["rate"], "pitch": spec["pitch"]})
    data["segments"] = out
    return data


def generate(date_str, theme_hint="", log=print):
    """生成当天故事。返回 (data, source)。source = 'llm' | 'file'"""
    local = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "stories", f"{date_str}.json")
    if os.environ.get("LLM_PROVIDER", "").lower() == "none":
        log(f"    [story] LLM_PROVIDER=none，读取 {local}")
        with open(local, encoding="utf-8") as f:
            return _apply_voices(json.load(f), log=log), "file"

    user = f"今天是 {date_str[:4]} 年 {int(date_str[4:6])} 月 {int(date_str[6:8])} 日。"
    if theme_hint:
        user += f" 本次主题/背景/风格请围绕：{theme_hint}。"
    user += " 请开始创作。"
    msgs = [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user}]
    last_err = None
    for attempt in (1, 2):
        raw = _chat(msgs, log=log)
        try:
            data = _extract_json(raw)
            n = len(data.get("segments") or [])
            if n < 90:
                raise ValueError(f"片段数只有 {n}，明显被截断")
            log(f"    [story] 片段数 {n}")
            return _apply_voices(data, log=log), "llm"
        except Exception as e:                      # noqa: BLE001
            last_err = e
            log(f"    [story] 第 {attempt} 次解析失败：{e}")
            msgs.append({"role": "assistant", "content": (raw or "")[:2000]})
            msgs.append({"role": "user",
                         "content": "上面的输出不完整。请重新输出完整 JSON，"
                                    "segments 一条都不能少。"})
    raise last_err


def today_str():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))
                                ).strftime("%Y%m%d")
