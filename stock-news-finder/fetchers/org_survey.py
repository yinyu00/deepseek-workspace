#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""东财机构调研采集器插件（type: org-survey）。

信息价值：机构调研热度=机构关注先行指标（调研→建仓常有领先关系），
一手披露数据，替代此前只能从新闻转述抓"176家机构调研"的方式。

接口：datacenter-web.eastmoney.com RPT_ORG_SURVEYNEW。
要点（2026-09-14 实测）：
- sortColumns=NOTICE_DATE 倒序拉最新披露，按 stop_date-lookback 边界停
- NUMBERNEW=参与机构数（信号强度）；RECEPTIONIST 含董事长/总经理=高规格
- 一天数百条记录，按 min_orgs 过滤（默认 ≥3 家机构才收）
- RECEPTIONIST/RECEIVE_WAY_EXPLAIN/RECEIVE_PLACE 入 body
"""
import datetime as _dt
import sys
import urllib.request

SOURCE = "org-survey"
API = ("https://datacenter-web.eastmoney.com/api/data/v1/get"
       "?reportName=RPT_ORG_SURVEYNEW&columns=ALL"
       "&sortColumns=NOTICE_DATE&sortTypes=-1&pageSize=100&pageNumber={page}&source=WEB")
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


def _get_json(url, timeout=15):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return __import__("json").loads(r.read().decode("utf-8", "ignore"))


def _parse_rows(rows, stop_boundary, min_orgs):
    """解析一页；返回 (items, reached_before_stop)。同股同日多条披露去重保最大值。"""
    items, best = [], {}  # (code, date) -> n_orgs
    for r in rows or []:
        code = str(r.get("SECURITY_CODE") or "")
        name = str(r.get("SECURITY_NAME_ABBR") or "")
        notice = str(r.get("NOTICE_DATE") or "")  # "2026-09-15 00:00:00"
        if not (len(code) == 6 and code.isdigit()):
            continue
        if stop_boundary and notice[:10] < stop_boundary:
            return items, True
        try:
            n_orgs = int(r.get("NUMBERNEW") or 0)
        except (ValueError, TypeError):
            n_orgs = 0
        key = (code, notice[:10])
        if key in best and best[key] >= n_orgs:
            continue
        best[key] = n_orgs
        if n_orgs < min_orgs:
            continue
        reception = str(r.get("RECEPTIONIST") or "")
        vip = any(k in reception for k in ("董事长", "总经理"))
        title = f"机构调研：{n_orgs}家机构调研{name}" + ("（董事长接待）" if vip else "")
        items.append({
            "title": title,
            "body": (f"机构调研（{name}（{code}）披露 {notice[:10]}）：{n_orgs} 家机构参与，"
                     f"形式：{r.get('RECEIVE_WAY_EXPLAIN') or ''}，地点：{r.get('RECEIVE_PLACE') or ''}。"
                     f"接待：{reception[:60]}"),
            "time": notice if len(notice) >= 19 else notice + " 00:00:00",
            "source": SOURCE,
            "url": f"https://data.eastmoney.com/jgdy/stock/{code}.html",
            "stocks": [code],
        })
    return items, False


def fetch(cfg: dict) -> list:
    """采集器插件统一入口。min_orgs=最低机构数过滤（默认3）。"""
    import datetime as _dt
    stop_date = cfg.get("_stop_date") or _dt.date.today().strftime("%Y-%m-%d")
    lookback = int(cfg.get("lookback_days", 3))
    min_orgs = int(cfg.get("min_orgs", 3))
    max_pages = int(cfg.get("max_pages", 4))
    boundary = (_dt.datetime.strptime(stop_date, "%Y-%m-%d").date()
                - _dt.timedelta(days=lookback)).strftime("%Y-%m-%d")
    items = []
    for page in range(1, max_pages + 1):
        try:
            rows = _get_json(API.format(page=page)).get("result", {}).get("data") or []
        except Exception as e:
            print(f"[warn] 机构调研第{page}页失败: {e}", file=sys.stderr)
            break
        if not rows:
            break
        page_items, stop = _parse_rows(rows, boundary, min_orgs)
        items.extend(page_items)
        if stop:
            break
    return items


def selftest() -> bool:
    import re
    try:
        items = _parse_rows(_get_json(API.format(page=1)).get("result", {}).get("data") or [], None, 0)[0]
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
        if not it["url"].startswith("https://data.eastmoney.com/jgdy/stock/"):
            return False
    return True


if __name__ == "__main__":
    print(selftest())
