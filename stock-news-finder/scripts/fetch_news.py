#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""采集层 loader：按 sources.json 动态加载 fetchers/<type>.py 插件，一源一模块。

插件接口见 fetchers/SPEC.md：fetch(cfg) -> [news]，selftest() -> bool。
新增新闻源 = 新建 fetchers/<type>.py + sources.json 加条目，本文件不改。

用法：
    python3 fetch_news.py                     # 抓当日（今天 00:00 起）
    python3 fetch_news.py --since 2026-08-21  # 回补：抓该日起全部
    python3 fetch_news.py --selftest          # 逐源自测
"""
import importlib
import json
import os
import sys
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根 = scripts/ 上一级
FETCHERS_DIR = os.path.join(BASE, "fetchers")
SOURCES = os.path.join(BASE, "sources.json")
OUT_DIR = os.path.join(BASE, "output")
OUT = os.path.join(OUT_DIR, "raw_news.json")
RAW_DIR = os.path.join(BASE, "raw")

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


def http_get_json(url, timeout=15):
    """通用 HTTP GET → JSON（供 loader 自用；插件自带网络逻辑）。"""
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def load_fetcher(stype):
    """动态加载 fetchers/<type>.py（type 中 - 转 _）。"""
    mod_name = stype.replace("-", "_")
    path = os.path.join(FETCHERS_DIR, mod_name + ".py")
    if not os.path.exists(path):
        return None
    if FETCHERS_DIR not in sys.path:
        sys.path.insert(0, FETCHERS_DIR)
    return importlib.import_module(mod_name)


def run_all(since=None):
    import datetime as _dt
    with open(SOURCES, encoding="utf-8") as f:
        sources = json.load(f)
    all_news = []
    for cfg in sources:
        if not cfg.get("enabled", False):
            print(f"[skip] 未启用: {cfg.get('name')}")
            continue
        stype = cfg.get("type")
        mod = load_fetcher(stype)
        if mod is None:
            print(f"[warn] 无采集器插件 {stype}: {cfg.get('name')}", file=sys.stderr)
            continue
        try:
            # 注入停止日期：默认今天 00:00（抓满当天）；回补模式用 since
            cfg["_stop_date"] = since or _dt.date.today().strftime("%Y-%m-%d")
            items = mod.fetch(cfg)
            print(f"[ok] {cfg.get('name')} ({stype}): {len(items)} 条")
            all_news.extend(items)
        except Exception as e:
            print(f"[err] {cfg.get('name')}: {e}", file=sys.stderr)

    # 去重（按标题）
    seen = set()
    uniq = []
    for n in all_news:
        key = (n.get("title") or "").strip()
        if key and key not in seen:
            seen.add(key)
            uniq.append(n)
    return uniq


def archive_by_day(uniq):
    """按日归档 raw/yyyymmdd.json（增量合并，以旧归档为去重基准）。"""
    os.makedirs(RAW_DIR, exist_ok=True)
    by_day = {}
    for n in uniq:
        d = (n.get("time") or "")[:10].replace("-", "")
        if d:
            by_day.setdefault(d, []).append(n)
    for d, items in sorted(by_day.items()):
        path = os.path.join(RAW_DIR, d + ".json")
        merged = items
        if os.path.exists(path):
            try:
                old = json.load(open(path, encoding="utf-8"))
                old_titles = {x["title"].strip() for x in old}
                merged = old + [x for x in items if x["title"].strip() not in old_titles]
            except Exception:
                pass
        with open(path, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=1)
        print(f"归档 raw/{d}.json: {len(merged)} 条")


def main():
    since = None
    if "--since" in sys.argv:
        since = sys.argv[sys.argv.index("--since") + 1]
    if "--selftest" in sys.argv:
        with open(SOURCES, encoding="utf-8") as f:
            for cfg in json.load(f):
                mod = load_fetcher(cfg.get("type", ""))
                st = mod.selftest() if mod else None
                print(f"selftest {cfg.get('type')}: {'✅' if st else '❌'}")
        return
    uniq = run_all(since)
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(uniq, f, ensure_ascii=False, indent=1)
    print(f"合计 {len(uniq)} 条（去重后）→ {OUT}")
    archive_by_day(uniq)


if __name__ == "__main__":
    main()
