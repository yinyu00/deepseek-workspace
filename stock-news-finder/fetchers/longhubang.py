#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""东财龙虎榜采集器插件（type: longhubang）——资金面验证通道。

信息价值：龙虎榜=交易所披露的异动资金数据（一手），机构/游资席位买卖
是新闻热度之外最硬的验证维度。上榜股票带官方代码标注，走权威通道。

接口：datacenter-web.eastmoney.com RPT_DAILYBILLBOARD_DETAILSNEW。
要点（2026-09-14 实测）：
- filter=(TRADE_DATE='YYYY-MM-DD')：从今天起最多回退 5 天找最近交易日
- BILLBOARD_NET_AMT 净买额（正=净买入）；EXPLAIN 含机构参与说明
- D1/D5/D10_CLOSE_ADJCHRATE 是上榜后 1/5/10 日涨幅（回测金矿，暂存 body）
- 每只上榜股票输出一条；time 固定为交易日 18:00（收盘后披露）
- 数据域与 push2 不同，直连稳定，无需 curl 多节点
"""
import datetime as _dt
import sys
import urllib.request

SOURCE = "longhubang"
API = ("https://datacenter-web.eastmoney.com/api/data/v1/get"
       "?reportName=RPT_DAILYBILLBOARD_DETAILSNEW&columns=ALL"
       "&filter=(TRADE_DATE%3D%27{date}%27)"
       "&sortColumns=BILLBOARD_NET_AMT&sortTypes=-1&pageSize=100&pageNumber=1&source=WEB")
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


def _get_json(url, timeout=15):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return __import__("json").loads(r.read().decode("utf-8", "ignore"))


def _yi(v):
    """元 → 亿元字符串。"""
    try:
        return f"{float(v) / 1e8:.2f}亿"
    except (ValueError, TypeError):
        return "?"


def _latest_trade_date(stop_date):
    """从 stop_date 起回退最多 5 天，找第一个有榜单数据的交易日。"""
    d = _dt.datetime.strptime(stop_date, "%Y-%m-%d").date()
    for i in range(6):
        date = (d - _dt.timedelta(days=i)).strftime("%Y-%m-%d")
        try:
            rows = _get_json(API.format(date=date)).get("result", {}).get("data") or []
        except Exception as e:
            print(f"[warn] 龙虎榜查询失败 {date}: {e}", file=sys.stderr)
            continue
        if rows:
            return date, rows
    return None, []


def fetch(cfg: dict) -> list:
    """采集器插件统一入口。每只上榜股票一条，净买方向在标题里（供正则分级）。"""
    import datetime as _dt
    stop_date = cfg.get("_stop_date") or _dt.date.today().strftime("%Y-%m-%d")
    date, rows = _latest_trade_date(stop_date)
    if not date:
        print("[warn] 龙虎榜近 6 天无数据", file=sys.stderr)
        return []
    items = []
    for r in rows:
        code = str(r.get("SECURITY_CODE") or "")
        name = str(r.get("SECURITY_NAME_ABBR") or "")
        if not (len(code) == 6 and code.isdigit()):
            continue
        net = r.get("BILLBOARD_NET_AMT")
        explain = str(r.get("EXPLAIN") or "")
        chg = r.get("CHANGE_RATE")
        direction = "净买入" if (net or 0) > 0 else "净卖出"
        inst = "，机构参与" if "机构" in explain else ""
        chg_s = f"{'涨' if (chg or 0) >= 0 else '跌'}{abs(chg or 0):.1f}%" if chg is not None else ""
        items.append({
            "title": f"龙虎榜：{name} {chg_s} {direction} {_yi(net)}{inst}",
            "body": (f"龙虎榜（{name}（{code}）{date}）：{direction} {_yi(net)}，"
                     f"买入 {_yi(r.get('BILLBOARD_BUY_AMT'))} / 卖出 {_yi(r.get('BILLBOARD_SELL_AMT'))}。"
                     f"{explain}。上榜原因：{r.get('EXPLANATION') or ''}"
                     f"（榜后1日 {(r.get('D1_CLOSE_ADJCHRATE') or 0) * 100:+.1f}%）"),
            "time": f"{date} 18:00:00",
            "source": SOURCE,
            "url": f"https://data.eastmoney.com/stock/lhb,{date},{code}.html",
            "stocks": [code],
        })
    return items


def selftest() -> bool:
    import re
    try:
        items = fetch({"_stop_date": _dt.date.today().strftime("%Y-%m-%d")})
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
        if not it["url"].startswith("https://data.eastmoney.com/stock/lhb,"):
            return False
        if not all(len(c) == 6 and c.isdigit() for c in it["stocks"]):
            return False
    return True


if __name__ == "__main__":
    print(selftest())
