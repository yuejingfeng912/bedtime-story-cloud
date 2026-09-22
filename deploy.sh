#!/usr/bin/env bash
# 一键把本仓库推到 GitHub 并配好 Secrets。
# 前置：先跑一次 gh auth login（交互式，只在浏览器点一下）
# 用法：bash deploy.sh [仓库名]      默认 bedtime-story-factory
set -e
REPO="${1:-bedtime-story-factory}"
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

if ! gh auth status >/dev/null 2>&1; then
  echo "❌ 还没登录 GitHub。请先执行："
  echo "     gh auth login -h github.com -w"
  exit 1
fi

git branch -M main 2>/dev/null || true

if git remote get-url origin >/dev/null 2>&1; then
  echo "→ 推送到已有 origin"
  git push -u origin main
else
  echo "→ 创建私有仓库 $REPO 并推送"
  gh repo create "$REPO" --private --source=. --remote=origin --push
fi

# ---- Secrets ----
PARENT="$(dirname "$HERE")"
TOKEN="$(sed -n 's/.*PUSHPLUS_TOKEN = "\(.*\)".*/\1/p' "$PARENT/_daily_story_push.py" | head -1)"
if [ -n "$TOKEN" ]; then
  gh secret set PUSHPLUS_TOKEN --body "$TOKEN"
  echo "  ✓ PUSHPLUS_TOKEN"
else
  echo "  ⚠️ 没找到 PUSHPLUS_TOKEN，跳过"
fi

if [ -f "$PARENT/stepfun_key.txt" ]; then
  gh secret set STEPFUN_KEY --body "$(tr -d '\r\n' < "$PARENT/stepfun_key.txt")"
  echo "  ✓ STEPFUN_KEY"
else
  echo "  ⚠️ 没有 stepfun_key.txt，跳过配乐密钥"
fi

echo ""
echo "✅ 完成。下一步："
echo "   打开 $(gh repo view --json url -q .url)/actions 手动 Run workflow 验证一次"
