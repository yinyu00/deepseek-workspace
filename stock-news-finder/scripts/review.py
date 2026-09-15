#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证层：次日回看昨日推荐的实际涨跌，统计各档命中率沉淀到 stats.json。

- 行情源：东财 push2 批量行情接口（curl 子进程 + 多节点重试，勿改 urllib 直连）
- 命中口径：★★★/★★ 档按「次日收盘涨幅 > 0」计命中；另记录平均涨幅
- 累计统计写 output/review_stats.json，用于后续调推荐阈值

用法：
  python3 review.py                # 回看最近一份 recommend_*.json
  python3 review.py 20260913       # 指定日期
"""
import glob
import json
import os
import re
import subprocess
import sys
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE, "output")
DAILY_DIR = os.path.join(BASE, "daily")
STATS = os.path.join(OUT_DIR, "review_stats.json")

NODES = ["https://push2.eastmoney.com",
         "http://push2.eastmoney.com",
         "http://push2delay.eastmoney.com"]


def secid(code):
    """6位代码 → 东财 secid（沪 1.x / 深 0.x / 北 0.x 兜底）。"""
    if code.startswith(("6", "9", "5")):
        return f"1.{code}"
    return f"0.{code}"


def fetch_quotes(codes):
    """批量拉实时行情：code → {name, price, pct}。失败返回 {}。"""
    if not codes:
        return {}
    secids = ",".join(secid(c) for c in codes)
    for base in NODES:
        url = (f"{base}/api/qt/ulist.np/get?fltt=2&fields=f2,f3,f12,f14&secids={secids}")
        for use_proxy in (True, False):
            cmd = ["curl", "-s", "-m", "15"]
            if use_proxy:
                cmd += ["--proxy", os.environ.get("ALL_PROXY", "http://127.0.0.1:7890")]
            cmd.append(url)
            try:
                out = subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout
                data = json.loads(out)
                quotes = {}
                for d in data.get("data", {}).get("diff", []):
                    pct = d.get("f3")
                    quotes[str(d.get("f12"))] = {
                        "name": d.get("f14"), "price": d.get("f2"),
                        "pct": pct if isinstance(pct, (int, float)) else None,
                    }
                if quotes:
                    return quotes
            except Exception:
                continue
    return {}


def load_recommend(date=None):
    files = sorted(glob.glob(os.path.join(OUT_DIR, "recommend_*.json")))
    if not files:
        sys.exit("[error] 无 recommend_*.json，请先运行 recommend.py")
    if date:
        files = [os.path.join(OUT_DIR, f"recommend_{date.replace('-', '')}.json")]
        if not os.path.exists(files[0]):
            sys.exit(f"[error] 不存在 {files[0]}")
    with open(files[-1], encoding="utf-8") as f:
        return json.load(f), files[-1]


def main():
    date = sys.argv[1] if len(sys.argv) > 1 else None
    rec, rec_path = load_recommend(date)
    date8 = rec["date"]
    recs = rec.get("recommended", [])
    if not recs:
        sys.exit("[skip] 推荐列表为空")

    codes = [r["code"] for r in recs]
    quotes = fetch_quotes(codes)
    if not quotes:
        sys.exit("[warn] 行情拉取失败（网络），验证中止；可稍后重跑")

    rows, tier_stat = [], {}
    for r in recs:
        q = quotes.get(r["code"])
        if not q or q["pct"] is None:
            continue
        # 停牌股接口返回 price=0 占位数据，计入统计会失真（0.00%≠平盘）
        if not q["price"]:
            rows.append(dict(r, pct=None, price=0, hit=None))  # 展示但不进统计
            continue
        hit = q["pct"] > 0
        t = tier_stat.setdefault(r["tier"], {"n": 0, "hit": 0, "pct_sum": 0.0})
        t["n"] += 1
        t["hit"] += 1 if hit else 0
        t["pct_sum"] += q["pct"]
        rows.append(dict(r, pct=q["pct"], price=q["price"], hit=hit))
    rows.sort(key=lambda x: -(x["pct"] if x["pct"] is not None else -99))

    # ---- 累计统计 ----
    stats = {"days": 0, "tier": {}}
    if os.path.exists(STATS):
        try:
            stats = json.load(open(STATS, encoding="utf-8"))
        except Exception:
            pass
    hist = stats.setdefault("history", {})
    day_stat = {tier: {"n": v["n"], "hit": v["hit"], "avg_pct": round(v["pct_sum"] / v["n"], 2)}
                for tier, v in tier_stat.items() if v["n"]}
    hist[date8] = day_stat
    agg = stats.setdefault("tier", {})
    for tier, v in day_stat.items():
        a = agg.setdefault(tier, {"n": 0, "hit": 0, "pct_sum": 0.0})
        a["n"] += v["n"]; a["hit"] += v["hit"]; a["pct_sum"] += v["avg_pct"] * v["n"]
    stats["days"] = len(hist)
    with open(STATS, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=1)

    # ---- Markdown ----
    now = datetime.now()
    L = [f"# 推荐复盘 {date8}（行情截至 {now:%Y-%m-%d %H:%M}）", "",
         "| 档 | 名称 | 代码 | 推荐分 | 最新涨跌 | 结果 |", "|---|---|---|---:|---:|---|"]
    for r in rows:
        pct_s = f"{r['pct']:+.2f}%" if r["pct"] is not None else "停牌"
        res = ("✅" if r["hit"] else "❌") if r["hit"] is not None else "暂停"
        L.append(f"| {'★' * r['stars']} | {r['name']} | {r['code']} | {r['r_score']:.1f} | "
                 f"{pct_s} | {res} |")
    L += ["", "## 分档统计（当日 / 累计）", "",
          "| 档 | 当日命中 | 当日均涨 | 累计命中 | 累计均涨 |", "|---|---|---:|---|---:|"]
    for tier in ("强推", "关注", "观察"):
        d = day_stat.get(tier)
        a = agg.get(tier, {"n": 0, "hit": 0, "pct_sum": 0})
        cur = f"{d['hit']}/{d['n']}" if d else "-"
        avg = f"{d['avg_pct']:+.2f}%" if d else "-"
        cum = f"{a['hit']}/{a['n']}" if a["n"] else "-"
        cavg = f"{a['pct_sum'] / a['n']:+.2f}%" if a["n"] else "-"
        L.append(f"| {tier} | {cur} | {avg} | {cum} | {cavg} |")

    md_path = os.path.join(DAILY_DIR, f"review_{date8}.md")
    os.makedirs(DAILY_DIR, exist_ok=True)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print(f"→ {md_path}")
    print(f"→ {STATS}（累计 {stats['days']} 个交易日）")
    for r in rows[:8]:
        pct_s = f"{r['pct']:+6.2f}%" if r["pct"] is not None else "  停牌 "
        print(f"{'★' * r['stars']} {pct_s}  {r['code']} {r['name']}")


if __name__ == "__main__":
    main()
