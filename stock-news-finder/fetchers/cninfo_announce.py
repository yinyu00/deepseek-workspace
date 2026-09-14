#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""巨潮资讯网公告采集器插件（type: cninfo-announce）。

信息价值：公告是一手信息（新闻是二手转述），订单/并购/回购/业绩预告
官方公告常领先媒体报道。stocks 字段带官方标注代码，走 match_score
官方通道（权重 1.2）。

双通道：
  A) watchlist 通道：data/watchlist.json 自选股近 N 天全部公告
  B) 全市场类别通道：高价值类别 + 标题关键词过滤（防 800+ 条/类刷屏）

要点（踩坑记录，2026-09-14 实测）：
- 巨潮 WAF：必须带 Referer + 常规浏览器 UA，否则 403
- seDate 必须紧凑格式 2026-09-12~2026-09-14（带空格的 "2026-09-01 ~ ..." 返回 0）
- stock 参数必须 "代码,orgId"（只传代码返回 0），orgId 用 topSearch 现查不落盘
- announcementTime 是毫秒时间戳，转本地时区
- PDF 直链 = http://static.cninfo.com.cn/{adjunctUrl}
- 全市场一天约 2000+ 条，必须类别+关键词双重过滤
"""
import datetime as _dt
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WATCHLIST = os.path.join(BASE, "data", "watchlist.json")

QUERY_API = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
ORG_API = "http://www.cninfo.com.cn/new/information/topSearch/query"
PDF_BASE = "http://static.cninfo.com.cn/"
SOURCE = "cninfo-announce"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "http://www.cninfo.com.cn/new/commonUrl?url=disclosure/list/notice",
    "X-Requested-With": "XMLHttpRequest",
}

# 高价值类别（事件驱动核心）：业绩预告 / 利润分配 / 股权激励 / 增发
DEFAULT_CATEGORIES = [
    "category_yjygjxz_szsh",   # 业绩预告
    "category_qyfpxzcs_szsh",  # 权益分派
    "category_gqjl_szsh",      # 股权激励
    "category_zj_szsh",        # 增发
]
# 类别通道的标题关键词（订单/合同没有独立 category，藏在日常经营 800 条里，只能词滤）
DEFAULT_KEYWORDS = re.compile(
    r"(中标|签署.{0,6}合同|重大合同|业绩预(增|亏|减)|预增|预减|回购|增持|减持|"
    r"并购|重组|收购|股权激励|派息|分红|解禁|涨停|风险提示)"
)


def _post_form(api, form, timeout=15):
    """POST 表单 → JSON；SSL 失败（公司 TLS 拦截）自动降级重试一次。"""
    body = urllib.parse.urlencode(form).encode()
    req = urllib.request.Request(api, data=body, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "ignore"))
    except Exception as e:
        if "CERTIFICATE" not in str(e).upper() and "SSL" not in str(e).upper():
            raise
    import ssl
    ctx = ssl._create_unverified_context()
    ctx.set_ciphers("DEFAULT@SECLEVEL=1")
    req = urllib.request.Request(api, data=body, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def _org_id(code):
    """topSearch 查 orgId（stock 参数必需）。查不到返回 None。"""
    try:
        rows = _post_form(ORG_API, {"keyWord": code, "maxNum": "3"})
    except Exception as e:
        print(f"[warn] orgId 查询失败 {code}: {e}", file=sys.stderr)
        return None
    for r in rows or []:
        if str(r.get("code")) == code and not r.get("delisted"):
            return r.get("orgId")
    return None


def _fmt_time(ts_ms):
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(ts_ms) / 1000))
    except (ValueError, TypeError, OSError):
        return ""


def _to_item(a):
    """巨潮公告记录 → 统一新闻 schema。"""
    title = re.sub(r"</?em>", "", str(a.get("announcementTitle") or ""))
    tm = _fmt_time(a.get("announcementTime"))
    url = PDF_BASE + str(a.get("adjunctUrl") or "")
    code = str(a.get("secCode") or "")
    name = str(a.get("secName") or "")
    return {
        "title": title,
        "body": f"巨潮公告：{name}（{code}）{title}",
        "time": tm,
        "source": SOURCE,
        "url": url,
        "stocks": [code] if len(code) == 6 and code.isdigit() else [],
    }


def _query(form_items):
    """单次公告查询，返回 announcements 列表（空列表=无数据）。"""
    form = {
        "pageNum": "1", "pageSize": "30", "column": "szse", "tabName": "fulltext",
        "plate": "", "stock": "", "searchkey": "", "secid": "", "category": "",
        "tradeDate": "", "sortName": "", "sortType": "", "isHLtitle": "false",
    }
    form.update(form_items)
    data = _post_form(QUERY_API, form)
    return data.get("announcements") or []


def _sedate(end_date, lookback_days):
    end = _dt.datetime.strptime(end_date, "%Y-%m-%d").date()
    start = end - _dt.timedelta(days=lookback_days)
    return f"{start}~{end}"


def fetch(cfg: dict) -> list:
    """采集器插件统一入口。"""
    stop_date = cfg.get("_stop_date") or _dt.date.today().strftime("%Y-%m-%d")
    lookback = int(cfg.get("lookback_days", 3))
    sedate = _sedate(stop_date, lookback)
    items, seen = [], set()

    # ---- 通道 A：watchlist 自选股全量公告 ----
    stocks = []
    if cfg.get("watchlist", True) and os.path.exists(WATCHLIST):
        try:
            stocks = json.load(open(WATCHLIST, encoding="utf-8")).get("stocks") or []
        except Exception as e:
            print(f"[warn] watchlist 读取失败: {e}", file=sys.stderr)
    wl_cnt = 0
    for s in stocks[:30]:
        code = str(s.get("code") or "")
        if not (len(code) == 6 and code.isdigit()):
            continue
        org = _org_id(code)
        if not org:
            continue
        try:
            rows = _query({"stock": f"{code},{org}", "seDate": sedate})
        except Exception as e:
            print(f"[warn] watchlist 公告失败 {code}: {e}", file=sys.stderr)
            continue
        for a in rows:
            aid = a.get("announcementId")
            if aid in seen:
                continue
            seen.add(aid)
            items.append(_to_item(a))
            wl_cnt += 1
        time.sleep(0.3)  # 礼貌限速（orgId 查询 + 公告查询都打巨潮）
    if stocks:
        print(f"  [cninfo] watchlist {len(stocks)} 只 → {wl_cnt} 条公告")

    # ---- 通道 B：全市场高价值类别 + 标题关键词过滤 ----
    categories = cfg.get("categories", DEFAULT_CATEGORIES)
    kw = DEFAULT_KEYWORDS
    if cfg.get("keywords"):
        kw = re.compile("|".join(cfg["keywords"]))
    cat_cnt = 0
    for cat in categories:
        try:
            rows = _query({"category": cat, "seDate": sedate, "pageSize": "50"})
        except Exception as e:
            print(f"[warn] 类别公告失败 {cat}: {e}", file=sys.stderr)
            continue
        for a in rows:
            if not kw.search(str(a.get("announcementTitle") or "")):
                continue
            aid = a.get("announcementId")
            if aid in seen:
                continue
            seen.add(aid)
            items.append(_to_item(a))
            cat_cnt += 1
        time.sleep(0.3)
    print(f"  [cninfo] 类别通道 {len(categories)} 类 → {cat_cnt} 条（关键词过滤后）")
    return items


def selftest() -> bool:
    """真实调用接口抓 1 类 1 页，校验字段格式（业绩预告非财报季可能为空，带兜底）。"""
    rows = []
    for cat in ("category_qyfpxzcs_szsh", "category_rcjy_szsh"):
        try:
            rows = _query({"category": cat,
                           "seDate": _sedate(_dt.date.today().strftime("%Y-%m-%d"), 14),
                           "pageSize": "10"})
        except Exception as e:
            print(f"[warn] selftest 网络失败: {e}", file=sys.stderr)
            return False
        if rows:
            break
    if not rows:
        print("[warn] selftest 未取到数据", file=sys.stderr)
        return False
    tm_re = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
    for a in rows[:5]:
        it = _to_item(a)
        if set(it) != {"title", "body", "time", "source", "url", "stocks"}:
            return False
        if not tm_re.match(it["time"]):
            return False
        if it["source"] != SOURCE or not it["url"].startswith(PDF_BASE):
            return False
        if not isinstance(it["stocks"], list):
            return False
    return True


if __name__ == "__main__":
    print(selftest())
