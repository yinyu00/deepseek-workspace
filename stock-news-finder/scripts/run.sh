#!/bin/sh
# 一键运行：拉新闻 → 构建词典 → LLM事件分类 → 匹配打分 → 微信推送
set -e
ROOT="$(dirname "$0")/.."
cd "$ROOT"
echo "=== 1/5 采集新闻 ==="; python3 scripts/fetch_news.py
echo "=== 2/5 构建词典 ==="; python3 scripts/build_dict.py
echo "=== 3/5 LLM事件分类 ==="; python3 scripts/llm_classify.py || echo "(LLM层失败，回退正则)"
echo "=== 4/5 匹配打分 ==="; python3 scripts/match_score.py
echo "=== 5/5 微信推送 ==="; python3 scripts/push_daily.py || echo "(推送失败，日报仍在 daily/"
