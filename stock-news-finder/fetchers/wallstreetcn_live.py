#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""华尔街见闻快讯采集器插件（type: wallstreetcn-live）。

接口：https://api-one-wscn.awtmt.com/apiv1/content/lives?channel=&limit=&page=（纯 JSON）。
字段特点：title 可能为空（正文在 content_text，取前 40 字做 title）、display_time 为
秒级时间戳（字符串或数字）、uri 为原文链接。stocks 恒为 []。
"""
import json
import sys
import time
import urllib.request

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
SOURCE = "wallstreetcn"


def _get_json(url, timeout=15):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def _fmt_time(ts):
    """display_time 秒级时间戳 → 'YYYY-MM-DD HH:MM:SS'（本地时区），兼容字符串/数字。"""
    try:
        ts = int(float(str(ts)))
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
    except (ValueError, TypeError):
        return ""


def fetch(cfg):
    channel = cfg.get("channel", "global-channel")
    limit = int(cfg.get("limit", 50))
    max_pages = int(cfg.get("max_pages", 4))
    stop_date = cfg.get("_stop_date") or None  # "YYYY-MM-DD"：翻页到该日 00:00 为止

    items = []
    for page in range(1, max_pages + 1):
        url = (f"https://api-one-wscn.awtmt.com/apiv1/content/lives"
               f"?channel={channel}&limit={limit}&page={page}")
        try:
            data = _get_json(url)
        except Exception as e:
            print(f"[warn] 华尔街见闻第{page}页失败: {e}", file=sys.stderr)
            break
        rows = (data.get("data") or {}).get("items") or []
        if not rows:
            break
        stop = False
        for r in rows:
            tm = _fmt_time(r.get("display_time"))
            if stop_date and tm[:10] < stop_date:
                stop = True  # 已翻到边界日期之前，本条不收
                break
            body = str(r.get("content_text") or "").strip()
            title = str(r.get("title") or "").strip() or body[:40]
            items.append({
                "title": title,
                "body": body,
                "time": tm,
                "source": SOURCE,
                "url": str(r.get("uri") or ""),
                "stocks": [],
            })
        if stop:
            break
    return items


def selftest():
    """真实抓 1 页，校验字段格式。"""
    try:
        items = fetch({"channel": "global-channel", "limit": 20, "max_pages": 1})
    except Exception as e:
        print(f"[warn] selftest 网络失败: {e}", file=sys.stderr)
        return False
    if not items:
        print("[warn] selftest: 未抓到数据", file=sys.stderr)
        return False
    import re
    pat = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
    for n in items:
        if set(n) != {"title", "body", "time", "source", "url", "stocks"}:
            print(f"[warn] selftest: 字段不齐 {sorted(n)}", file=sys.stderr)
            return False
        if n["source"] != SOURCE or n["stocks"] != []:
            print("[warn] selftest: source/stocks 不符", file=sys.stderr)
            return False
        if not isinstance(n["title"], str) or not isinstance(n["body"], str):
            print("[warn] selftest: title/body 非字符串", file=sys.stderr)
            return False
        if not pat.match(n["time"]):
            print(f"[warn] selftest: time 格式错误 {n['time']!r}", file=sys.stderr)
            return False
    print(f"[ok] selftest: {len(items)} 条校验通过")
    return True


if __name__ == "__main__":
    print(selftest())
