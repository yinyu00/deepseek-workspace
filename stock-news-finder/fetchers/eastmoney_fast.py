#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""东方财富财经频道滚动快讯采集器插件（type: eastmoney-fast）。

接口：np-listapi.eastmoney.com getFastNewsList 公开 JSON。
要点（踩坑记录）：
- URL 必须带 req_trace（毫秒时间戳），否则报缺参数
- 翻页用游标 data.sortEnd，不是页码递增
- stop_date：新闻 time[:10] < stop_date 时停止翻页（历史回补边界）
- max_pages=40 安全上限（≈2000 条 ≈ 4 个交易日）
- stockList 如 "1.600525"，取点号后 6 位数字代码
- url 用新闻 ID 构造 https://finance.eastmoney.com/a/{nid}.html
- showTime 已是 "YYYY-MM-DD HH:MM:SS" 字符串，直接用
"""
import datetime as _dt
import json
import sys
import time
import urllib.request

SOURCE = "eastmoney-fast"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


def _http_get_json(url, timeout=15):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def _parse_rows(data, stop_date):
    """解析一页 fastNewsList；返回 (items, reached_before_stop)。"""
    rows = (data.get("data") or {}).get("fastNewsList") or []
    items = []
    for r in rows:
        tm = str(r.get("showTime") or "")
        if stop_date and tm[:10] < stop_date:
            return items, True  # 已翻到边界日期之前，本条不收
        nid = str(r.get("code") or "")
        body = str(r.get("summary") or "")
        title = str(r.get("title") or "").strip() or body[:40]
        # 官方标注的关联股票代码（如 "1.600525"，1=沪 0=深），权威性高于文本匹配
        stock_list = []
        for s in r.get("stockList") or []:
            code = str(s).split(".")[-1].strip()
            if len(code) == 6 and code.isdigit():
                stock_list.append(code)
        items.append({
            "title": title,
            "body": body,
            "time": tm,
            "source": SOURCE,
            "url": f"https://finance.eastmoney.com/a/{nid}.html" if nid else "",
            "stocks": stock_list,
        })
    return items, False


def _fetch_pages(stop_date, max_pages, page_limit=None):
    """翻页抓取。page_limit 用于 selftest（只抓 1 页）。"""
    items = []
    page = 1
    sort_end = ""
    while page <= max_pages:
        url = (
            "https://np-listapi.eastmoney.com/comm/web/getFastNewsList"
            f"?client=web&biz=web_724&fastColumn=102&sortEnd={sort_end}"
            f"&pageSize=50&pageNo={page}&req_trace={int(time.time() * 1000)}"
        )
        try:
            data = _http_get_json(url)
        except Exception as e:
            print(f"[warn] 东财第{page}页失败: {e}", file=sys.stderr)
            break
        rows = (data.get("data") or {}).get("fastNewsList") or []
        if not rows:
            break
        page_items, stop = _parse_rows(data, stop_date)
        items.extend(page_items)
        if stop:
            break
        # 翻页游标：sortEnd 是下一页起点，不是页码递增
        sort_end = (data.get("data") or {}).get("sortEnd") or sort_end
        if page_limit and page >= page_limit:
            break
        page += 1
    return items


def fetch(cfg: dict) -> list:
    """采集器插件统一入口。cfg["_stop_date"] 由 loader 注入（None 默认今天）。"""
    stop_date = cfg.get("_stop_date") or _dt.date.today().strftime("%Y-%m-%d")
    max_pages = int(cfg.get("max_pages", 40))
    return _fetch_pages(stop_date, max_pages)


def selftest() -> bool:
    """真实调用接口抓 1 页，校验字段格式。"""
    try:
        items = _fetch_pages(stop_date=None, max_pages=1, page_limit=1)
    except Exception as e:
        print(f"[warn] selftest 网络失败: {e}", file=sys.stderr)
        return False
    if not items:
        print("[warn] selftest 未取到数据", file=sys.stderr)
        return False
    import re
    tm_re = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
    for it in items[:5]:
        if set(it) != {"title", "body", "time", "source", "url", "stocks"}:
            return False
        if not tm_re.match(it["time"]):
            return False
        if it["source"] != SOURCE:
            return False
        if not isinstance(it["stocks"], list) or not all(
            len(c) == 6 and c.isdigit() for c in it["stocks"]
        ):
            return False
        if it["url"] and not it["url"].startswith("https://finance.eastmoney.com/a/"):
            return False
    return True


if __name__ == "__main__":
    print(selftest())
