#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日报微信推送（Server酱 · Turbo 版）。

- SendKey 来源：环境变量 SERVERCHAN_SENDKEY（建议放 ~/.zshrc）或 --key 参数
- 免费版每天 5 条，日报 1 条/天足够
- 推送内容：日报概览表 + 头部明细 + 宏观板块（Server酱 markdown 单消息约 32KB 上限，超长截断）

用法：
    python3 push_daily.py                    # 推今天 daily/yyyymmdd.md
    python3 push_daily.py 20260825           # 推指定日期
    python3 push_daily.py --key SCTxxxx      # 显式指定 key
"""
import os
import subprocess
import sys
import urllib.parse
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAILY = os.path.join(BASE, "daily")
API = "https://sctapi.ftqq.com/{key}.send"


def get_key():
    if "--key" in sys.argv:
        return sys.argv[sys.argv.index("--key") + 1]
    key = os.environ.get("SERVERCHAN_SENDKEY")
    if key:
        return key
    # 登录 shell 兜底（本机习惯把 key 写 ~/.zshrc）
    try:
        r = subprocess.run(["zsh", "-ic", "echo $SERVERCHAN_SENDKEY"],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() or None
    except Exception:
        return None


def build_content(date):
    path = os.path.join(DAILY, date + ".md")
    if not os.path.exists(path):
        return None, None
    md = open(path, encoding="utf-8").read()
    title = f"股票信号日报 {date}"
    # Server酱 消息体上限约 32KB：超长时保留概览表 + 宏观板块
    if len(md.encode()) > 30000:
        overview = md.split("## 明细")[0]
        macro = ""
        if "## 宏观/地缘动态" in md:
            macro = "## 宏观/地缘动态" + md.split("## 宏观/地缘动态")[1]
        md = overview + "\n（明细过长已截断，完整版见本地文件）\n\n" + macro
    return title, md


def push(key, title, content):
    data = urllib.parse.urlencode({"title": title, "desp": content}).encode()
    # 走系统代理（外网接口）；curl 比 urllib 兼容性好
    r = subprocess.run(
        ["curl", "-s", "-m", "20", "-X", "POST", "-d", data.decode(), API.format(key=key)],
        capture_output=True, text=True)
    return r.stdout


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--") and not a == "20260825" or a.isdigit()]
    date = next((a for a in sys.argv[1:] if a.isdigit() and len(a) == 8), datetime.now().strftime("%Y%m%d"))
    key = get_key()
    if not key:
        print("[err] 无 SERVERCHAN_SENDKEY（sct.ftqq.com 扫码获取，写入 ~/.zshrc）")
        sys.exit(1)
    title, content = build_content(date)
    if not content:
        print(f"[err] 日报不存在: daily/{date}.md（先跑 scripts/run.sh）")
        sys.exit(1)
    resp = push(key, title, content)
    ok = '"code":0' in resp or '"errno":0' in resp
    print(("✅ 推送成功" if ok else "❌ 推送失败") + f" → {resp[:200]}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
