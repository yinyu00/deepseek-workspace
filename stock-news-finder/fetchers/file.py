#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地文件采集器插件：读 JSON / JSONL 数组文件。

cfg:
  path:    文件路径（相对项目根，即 fetchers/ 的上一级）
  fields:  {title, body, time} 字段名映射（默认同名）
  name:    源名（作为 source 字段）
"""
import json
import os
import re
import sys
import tempfile
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根


def _norm_time(v):
    """时间归一化：秒级时间戳 → 'YYYY-MM-DD HH:MM:SS'；其余原样字符串。"""
    s = str(v or "").strip()
    if s.isdigit() and len(s) == 10:
        try:
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(s)))
        except (ValueError, OverflowError, OSError):
            return s
    return s


def _load_rows(path):
    with open(path, encoding="utf-8") as f:
        text = f.read().strip()
    if not text:
        return []
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):  # dict 包数组兜底
            for k in ("data", "list", "items", "rows"):
                if isinstance(data.get(k), list):
                    return data[k]
        return []
    except json.JSONDecodeError:
        # JSONL：每行一个 JSON 对象
        rows = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                print(f"[warn] file 源跳过非法行: {line[:50]}", file=sys.stderr)
                continue
            if isinstance(obj, dict):
                rows.append(obj)
        return rows


def fetch(cfg: dict) -> list:
    path = os.path.join(BASE, cfg["path"])
    if not os.path.exists(path):
        print(f"[warn] 文件源不存在: {path}", file=sys.stderr)
        return []
    try:
        rows = _load_rows(path)
    except Exception as e:
        print(f"[warn] file 源 {path} 读取失败: {e}", file=sys.stderr)
        return []
    fields = cfg.get("fields", {})
    fk_title = fields.get("title", "title")
    fk_body = fields.get("body", "body")
    fk_time = fields.get("time", "time")
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        body = str(r.get(fk_body, "") or "").strip()
        title = str(r.get(fk_title, "") or "").strip() or body[:40]
        out.append({
            "title": title,
            "body": body,
            "time": _norm_time(r.get(fk_time, "")),
            "source": cfg.get("name", "file"),
            "url": str(r.get("url", "") or ""),
            "stocks": [],
        })
    return out


def selftest() -> bool:
    tmp = os.path.join(tempfile.gettempdir(), "sn_file_selftest.json")
    sample = [
        {"title": "测试新闻标题", "body": "这是测试正文。", "time": 1700000000, "url": "https://example.com/a"},
        {"title": "", "body": "无标题新闻的正文内容，标题应取正文前40字。", "time": "2024-01-01 08:00:00", "url": ""},
    ]
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(sample, f, ensure_ascii=False)
        # path 是相对项目根的，这里用绝对路径测（os.path.join 对绝对路径右者优先）
        cfg = {"type": "file", "name": "file-selftest", "path": tmp,
               "fields": {"title": "title", "body": "body", "time": "time"}}
        items = fetch(cfg)
        if len(items) != 2:
            print(f"[selftest:file] 条数不符: {len(items)}", file=sys.stderr)
            return False
        if items[0]["time"] != time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(1700000000)):
            print(f"[selftest:file] 时间戳转换错误: {items[0]['time']!r}", file=sys.stderr)
            return False
        if not items[1]["title"] or items[1]["title"] != items[1]["body"][:40]:
            print(f"[selftest:file] 无标题兜底错误: {items[1]['title']!r}", file=sys.stderr)
            return False
        if items[0]["stocks"] != [] or items[0]["source"] != "file-selftest":
            print(f"[selftest:file] source/stocks 错误", file=sys.stderr)
            return False
        print(f"[selftest:file] ok, {len(items)} 条, 样例: "
              f"{ {k: items[0][k] for k in ('title', 'time', 'source', 'url')} }")
        return True
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


if __name__ == "__main__":
    selftest()
