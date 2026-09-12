#!/bin/sh
# 备用入口：工作区包装脚本（日志追加到 output/cron.log；定时任务已移除，手动也可用）
ROOT="$(dirname "$0")/.."
cd "$ROOT"
exec scripts/run.sh >> output/cron.log 2>&1
