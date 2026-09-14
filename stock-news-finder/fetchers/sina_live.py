#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新浪财经 7x24 全球快讯采集器插件（type: sina-live）。

定位：替代财联社电报（2026 年免费接口已全关，404）的实时快讯源，
公开稳定无签名。速度稍逊财联社但同一量级，宏观+全球+A股混合流。

接口：zhibo.sina.com.cn/api/zhibo/feed（公开 JSON，无需签名）。
要点（踩坑记录，2026-09-14 实测）：
- feed 是 dict（含 list/pages），不是数组
- create_time 已是 "YYYY-MM-DD HH:MM:SS" 字符串，无需转换
- rich_text 里【】内为标题；docurl 可能为空
- 翻页用 page 递增，按 stop_date 边界停止（历史回补用）
"""
import sys
import urllib.request

SOURCE = "sina-live"
API = ("https://zhibo.sina.com.cn/api/zhibo/feed"
       "?page={page}&page_size={ps}&zhibo_id=152&tag_id=0&dire=f&dpc=1")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://finance.sina.com.cn/7x24/",
}


def _get_json(url, timeout=15):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.json() if hasattr(r, "json") else __import__("json").loads(r.read().decode("utf-8", "ignore"))


def _parse_rows(data, stop_date):
    """解析一页 feed.list；返回 (items, reached_before_stop)。"""
    rows = ((data.get("result") or {}).get("data") or {}).get("feed", {}).get("list") or []
    items = []
    for x in rows:
        tm = str(x.get("create_time") or "")
        if stop_date and tm[:10] < stop_date:
            return items, True
        text = str(x.get("rich_text") or "").replace("\n", " ").strip()
        if not text:
            continue
        # 【标题】正文 → 拆分；无【】时标题取正文前 40 字
        if text.startswith("【") and "】" in text[:60]:
            title, _, body = text[1:].partition("】")
        else:
            title, body = text[:40], text
        items.append({
            "title": title.strip(),
            "body": body.strip() or title,
            "time": tm,
            "source": SOURCE,
            "url": str(x.get("docurl") or ""),
            "stocks": [],
        })
    return items, False


def _fetch_pages(stop_date, max_pages, page_limit=None):
    import datetime as _dt
    items = []
    page = 1
    while page <= max_pages:
        url = API.format(page=page, ps=50)
        try:
            data = _get_json(url)
        except Exception as e:
            print(f"[warn] 新浪7x24 第{page}页失败: {e}", file=sys.stderr)
            break
        page_items, stop = _parse_rows(data, stop_date)
        if not page_items and stop:
            break
        items.extend(page_items)
        if stop or (page_limit and page >= page_limit):
            break
        page += 1
    return items


def fetch(cfg: dict) -> list:
    """采集器插件统一入口。cfg["_stop_date"] 由 loader 注入。"""
    import datetime as _dt
    stop_date = cfg.get("_stop_date") or _dt.date.today().strftime("%Y-%m-%d")
    max_pages = int(cfg.get("max_pages", 20))
    return _fetch_pages(stop_date, max_pages)


def selftest() -> bool:
    import re
    try:
        items = _fetch_pages(stop_date=None, max_pages=1, page_limit=1)
    except Exception as e:
        print(f"[warn] selftest 网络失败: {e}", file=sys.stderr)
        return False
    if not items:
        print("[warn] selftest 未取到数据", file=sys.stderr)
        return False
    tm_re = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
    for it in items[:5]:
        if set(it) != {"title", "body", "time", "source", "url", "stocks"}:
            return False
        if not tm_re.match(it["time"]) or it["source"] != SOURCE:
            return False
        if not isinstance(it["stocks"], list):
            return False
    return True


if __name__ == "__main__":
    print(selftest())
