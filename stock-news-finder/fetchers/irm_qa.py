#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""互动易（深交所投资者关系互动平台）采集器插件（type: irm-qa）。

信息价值：董秘亲笔回复=公司官方口径，常领先媒体确认业务布局
（"公司在XX领域有业务/订单"）。attachedContent 是回复原文。

接口：irm.cninfo.com.cn/newircs/index/search（公开，POST）。
要点（2026-09-14 实测）：
- 空关键词 = 全量时间流（按最新排序，6 万+ 条在库）
- searchTypes=11 问答型；翻页 pageNo 递增
- attachedContent 空=尚未回复，跳过（提问无价值，回复才是信号）
- 时效字段：updateDate/attachedPubDate 毫秒时间戳
- 噪声控制：全站一天数千条，垃圾提问占 90%+，必须强信号关键词过滤
"""
import datetime as _dt
import re
import sys
import time
import urllib.parse
import urllib.request

SOURCE = "irm-qa"
API = "https://irm.cninfo.com.cn/newircs/index/search"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://irm.cninfo.com.cn/",
    "Content-Type": "application/x-www-form-urlencoded",
}
# 强信号关键词：回复/提问中命中其一才收（订单/产能/前沿业务/资本运作）
SIGNAL_KW = re.compile(
    r"(订单|中标|合同|产能|量产|投产|在手|人工智能|AI|机器人|算力|芯片|半导体|"
    r"固态电池|低空经济|回购|增持|并购|重组|业绩|超预期|海外|出海|涨价|提价)"
)


def _post_page(page, page_size, timeout=15):
    body = urllib.parse.urlencode({
        "pageNo": page, "pageSize": page_size, "searchTypes": "11", "keyWord": "",
    }).encode()
    req = urllib.request.Request(API, data=body, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return __import__("json").loads(r.read().decode("utf-8", "ignore"))


def _fmt_time(ts_ms):
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(ts_ms) / 1000))
    except (ValueError, TypeError, OSError):
        return ""


def _parse_rows(results, stop_date, keep_all):
    """解析一页；返回 (items, reached_before_stop)。"""
    items = []
    for x in results or []:
        reply = str(x.get("attachedContent") or "").strip()
        if not reply:                      # 未回复的提问无信号价值
            continue
        ask = str(x.get("mainContent") or "").strip()
        tm = _fmt_time(x.get("attachedPubDate") or x.get("updateDate"))
        if stop_date and tm and tm[:10] < stop_date:
            return items, True
        code = str(x.get("stockCode") or "")
        name = str(x.get("companyShortName") or "")
        if not (len(code) == 6 and code.isdigit()):
            continue
        if not keep_all and not SIGNAL_KW.search(reply + ask):
            continue
        items.append({
            "title": f"互动易：{name}董秘回复：{reply[:40]}",
            "body": f"互动易问答（{name}（{code}））\n问：{ask[:200]}\n答：{reply[:400]}",
            "time": tm,
            "source": SOURCE,
            "url": f"https://irm.cninfo.com.cn/ircs/company/{code}",
            "stocks": [code],
        })
    return items, False


def _fetch_pages(stop_date, max_pages, page_size=30, keep_all=False):
    items = []
    for page in range(1, max_pages + 1):
        try:
            data = _post_page(page, page_size)
        except Exception as e:
            print(f"[warn] 互动易第{page}页失败: {e}", file=sys.stderr)
            break
        page_items, stop = _parse_rows(data.get("results"), stop_date, keep_all)
        if page_items or stop:
            items.extend(page_items)
        if stop:
            break
        time.sleep(0.3)  # 礼貌限速
    return items


def fetch(cfg: dict) -> list:
    """采集器插件统一入口。keep_all 调试用（不过滤关键词）。

    注意：互动易回复有延迟（问→答隔数小时到数天），且周末积压，
    时间边界必须回看 lookback_days（默认3天），不能只看当天。
    """
    import datetime as _dt
    stop_date = cfg.get("_stop_date") or _dt.date.today().strftime("%Y-%m-%d")
    lookback = int(cfg.get("lookback_days", 3))
    boundary = (_dt.datetime.strptime(stop_date, "%Y-%m-%d").date()
                - _dt.timedelta(days=lookback)).strftime("%Y-%m-%d")
    max_pages = int(cfg.get("max_pages", 10))
    keep_all = bool(cfg.get("keep_all", False))
    return _fetch_pages(boundary, max_pages, keep_all=keep_all)


def selftest() -> bool:
    tm_re = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
    try:
        items = _fetch_pages(stop_date=None, max_pages=1, keep_all=True)
    except Exception as e:
        print(f"[warn] selftest 网络失败: {e}", file=sys.stderr)
        return False
    if not items:
        print("[warn] selftest 未取到数据", file=sys.stderr)
        return False
    for it in items[:5]:
        if set(it) != {"title", "body", "time", "source", "url", "stocks"}:
            return False
        if not tm_re.match(it["time"]) or it["source"] != SOURCE:
            return False
        if not all(len(c) == 6 and c.isdigit() for c in it["stocks"]):
            return False
    return True


if __name__ == "__main__":
    print(selftest())
