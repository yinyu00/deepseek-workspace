#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""推荐层：在 signals_*.json 之上做信号提纯 + 分级推荐。

与 match_score.py（信号漏斗）的分工：
  - 信号层回答「今天哪些股票有新闻热度」→ 全量排名，允许噪声
  - 推荐层回答「今天真正值得研究哪几只」→ 提纯、分级、给理由

提纯与分级规则：
  1. 信号提纯：仅靠「产品传导」（板块联动蹭热点）命中的股票不进推荐，
     单独列为板块联动观察池——这是旧日报 TOP30 同分刷屏的噪声主源。
  2. 事件分级：强事件（订单/政策/业绩/并购/回购/产品进展）与弱事件
     （一般资讯/机构评级）区别对待，弱事件只作热度不作推荐依据。
  3. 交叉验证：≥2 个独立新闻源的正面信号加成（单一来源易是软文）。
  4. 连续性加成：近 3 个信号文件中反复出现 → 热度持续标记（资金关注度）。
  5. 三档输出：★★★ 强推 / ★★ 关注 / ★ 观察；负面主导进「回避区」。

输入：output/signals_yyyymmdd.json（match_score 顺产）
输出：output/recommend_yyyymmdd.json + daily/recommend_yyyymmdd.md
"""
import glob
import json
import os
import re
import sys
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE, "output")
DAILY_DIR = os.path.join(BASE, "daily")

# 强事件（可作推荐依据）；命中词与 LLM 事件名都对齐 match_score 的展示名
STRONG_EVENTS = {"订单/合同", "政策利好", "业绩超预期", "并购重组", "回购增持", "产品进展", "资金异动", "机构调研"}
NEG_EVENTS = {"负面"}
CONTINUITY_DAYS = 3      # 连续性回看窗口（个信号文件）
TOP_N = 15               # 报告明细条数


def load_signals(date=None):
    """读指定日期 signals；缺省取 output/ 里最新一份。"""
    files = sorted(glob.glob(os.path.join(OUT_DIR, "signals_*.json")))
    if not files:
        sys.exit("[error] 无 signals_*.json，请先运行 match_score.py")
    if date:
        target = os.path.join(OUT_DIR, f"signals_{date}.json")
        if not os.path.exists(target):
            sys.exit(f"[error] 不存在 {target}")
        files = [target]
    path = files[-1]
    with open(path, encoding="utf-8") as f:
        return json.load(f), path


def continuity_map(today_file):
    """近 N 个历史 signals 文件中各股票出现次数（不含当日）。"""
    files = sorted(glob.glob(os.path.join(OUT_DIR, "signals_*.json")))
    hist = [f for f in files if f != today_file][-CONTINUITY_DAYS:]
    cnt = {}
    for fp in hist:
        try:
            with open(fp, encoding="utf-8") as f:
                for row in json.load(f):
                    cnt[row["code"]] = cnt.get(row["code"], 0) + 1
        except Exception:
            continue
    return cnt, len(hist)


def purify(rec):
    """拆分直连信号与产品传导信号。返回 (direct_hits, via_only)."""
    hits = rec.get("hits", [])
    direct = [h for h in hits if not (h.get("channel") or "").startswith("产品传导")]
    via = [h for h in hits if (h.get("channel") or "").startswith("产品传导")]
    return direct, via


def main():
    date = None
    if len(sys.argv) > 1:
        date = sys.argv[1].replace("-", "")
    signals, sig_path = load_signals(date)
    date8 = re.search(r"(\d{8})", os.path.basename(sig_path)).group(1)
    cont, cont_files = continuity_map(sig_path)

    recommended, watchlist_sector, avoid = [], [], []
    for rec in signals:
        direct, via = purify(rec)
        strong_pos = [h for h in direct
                      if any(e in h["event"] for e in STRONG_EVENTS) and h.get("score", 0) > 0]
        weak_pos = [h for h in direct if h not in strong_pos and h.get("score", 0) > 0]
        neg = [h for h in direct if h.get("score", 0) < 0 or any(e in h["event"] for e in NEG_EVENTS)]
        sources = {h.get("source") for h in strong_pos + weak_pos}

        # 1) 仅产品传导命中 → 板块联动池，不推荐
        if not direct:
            words = sorted({(h.get("channel") or "").split(":", 1)[-1] for h in via})
            rec2 = dict(rec, via_words=words, via_cnt=len(via))
            watchlist_sector.append(rec2)
            continue

        # 2) 负面主导 → 回避区
        if neg and (not strong_pos or len(neg) >= max(1, len(strong_pos))):
            avoid.append(dict(rec, neg_cnt=len(neg)))
            continue

        # 3) 连续性
        days = cont.get(rec["code"], 0)
        cont_tag = f"{days}/{cont_files}日持续" if cont_files and days >= 1 else ""

        # 4) 分级
        cross = len(sources) >= 2
        if len(strong_pos) >= 2 and (cross or len(strong_pos) >= 3):
            stars, tier = 3, "强推"
        elif strong_pos:
            stars, tier = 2, "关注"
        else:
            stars, tier = 1, "观察"

        # 推荐分：强事件为主，弱事件/交叉/连续性加成
        r_score = (sum(h["score"] for h in strong_pos) * 1.0
                   + sum(h["score"] for h in weak_pos) * 0.3
                   + (1.5 if cross else 0)
                   + days * 0.8)
        reasons = []
        if strong_pos:
            evs = "、".join(sorted({h["event"] for h in strong_pos})[:3])
            reasons.append(f"强事件[{evs}]×{len(strong_pos)}")
        if cross:
            reasons.append(f"{len(sources)}源交叉验证")
        if cont_tag:
            reasons.append(cont_tag)
        if neg:
            reasons.append(f"⚠{len(neg)}条负面")
        recommended.append(dict(
            rec, stars=stars, tier=tier, r_score=round(r_score, 2),
            reasons=reasons, direct_cnt=len(direct), cont_days=days,
        ))

    recommended.sort(key=lambda r: (-r["stars"], -r["r_score"]))
    watchlist_sector.sort(key=lambda r: -r["via_cnt"])

    now = datetime.now()
    out_json = os.path.join(OUT_DIR, f"recommend_{date8}.json")
    slim = [{k: r[k] for k in ("code", "name", "stars", "tier", "r_score",
                               "reasons", "score", "pos", "neg", "events")}
            for r in recommended[:TOP_N]]
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump({"date": date8, "generated_at": now.strftime("%Y-%m-%d %H:%M"),
                   "recommended": slim}, f, ensure_ascii=False, indent=1)

    # ---- Markdown 日报 ----
    L = [
        f"# 股票推荐日报 {date8}",
        "",
        f"> 生成 {now:%Y-%m-%d %H:%M} | 信号 {len(signals)} 只 → 推荐 {len(recommended)} 只"
        f"（强推 {sum(1 for r in recommended if r['stars']==3)} / "
        f"关注 {sum(1 for r in recommended if r['stars']==2)} / "
        f"观察 {sum(1 for r in recommended if r['stars']==1)}）"
        f" | 板块联动 {len(watchlist_sector)} 只（不入推荐）",
        "> 定位：研究漏斗的最后一层，非交易指令。",
        "",
        "## 推荐列表",
        "",
        "| 档 | 名称 | 代码 | 推荐分 | 信号分 | 理由 |",
        "|---|---|---|---:|---:|---|",
    ]
    for r in recommended[:TOP_N]:
        L.append(f"| {'★' * r['stars']} {r['tier']} | {r['name']} | {r['code']} | "
                 f"{r['r_score']:.1f} | {r.get('score', 0):.1f} | {'；'.join(r['reasons'])} |")
    L += ["", "### 各股依据（TOP10 明细）", ""]
    for r in recommended[:10]:
        L.append(f"**{r['name']}（{r['code']}）** {'★' * r['stars']} {r['tier']}，推荐分 {r['r_score']:.1f}")
        for h in sorted(r["hits"], key=lambda h: -h.get("score", 0))[:4]:
            if (h.get("channel") or "").startswith("产品传导"):
                continue
            reason = f"（{h['reason']}）" if h.get("reason") else ""
            title = f"[{h['title']}]({h['url']})" if h.get("url") else h.get("title", "")
            L.append(f"- `{(h.get('time') or '')[11:16]}` **{h['event']}** {reason} {title}")
        L.append("")

    if watchlist_sector:
        L += ["## 板块联动池（仅产品传导命中，只看板块不做个股）", "",
              "| 名称 | 代码 | 联动新闻数 | 传导词 |", "|---|---|---:|---|"]
        for r in watchlist_sector[:10]:
            L.append(f"| {r['name']} | {r['code']} | {r['via_cnt']} | {'、'.join(r['via_words'][:3])} |")
        L.append("")
    if avoid:
        L += ["## 回避区（负面主导）", "", "| 名称 | 代码 | 负面条数 | 信号分 |", "|---|---|---:|---:|"]
        for r in avoid[:10]:
            L.append(f"| {r['name']} | {r['code']} | {r['neg_cnt']} | {r.get('score', 0):.1f} |")
        L.append("")

    md_path = os.path.join(DAILY_DIR, f"recommend_{date8}.md")
    os.makedirs(DAILY_DIR, exist_ok=True)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")

    print(f"→ {out_json}")
    print(f"→ {md_path}")
    for r in recommended[:10]:
        print(f"{'★' * r['stars']} {r['r_score']:6.1f}  {r['code']} {r['name']}  {'；'.join(r['reasons'])}")


if __name__ == "__main__":
    main()
