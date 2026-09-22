# 睡前故事 · 云端流水线

每晚 19:00 自动产出一篇 3-6 岁睡前故事：写故事 → 多角色配音 → 专属配乐 → 混音 → 推微信。
**跑在 GitHub Actions 上，不依赖任何一台固定的电脑。**

## 为什么要有这个

原来整套流水线绑死在一台 Windows 机器上（`C:\Python314`、本机 ffmpeg、
`D:\WorkBuddy制品备份`、1.3GB 曲库）。机器关机或人在外地，当晚就没有故事。

现在拆成三层：

| 层 | 在哪 | 说明 |
|---|---|---|
| 随身操作 | 任意设备的浏览器 | GitHub 网页即可手动触发、看日志、下载音频 |
| 云端执行 | GitHub Actions | 定时 + 配音 + 混音，与本机开没开无关 |
| 交付 | PushPlus → 微信 | 本来就跟身走 |

曲库没有搬上来——它只是配乐回退链的第 2 层，首选一直是 StepFun 现生成的专属配乐。
所以仓库体积几乎为零。

## 🌐 随身落地页（能跟着你走的网址）

光有 Actions 还不够"随身"——你不想每次都翻到 Actions 页面。所以挂了一个落地页：

> **https://yuejingfeng912.github.io/bedtime-story-cloud/**

Bookmark 它，手机 / 平板 / 公司电脑都能开。页面里有四个直达卡片：
触发今晚故事、查看运行状态、浏览故事库、下载最新音频；下面还有一块
"实时状态"会自动拉取最近几次运行记录（公开仓库可直接读；私有仓库需登录后同浏览器访问）。

## ⚠️ 仓库现在是公开的（为了免费 Pages）

GitHub **Free 计划不支持私有仓库的 GitHub Pages**（实测 422）。
本仓库已改为**公开**——代码与故事均为无害内容，密钥仍在 GitHub Secrets 中，不会被暴露。
若你日后改回私有，Pages 会立刻失效（想保留网址就保持公开，或升级 GitHub Pro）。

## 首次配置（只需做一次）

在仓库 Settings → Secrets and variables → Actions 里加：

| Secret | 必填 | 说明 |
|---|---|---|
| `PUSHPLUS_TOKEN` | 是 | 微信推送令牌，没有就跳过推送（产物仍保留） |
| `STEPFUN_KEY` | 否 | 专属配乐。不配则只出纯人声 |
| `OPENAI_API_KEY` + `OPENAI_BASE_URL` | **是（见下）** | 写故事用的 OpenAI 兼容接口 |
| `LLM_MODEL` | 否 | 模型名，默认 `gpt-4o-mini` |
| `LLM_EFFORT` | **推理型模型必填** | 填 `low`。DeepSeek V4 这类模型默认高强度推理，会吃掉输出额度导致正文截断 |
| `GH_PAT` | 否 | 个人令牌，仅当需要从 Actions 里回写仓库时用 |

### ⚠️ GitHub Models 不可用（2026-09-22 实测）

代码里保留了 `github_models` 分支（用 Actions 内置 `GITHUB_TOKEN`，免费），但**实测是废的**：
对 `https://models.github.ai` 的任何请求——包括 `GET /`——都返回 `HTTP 200` + 纯文本 `OK`，
内置令牌和 PAT 都一样。runner 到 example.com / api.openai.com 的连通性正常，
所以这是 GitHub Models 服务端/网关本身的问题，不是我们的调用姿势不对。
（排查时试过：补 `Accept: application/vnd.github+json`、`X-GitHub-Api-Version`、
`api-version` 查询参数、换 `openai/gpt-4o` 等模型、换 `api.github.com/models/*` 路径，全部无效。）

→ **必须自备一个 OpenAI 兼容的 API 密钥**，DeepSeek / 智谱 / 硅基流动 / OpenRouter 都行，例如：

```
OPENAI_BASE_URL = https://api.deepseek.com/v1
OPENAI_API_KEY  = sk-xxxx
LLM_MODEL       = deepseek-chat
```

配好之后每天 19:00 自动生成；不配则故事那一步会直接失败（不会静默发旧故事）。

想自己写故事：手动触发时填 `llm_provider=none`，并提交 `stories/<YYYYMMDD>.json`
（格式见 `stories/20260921.json` 示例）。

## 用法

- **自动**：每晚 19:00（北京时间）。GitHub 的 schedule 在整点繁忙时会延迟几分钟，属正常。
- **手动**：Actions → 每日睡前故事 → Run workflow。可勾选"只出故事文本"或"跳过配乐"用于排障。
- **产物**：Actions 运行页的 Artifacts 里下载 mp3。

## 目录

```
.github/workflows/daily.yml   # 定时任务
run_daily.py                  # 主入口
pipeline/story.py             # 故事生成（LLM 可插拔）+ 角色音色映射
pipeline/tts.py               # 多角色 edge-tts
pipeline/music.py             # StepFun 配乐 + ffmpeg 混音
pipeline/push.py              # PushPlus 推送
stories/                      # 手工创作的故事（LLM_PROVIDER=none 时用）
```

## 内建的三条纪律（都是本机踩过的坑，不要删）

1. **强制 IPv4** —— DNS 对 `speech.platform.bing.com` 返回 IPv6 优先，而 IPv6 常常不通，
   表现为 TCP 静默挂起（不报错也不返回）。`pipeline/tts.py` 顶部 patch 了 `getaddrinfo`。
2. **硬超时 + 产物回收** —— 光有超时不够：edge_tts 常把音频写完却卡在收尾不返回，
   此时文件其实是好的。所以超时后会检查"文件是否停止增长且非空"，是就按成功处理。
   失败的残缺文件一定删除，不留残渣污染下次。
3. **推送闸门** —— 只要有一段降级就不推微信。宁可当晚没有，也不发残缺版。
   配乐不够长也直接回退纯人声，不要尾部静音。
4. **推理型模型要压 reasoning** —— DeepSeek V4 系列默认高强度思考，一次能烧掉 6800+ token，
   `max_tokens=8192` 时正文被截成半个 JSON（表现为"响应里没有 JSON"，不像报错，很容易误判）。
   对策：`max_tokens=32768` + `effort=low`（环境变量 `LLM_EFFORT`），
   外加"片段数 < 90 就重试一次"的兜底。

## 已知限制

- **edge-tts 是第三方服务，会故障**。2026-09-21 就大面积超时过（成功率一度 20-30%）。
  上云解决的是"本机开没开"，解决不了"微软服务端挂了"。故障当晚会自动降级并跳过推送。
- 配乐目前是整轨一段，本机那套"按剧情分 4 块 crossfade"还没搬过来。
