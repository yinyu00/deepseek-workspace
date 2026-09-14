#!/bin/sh
# 一键运行：拉新闻 → 构建词典 → LLM事件分类 → 匹配打分 → 推荐 → 推送 → 日历 → 复盘
set -e
ROOT="$(dirname "$0")/.."
cd "$ROOT"
echo "=== 1/6 采集新闻 ==="; python3 scripts/fetch_news.py
echo "=== 2/6 构建词典 ==="; python3 scripts/build_dict.py
echo "=== 3/6 LLM事件分类 ==="; python3 scripts/llm_classify.py || echo "(LLM层失败，回退正则)"
echo "=== 4/6 匹配打分 ==="; python3 scripts/match_score.py
echo "=== 5/8 推荐层 ==="; python3 scripts/recommend.py || echo "(推荐层失败，不阻断)"
echo "=== 6/8 微信推送 ==="; python3 scripts/push_daily.py || echo "(推送失败，日报仍在 daily/"
echo "=== 7/8 财报日历 ==="; python3 scripts/report_calendar.py --push || echo "(财报日历失败，不阻断)"
echo "=== 8/8 昨日推荐复盘 ==="; python3 scripts/review.py || echo "(无昨日推荐或行情失败，跳过)"
