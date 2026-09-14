#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通用 Markdown 微信推送(Server酱 · Turbo 版)。

复用 stock-news-finder 的推送通道,但支持任意 md 文件:
    python push_md.py <md文件> [标题] [--key SCTxxxx]

- SendKey 来源:--key 参数 > 环境变量 SERVERCHAN_SENDKEY
- 免费版每天 5 条;单消息约 32KB 上限,超长自动截断
- 内容由脚本直接读取文件发送,不经过对话/网关
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

API = "https://sctapi.ftqq.com/{key}.send"
WECOM_API = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"


def get_key():
    if "--key" in sys.argv:
        return sys.argv[sys.argv.index("--key") + 1]
    return os.environ.get("SERVERCHAN_SENDKEY")


def build_content(path, title):
    md = open(path, encoding="utf-8").read()
    raw = md.encode("utf-8")
    if len(raw) > 30000:  # Server酱单消息约 32KB 上限,留余量
        md = md.encode("utf-8")[:29500].decode("utf-8", errors="ignore")
        md += "\n\n(超长已截断,完整版见本地文件)"
    return title or (md.splitlines() or ["Markdown 推送"])[0].lstrip("# "), md


def get_wecom():
    if "--wecom" in sys.argv:
        return sys.argv[sys.argv.index("--wecom") + 1]
    return os.environ.get("WECOM_WEBHOOK")


def md_for_wecom(md):
    """表格行 → 列表行(企业微信 markdown 不支持表格)。"""
    out = []
    for ln in md.split("\n"):
        s = ln.strip()
        if s.startswith("|"):
            if set(s) <= set("|-: "):
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]
            out.append("  ".join(c for c in cells if c))
        else:
            out.append(ln)
    return "\n".join(out)


def _split_utf8(text, limit=3800):
    segs, cur, n = [], [], 0
    for line in text.split("\n"):
        lb = len(line.encode("utf-8")) + 1
        if n + lb > limit and cur:
            segs.append("\n".join(cur))
            cur, n = [], 0
        cur.append(line)
        n += lb
    if cur:
        segs.append("\n".join(cur))
    return segs


def push_wecom(webhook, title, content):
    """企业微信群机器人:markdown 自动分段(单条 4096 字节上限)。"""
    key = webhook.split("key=", 1)[1].split("&", 1)[0] if "key=" in webhook else webhook
    segs = _split_utf8(md_for_wecom(content))
    ok, resp = True, ""
    for i, seg in enumerate(segs):
        head = "# %s%s" % (title, "(续%d)" % (i + 1) if i else "")
        body = json.dumps({"msgtype": "markdown",
                           "markdown": {"content": (head + "\n" + seg)[:4000]}}
                          ).encode("utf-8")
        req = urllib.request.Request(WECOM_API + "?key=" + key, data=body,
                                     headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", errors="replace")
        ok = ok and '"errcode":0' in resp
        if len(segs) > 1:
            time.sleep(1)
    return ok, resp


def push(key, title, content):
    # 用 Python 自带 OpenSSL 栈:沙箱受限令牌下 schannel 无法建立 TLS 凭据,
    # curl.exe / Invoke-WebRequest 全部失败,urllib 不受影响
    data = urllib.parse.urlencode({"title": title, "desp": content}).encode()
    req = urllib.request.Request(API.format(key=key), data=data, method="POST")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="replace")


def main():
    try:  # Windows 控制台 GBK 兜底,防 emoji 打印崩溃
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    args = sys.argv[1:]
    paths = [a for a in args if not a.startswith("--") and os.path.exists(a)]
    if not paths:
        print("[err] 用法: python push_md.py <md文件> [标题] [--key SCTxxxx]")
        sys.exit(1)
    path = paths[0]
    rest = [a for a in args if a != path and a != "--key"]
    title = rest[0] if rest else None

    key = get_key()  # 校验推迟到选通道之后(--wecom 时不需要 Server酱 key)

    title, content = build_content(path, title)
    wecom = get_wecom()
    if wecom:  # 企业微信优先
        ok, resp = push_wecom(wecom, title, content)
        print(("✅ 推送成功(企业微信)" if ok else "❌ 推送失败") + f" → {resp[:200]}")
        sys.exit(0 if ok else 1)
    if not key:
        print("[err] 无 SendKey(--key 或环境变量 SERVERCHAN_SENDKEY)")
        sys.exit(1)
    resp = push(key, title, content)
    ok = '"code":0' in resp or '"errno":0' in resp
    print(("✅ 推送成功" if ok else "❌ 推送失败") + f" → {resp[:200]}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
