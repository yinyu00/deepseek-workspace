#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""东财龙虎榜席位明细采集器插件（type: lhb-seats）——游资/机构席位维度。

信息价值：RPT_DAILYBILLBOARD_DETAILSNEW（longhubang.py）只有榜单总量；
本插件下钻 RPT_OPERATEDEPT_TRADE 拿到买卖前五席位名称与金额——
顶级游资席位（武汉紫阳东路/西安西大街等）现身是比榜单净额更硬的信号。

接口：datacenter-web.eastmoney.com RPT_OPERATEDEPT_TRADE（2026-09-18 实测）：
- filter=(SECURITY_CODE="code")，sortColumns=TRADE_DATE,RANK
- 金额字段必须用 BUY_AMT_REAL / SELL_AMT_REAL（BUY_AMT 是占比，坑）
- TRADE_DIRECTION：'0'=买方席位榜，'1'=卖方席位榜；RANK 为榜内名次
- 深股通/机构专用会同时出现在买卖两侧（对倒），按 side 分别取
- watchlist 之外的股票默认不拉（requests 量 = 股票数 × 1 次，可控）

sources.json 配置示例：
  {"name": "龙虎榜席位", "type": "lhb-seats", "enabled": true,
   "lookback_days": 3, "min_net_amt": 30000000}
  可选 "codes": ["000981"] 覆盖 watchlist。
"""
import datetime as _dt
import json
import os
import ssl
import sys
import urllib.parse
import urllib.request

SOURCE = "lhb-seats"
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # stock-news-finder/
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
           "Referer": "https://data.eastmoney.com/"}

FAMOUS = ("紫阳东路", "西安西大街", "拉萨", "漕溪北路", "深股通", "机构专用",
          "宁波桑田路", "量化", "杭州上塘路")


def _get_json(url, timeout=15):
    """datacenter-web 直连；公司 TLS 拦截时降级 unverified 重试（Windows 姿势）。"""
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "ignore"))
    except ssl.SSLError:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return json.loads(r.read().decode("utf-8", "ignore"))


def _yi(v):
    try:
        return float(v) / 1e8
    except (ValueError, TypeError):
        return 0.0


def _fetch_seats(code):
    q = urllib.parse.quote(f'(SECURITY_CODE="{code}")')
    url = ("https://datacenter-web.eastmoney.com/api/data/v1/get"
           f"?reportName=RPT_OPERATEDEPT_TRADE&columns=ALL&filter={q}"
           "&sortColumns=TRADE_DATE,RANK&sortTypes=-1,1&pageSize=100&pageNumber=1&source=WEB")
    return _get_json(url).get("result", {}).get("data") or []


def fetch(cfg: dict) -> list:
    """统一入口。每只股票每个上榜交易日一条，标题聚焦席位亮点（供正则/LLM 分级）。"""
    lookback = int(cfg.get("lookback_days", 3))
    min_net = float(cfg.get("min_net_amt", 3e7))
    codes = cfg.get("codes")
    if not codes:
        try:
            with open(os.path.join(HERE, "data", "watchlist.json"), encoding="utf-8") as f:
                codes = [s["code"] for s in json.load(f).get("stocks", [])]
        except Exception:
            codes = []
    cutoff = (_dt.date.today() - _dt.timedelta(days=lookback)).strftime("%Y-%m-%d")

    out = []
    for code in codes:
        try:
            rows = _fetch_seats(code)
        except Exception as e:
            print(f"[warn] lhb-seats {code} 拉取失败: {e}", file=sys.stderr)
            continue
        by_day = {}
        for r in rows:
            day = (r.get("TRADE_DATE") or "")[:10]
            if day < cutoff:
                continue
            by_day.setdefault(day, []).append(r)
        for day, seats in sorted(by_day.items()):
            buys = [s for s in seats if s.get("TRADE_DIRECTION") == "0"][:5]
            sells = [s for s in seats if s.get("TRADE_DIRECTION") == "1"][:5]
            top_buy = max(buys, key=lambda s: _yi(s.get("BUY_AMT_REAL")), default=None)
            if not top_buy:
                continue
            top_net = _yi(top_buy.get("BUY_AMT_REAL")) - _yi(top_buy.get("SELL_AMT_REAL"))
            if top_net * 1e8 < min_net:
                continue
            name = top_buy.get("OPERATEDEPT_NAME", "?")
            tag = next((k for k in FAMOUS if k in name), "")
            title = (f"龙虎榜席位 {code}: {name[:18]} 净买{top_net:.2f}亿"
                     + (f" [{tag}]" if tag else ""))
            body_lines = [f"{day} 龙虎榜席位明细（前五）",
                          "买方: " + " / ".join(
                              f"{s['OPERATEDEPT_NAME'][:16]} 净{_yi(s.get('BUY_AMT_REAL')) - _yi(s.get('SELL_AMT_REAL')):.2f}亿"
                              for s in buys),
                          "卖方: " + " / ".join(
                              f"{s['OPERATEDEPT_NAME'][:16]} 净{_yi(s.get('BUY_AMT_REAL')) - _yi(s.get('SELL_AMT_REAL')):.2f}亿"
                              for s in sells)]
            out.append({"title": title, "body": "\n".join(body_lines),
                        "time": f"{day} 18:00:00", "source": SOURCE,
                        "url": f"https://data.eastmoney.com/stock/lhb,{day},{code}.html",
                        "stocks": [code]})
    return out


def selftest() -> bool:
    rows = fetch({"codes": ["000981"], "lookback_days": 10, "min_net_amt": 1e7})
    assert rows, "000981 近10日应有席位数据"
    r = rows[0]
    assert r["source"] == SOURCE and len(r["stocks"][0]) == 6 and r["time"][10] == " "
    print("selftest ok:", r["title"])
    return True


if __name__ == "__main__":
    selftest()
