#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通用 JSON 接口采集器插件。

cfg:
  url:    接口地址（GET，返回 JSON）
  fields: {title, body, time} 字段名映射（默认同名）
  name:   源名（作为 source 字段）
"""
import json
import sys
import time
import urllib.request

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


def _http_get_json(url, timeout=15):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def _norm_time(v):
    """时间归一化：秒级时间戳 → 'YYYY-MM-DD HH:MM:SS'（本地时区）；其余原样字符串。"""
    s = str(v or "").strip()
    if s.isdigit() and len(s) == 10:
        try:
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(s)))
        except (ValueError, OverflowError, OSError):
            return s
    return s


def _extract_rows(data):
    """响应可能是数组，或 dict 包数组（依次找 data/list/items/rows 键，含嵌套一层）。"""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("data", "list", "items", "rows"):
            if k in data:
                v = data[k]
                if isinstance(v, list):
                    return v
                if isinstance(v, dict):  # 再往下一层（如 data.items）
                    for k2 in ("list", "items", "rows"):
                        if isinstance(v.get(k2), list):
                            return v[k2]
    return []


def _map_rows(rows, cfg):
    fields = cfg.get("fields", {})
    fk_title = fields.get("title", "title")
    fk_body = fields.get("body", "body")
    fk_time = fields.get("time", "time")
    out = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        body = str(r.get(fk_body, "") or "").strip()
        title = str(r.get(fk_title, "") or "").strip() or body[:40]
        out.append({
            "title": title,
            "body": body,
            "time": _norm_time(r.get(fk_time, "")),
            "source": cfg.get("name", "http-json"),
            "url": str(r.get("url", "") or ""),
            "stocks": [],
        })
    return out


def fetch(cfg: dict) -> list:
    try:
        data = _http_get_json(cfg["url"])
    except Exception as e:
        print(f"[warn] http-json {cfg.get('name', cfg.get('url', '?'))} 请求失败: {e}",
              file=sys.stderr)
        return []
    try:
        return _map_rows(_extract_rows(data), cfg)
    except Exception as e:
        print(f"[warn] http-json {cfg.get('name', '?')} 解析失败: {e}", file=sys.stderr)
        return []


def selftest() -> bool:
    """用华尔街见闻真实接口测一页，校验字段格式。"""
    cfg = {
        "type": "http-json",
        "name": "wallstreetcn-live",
        "url": "https://api-one-wscn.awtmt.com/apiv1/content/lives?channel=global-channel&limit=3",
        "fields": {"title": "title", "body": "content_text", "time": "display_time"},
    }
    items = fetch(cfg)
    if not items:
        print("[selftest:http-json] 未取到数据", file=sys.stderr)
        return False
    import re
    for it in items:
        if not it["title"] or not it["body"]:
            print(f"[selftest:http-json] 字段缺失: {it}", file=sys.stderr)
            return False
        if it["time"] and not re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", it["time"]):
            print(f"[selftest:http-json] 时间格式错误: {it['time']!r}", file=sys.stderr)
            return False
        if it["source"] != "wallstreetcn-live" or it["stocks"] != []:
            print(f"[selftest:http-json] source/stocks 错误: {it}", file=sys.stderr)
            return False
    print(f"[selftest:http-json] ok, {len(items)} 条, 样例: "
          f"{ {k: items[0][k] for k in ('title', 'time', 'source', 'url')} }")
    return True


if __name__ == "__main__":
    selftest()
