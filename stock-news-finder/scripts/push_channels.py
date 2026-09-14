#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一推送通道:企业微信群机器人(主)+ Server酱 Turbo(备)。

凭据来源(优先级高→低):命令行参数 > 环境变量 > data/push_config.json
配置文件格式:
    {"channel": "wecom", "wecom_webhook": "https://qyapi...key=xxx",
     "serverchan_key": "SCTxxxx"}

企业微信机器人限制:单条 markdown 上限 4096 字节(自动分段)、20 条/分钟、
不支持表格(本模块自动把表格行转为 " · " 连接的列表行)。
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE, "data", "push_config.json")
WECOM_API = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"
SERVERCHAN_API = "https://sctapi.ftqq.com/{key}.send"


# ---------------------------------------------------------------- 配置

def load_config(wecom=None, serverchan=None, channel=None):
    """合并:参数 > 环境变量 > 配置文件。返回 dict。"""
    cfg = {}
    if os.path.exists(CONFIG_PATH):
        try:
            cfg = json.load(open(CONFIG_PATH, encoding="utf-8")) or {}
        except Exception as e:
            print("[warn] push_config.json 解析失败:", e)
    cfg["wecom_webhook"] = wecom or os.environ.get("WECOM_WEBHOOK") or cfg.get("wecom_webhook")
    cfg["serverchan_key"] = (serverchan or os.environ.get("SERVERCHAN_SENDKEY")
                             or cfg.get("serverchan_key"))
    cfg["channel"] = channel or os.environ.get("PUSH_CHANNEL") or cfg.get("channel") or "wecom"
    return cfg


def _wecom_key(webhook):
    """从完整 webhook URL 提取 key;已是纯 key 则原样返回。"""
    if "key=" in webhook:
        return webhook.split("key=", 1)[1].split("&", 1)[0]
    return webhook


# ------------------------------------------------------------ 格式转换

def md_for_wecom(md):
    """表格行 → 列表行(企业微信 markdown 不支持表格)。"""
    out = []
    for ln in md.split("\n"):
        s = ln.strip()
        if s.startswith("|"):
            if set(s) <= set("|-: "):     # 表头分隔行 |---|---| 丢弃
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]
            cells = [c for c in cells if c]
            out.append("  ".join(cells))
        else:
            out.append(ln)
    return "\n".join(out)


def _split_utf8(text, limit=3800):
    """按行切段,每段 utf-8 字节数不超 limit(单条上限 4096,留头部余量)。"""
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


# ---------------------------------------------------------------- 发送

def push_wecom(webhook, title, md):
    """企业微信机器人,markdown 自动分段。返回 (ok, 最后响应)。"""
    key = _wecom_key(webhook)
    segs = _split_utf8(md_for_wecom(md))
    ok, resp = True, ""
    for i, seg in enumerate(segs):
        head = "# %s%s" % (title, "(续%d)" % (i + 1) if i else "")
        body = json.dumps({"msgtype": "markdown",
                           "markdown": {"content": (head + "\n" + seg)[:4000]}}
                          ).encode("utf-8")
        req = urllib.request.Request(WECOM_API + "?key=" + key, data=body,
                                     headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", errors="replace")
        ok = ok and ('"errcode":0' in resp or '"errcode": 0' in resp)
        if len(segs) > 1:
            time.sleep(1)               # 20 条/分钟,分段间隔 1s
    return ok, resp


def push_serverchan(key, title, md):
    """Server酱 Turbo(urllib OpenSSL 栈,兼容受限沙箱)。"""
    data = urllib.parse.urlencode({"title": title, "desp": md}).encode()
    req = urllib.request.Request(SERVERCHAN_API.format(key=key), data=data, method="POST")
    resp = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", errors="replace")
    return '"code":0' in resp, resp


def push(title, md, cfg=None):
    """按 cfg['channel'] 发送,自动回退:wecom 失败→serverchan。"""
    cfg = cfg or load_config()
    order = ([cfg["channel"]] if cfg.get("channel") in ("wecom", "serverchan")
             else ["wecom", "serverchan"])
    if "serverchan" not in order:
        order.append("serverchan")       # 始终保留回退通道
    for ch in order:
        if ch == "wecom" and cfg.get("wecom_webhook"):
            ok, resp = push_wecom(cfg["wecom_webhook"], title, md)
            print("[wecom] %s → %s" % ("✅" if ok else "❌", resp[:150]))
            if ok:
                return True
        elif ch == "serverchan" and cfg.get("serverchan_key"):
            ok, resp = push_serverchan(cfg["serverchan_key"], title, md)
            print("[serverchan] %s → %s" % ("✅" if ok else "❌", resp[:150]))
            if ok:
                return True
    return False
