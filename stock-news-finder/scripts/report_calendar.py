#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""财报日历:自选池定期报告预约/实际披露时间监控 + 微信推送。

数据源:东方财富数据中心 RPT_PUBLIC_BS_APPOIN(全市场定期报告预约披露时间表)。
调用预算:每报告期每批 1 次,自选池<=30只、3个报告期 = 每天最多 3 次;
结果缓存于 data/report_calendar_cache.json(按天),同日重复执行零调用。

用法:
    python3 scripts/report_calendar.py --key SCTxxxx --push        # 有事件才推
    python3 scripts/report_calendar.py --key SCTxxxx --push --force  # 无事件也推总览
    python3 scripts/report_calendar.py                             # 只生成不推

事件定义:
    今日实际披露 / 明日预约披露 / 未来7天预约披露 / 顺延关注(预约已过未见实际)
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from push_channels import push, load_config
except ImportError:
    push = None  # main 里推送时再报错

try:  # Windows 控制台 GBK 兜底
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WATCHLIST = os.path.join(BASE, "data", "watchlist.json")
CACHE = os.path.join(BASE, "data", "report_calendar_cache.json")
OUT_DIR = os.path.join(BASE, "output")
API = ("https://datacenter-web.eastmoney.com/api/data/v1/get"
       "?reportName=RPT_PUBLIC_BS_APPOIN&columns=ALL&pageSize=500&filter=")
PERIOD_NAMES = {"03-31": "一季报", "06-30": "半年报", "09-30": "三季报", "12-31": "年报"}
BATCH = 30  # in 列表分批,防 URL 过长


def http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def recent_periods(today, n_past=1, n_future=2):
    """最近 n_past 个已完成报告期 + 未来 n_future 个报告期。"""
    ends = []
    for y in (today.year - 1, today.year, today.year + 1):
        for m, d in ((3, 31), (6, 30), (9, 30), (12, 31)):
            ends.append(datetime(y, m, d))
    past = [x for x in ends if x <= today][-n_past:]
    future = [x for x in ends if x > today][:n_future]
    return [x.strftime("%Y-%m-%d") for x in past + future]


def fetch(stocks, periods):
    """按(报告期 × 批)调用接口,返回行列表。"""
    rows = []
    codes = [s["code"] for s in stocks]
    for period in periods:
        for i in range(0, len(codes), BATCH):
            batch = codes[i:i + BATCH]
            quoted = ",".join('"%s"' % c for c in batch)
            filt = "(REPORT_DATE='%s')(SECURITY_CODE in (%s))" % (period, quoted)
            url = API + urllib.parse.quote(filt, safe="")
            print("[call] %s 批%d(%d只)" % (period, i // BATCH + 1, len(batch)))
            try:
                data = http_json(url).get("result") or {}
                rows.extend(data.get("data") or [])
            except Exception as e:
                print("[warn] 调用失败(%s %s): %s" % (period, batch, e))
    return rows


def load_cache(today_str):
    if os.path.exists(CACHE):
        try:
            c = json.load(open(CACHE, encoding="utf-8"))
            if c.get("date") == today_str:
                print("[cache] 命中今日缓存,零接口调用")
                return c.get("rows") or []
        except Exception:
            pass
    return None


def build_report(rows, stocks, today):
    """生成 markdown 报告,返回 (markdown, 事件数)。"""
    by_code = {s["code"]: s["name"] for s in stocks}
    tmr = today + timedelta(days=1)
    week = today + timedelta(days=7)
    d = lambda x: str(x)[:10]

    def period_name(rd):
        return rd[:4] + PERIOD_NAMES.get(rd[5:10], rd[5:10])

    today_out, tmr_out, week_out, delay_out, all_rows = [], [], [], [], []
    for r in rows:
        code = r.get("SECURITY_CODE", "")
        name = r.get("SECURITY_NAME_ABBR") or by_code.get(code, "")
        rd = d(r.get("REPORT_DATE") or "")
        ap, ac = r.get("APPOINT_PUBLISH_DATE"), r.get("ACTUAL_PUBLISH_DATE")
        line = (code, name, period_name(rd), d(ap) if ap else "未定", d(ac) if ac else "—")
        all_rows.append(line)
        if ac and d(ac) == today.strftime("%Y-%m-%d"):
            today_out.append(line)
        elif not ac and ap and d(ap) == tmr.strftime("%Y-%m-%d"):
            tmr_out.append(line)
        elif not ac and ap and today < datetime.strptime(d(ap), "%Y-%m-%d") <= week:
            week_out.append(line)
        elif not ac and ap and d(ap) < today.strftime("%Y-%m-%d"):
            delay_out.append(line)

    def table(lines):
        if not lines:
            return "无\n"
        return "\n".join("| %s %s | %s | 预约 %s | 实际 %s |" % l for l in lines) + "\n"

    md = ["## 财报日历 %s(%s)\n" % (today.strftime("%m-%d"), "周" + "一二三四五六日"[today.weekday()]),
          "### 已披露·今日\n" + table(today_out),
          "### 即将披露·明日\n" + table(tmr_out),
          "### 即将披露·未来7天\n" + table(week_out)]
    if delay_out:
        md.append("### ⚠️ 顺延关注(预约已过、未见实际)\n" + table(delay_out))
    md.append("### 自选池定期报告总览\n" + table(sorted(all_rows)))
    md.append("\n(自选池 %d 只 × 最近3期;数据源:东财预约披露时间表)"
              % len(by_code))
    events = len(today_out) + len(tmr_out) + len(week_out) + len(delay_out)
    return "\n".join(md), events


def push_wechat(key, title, content):
    """已废弃,保留签名兼容;实际走 push_channels(见 main)。"""
    raise NotImplementedError("use push_channels.push")


def main():
    args = sys.argv[1:]
    key = args[args.index("--key") + 1] if "--key" in args else os.environ.get("SERVERCHAN_SENDKEY")
    do_push, force = "--push" in args, "--force" in args

    stocks = (json.load(open(WATCHLIST, encoding="utf-8")) or {}).get("stocks") or []
    if not stocks:
        print("[err] data/watchlist.json 无股票")
        sys.exit(1)

    today = datetime.now()
    today_str = today.strftime("%Y-%m-%d")
    rows = load_cache(today_str)
    if rows is None:
        periods = recent_periods(today)
        rows = fetch(stocks, periods)
        json.dump({"date": today_str, "rows": rows},
                  open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)

    md, events = build_report(rows, stocks, today)
    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "report_calendar_%s.md" % today.strftime("%Y%m%d"))
    open(out, "w", encoding="utf-8").write(md)
    print("[ok] 报告已生成:", out, "| 事件数:", events)

    if do_push:
        if events == 0 and not force:
            print("[skip] 无事件,未推送(--force 可强推)")
        elif push is None:
            print("[err] push_channels 模块不可用")
            sys.exit(1)
        else:
            cfg = load_config(
                serverchan=key,
                wecom=(args[args.index("--wecom") + 1] if "--wecom" in args else None))
            ok = push("财报日历 %s(事件%d)" % (today.strftime("%m-%d"), events), md, cfg)
            sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
