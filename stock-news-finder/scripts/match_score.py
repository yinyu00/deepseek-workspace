#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""关联层 + 信号层：新闻匹配股票词典并打分，输出 output/signal_report.md。

信号模型（事件驱动，规则版，后续可替换为 LLM 分类）：
score = 事件权重 × 时效衰减 × 命中强度
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根 = scripts/ 上一级
DICT = os.path.join(BASE, "data", "stock_dict.json")
NEWS = os.path.join(BASE, "output", "raw_news.json")
LLM = os.path.join(BASE, "output", "llm_events.json")
OUT = os.path.join(BASE, "output", "signal_report.md")

# 采集源内部标识 → 展示名（新增源时在 sources.json 的 name 里起好名即可，此处只做兜底映射）
SOURCE_NAMES = {
    "eastmoney-fast": "东方财富",
    "wallstreetcn": "华尔街见闻",
    "eastmoney-search": "东方财富搜索",
}
# LLM 事件类型 → 展示名（打分用 LLM 的 impact，这里只做中文名映射）
LLM_EVENT_NAMES = {
    "earnings_beat": "业绩超预期", "order": "订单/合同", "buyback": "回购增持",
    "ma": "并购重组", "policy": "政策利好", "product": "产品进展",
    "rating": "机构评级", "negative": "负面", "neutral": "一般资讯",
}

# 事件规则：正则 → (权重, 事件名)。后续调参/补充就在这里加。
EVENT_RULES = [
    (r"(业绩预告|预增|净利[润润].{0,6}(增|翻)|超预期|创.{0,4}新高)", 3.0, "业绩超预期"),
    (r"(中标|获得.{0,8}订单|签署.{0,8}(合同|协议)|大单)", 2.5, "订单/合同"),
    (r"(回购|增持)", 2.0, "回购增持"),
    (r"(并购|重组|借壳|收购)", 2.5, "并购重组"),
    (r"(涨停|大涨|飙升|暴涨)", 1.0, "已大涨(谨慎)"),
    (r"(下跌|暴跌|亏损|预减|减持|质押|立案|调查|处罚|退市)", -3.0, "负面"),
]
DECAY_HOURS = 72.0  # 时效半衰期：3 天


def build_matcher():
    with open(DICT, encoding="utf-8") as f:
        entries = json.load(f)
    terms = []  # (term, code, name, weight)
    for e in entries:
        terms.append((e["name"], e["code"], e["name"], 2.0))
        for a in e.get("aliases", []):
            if len(a) >= 2:
                terms.append((a, e["code"], e["name"], 1.0))
    terms.sort(key=lambda t: -len(t[0]))  # 长词优先，避免"中国移动"被"移动"截胡
    return terms


def parse_time(s):
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:len(fmt) + 2], fmt)
        except ValueError:
            pass
    return None


def decay(t):
    if t is None:
        return 0.5
    hours = max((datetime.now() - t).total_seconds() / 3600.0, 0)
    return 0.5 ** (hours / DECAY_HOURS)


def classify(text):
    hits = []
    for pat, w, name in EVENT_RULES:
        if re.search(pat, text):
            hits.append((w, name))
    if not hits:
        hits.append((0.5, "一般资讯"))
    return hits


def main():
    with open(NEWS, encoding="utf-8") as f:
        news = json.load(f)
    terms = build_matcher()

    # LLM 分类结果（可选增强层）：新闻标题 → [{stocks, event, impact, confidence, reason}]
    llm_by_title = {}
    if os.path.exists(LLM):
        try:
            with open(LLM, encoding="utf-8") as f:
                llm_items = json.load(f)
            # llm_classify 输出的 id 对应预筛后顺序，回查标题需按预筛逻辑重建
            terms_pre = []
            for e in json.load(open(DICT, encoding="utf-8")):
                terms_pre.append((e["name"], e["code"]))
                for a in e.get("aliases", []):
                    if len(a) >= 3:
                        terms_pre.append((a, e["code"]))
            pre = [n for n in news if any(t in (n["title"] + " " + n["body"]) for t, _ in terms_pre)]
            for item in llm_items:
                idx = item.get("id")
                if isinstance(idx, int) and 0 <= idx < len(pre):
                    llm_by_title.setdefault(pre[idx]["title"], []).append(item)
            print(f"LLM 增强层: {len(llm_by_title)} 条新闻已分类")
        except Exception as e:
            print(f"[warn] LLM 结果加载失败，回退正则: {e}", file=sys.stderr)

    # 产品传导通道：产品词 → 东财板块 → 成分股（当日缓存，解析失败不影响主流程）
    product_terms = []
    ptxt = os.path.join(BASE, "data", "products.txt")
    if os.path.exists(ptxt):
        with open(ptxt, encoding="utf-8") as f:
            product_terms = [w.strip() for w in f if w.strip() and not w.startswith("#")]
    product_boards = {}  # word -> [(code,name)...] 或 None(解析失败)
    if product_terms:
        # 只解析「当日新闻中真实出现」的词（避免全量词表逐个请求触发限流）
        news_text_all = " ".join(n["title"] + " " + n["body"] for n in news)
        active_words = {w for w in product_terms if w in news_text_all}
        print(f"产品通道: 词表 {len(product_terms)} 词，当日新闻出现 {len(active_words)} 词")
        try:
            import product_lookup
            for w in sorted(active_words):
                try:
                    r = product_lookup.resolve(w)
                    product_boards[w] = r[1] if r else None
                except Exception as e:
                    print(f"[warn] 产品解析失败 {w}: {type(e).__name__}", file=sys.stderr)
                    product_boards[w] = None
            ok = sum(1 for v in product_boards.values() if v)
            print(f"产品通道: {ok}/{len(active_words)} 个活跃词解析成功")
        except ImportError:
            print("[warn] product_lookup 不可用，跳过产品传导")
    dict_codes = {c for _, c, _, _ in terms}

    per_stock = {}  # code -> {...}
    for n in news:
        text = n["title"] + " " + n["body"]
        matched = {}
        for term, code, name, w in terms:
            if term in text:
                if code not in matched or matched[code][1] < w:
                    matched[code] = (term, w)
        # 官方标注通道（东财 stockList）：权威性最高，权重 1.2；已有文本命中不降权
        for code in n.get("stocks") or []:
            code = str(code).strip()
            if len(code) == 6 and code.isdigit() and code in dict_codes:
                w = matched.get(code, (None, 0))[1]
                if w < 1.2:
                    matched[code] = ("官方标注", 1.2)
        # 产品词命中 → 成分股传导（权重 0.6，标注传导来源）
        via_products = {}  # code -> product word
        for w, stocks in product_boards.items():
            if stocks and w in text:
                for code, _ in stocks:
                    if code in dict_codes and code not in matched:
                        matched[code] = (f"产品:{w}", 0.6)
                        via_products[code] = w
        if not matched:
            continue
        t = parse_time(n.get("time"))
        d = decay(t)
        # LLM 增强：以 LLM 的 stocks/event/impact 为准（缺省回退正则）
        llm_items = llm_by_title.get(n["title"]) or []
        if llm_items:
            for item in llm_items:
                for code in item.get("stocks", []) or []:
                    code = str(code).split(":")[0].strip().zfill(6)  # 容错 "600984:建设机械"
                    if len(code) == 6 and code.isdigit():
                        matched.setdefault(code, (None, 1.0))
            events = [(
                item.get("impact", 0),
                LLM_EVENT_NAMES.get(item.get("event", "neutral"), item.get("event", "?")),
                item.get("confidence", 0.5),
                item.get("reason", ""),
            ) for item in llm_items]
        else:
            events = [(ew, ename, 1.0, "") for ew, ename in classify(text)]
        for code, (term, mw) in matched.items():
            for ew, ename, conf, reason in events:
                key = (ename, ew > 0)
                rec = per_stock.setdefault(code, {
                    "code": code, "name": None, "hits": [],
                    "score": 0.0, "pos": 0, "neg": 0,
                })
                if rec["name"] is None:
                    rec["name"] = next((nm for tm, c, nm, _ in terms if c == code), code)
                s = ew * conf * mw * d
                rec["score"] += s
                if term == "官方标注":
                    channel = "官方标注"
                elif code in via_products:
                    channel = "产品传导:" + via_products[code]
                elif term is None:
                    channel = "LLM补充"
                else:
                    channel = "文本匹配"
                tag = f"[经产品传导:{via_products[code]}] " if code in via_products else ""
                rec["hits"].append({
                    "event": tag + ename, "score": round(s, 2), "reason": reason,
                    "title": n["title"][:60], "time": n.get("time", ""), "url": n.get("url", ""),
                    "source": SOURCE_NAMES.get(n.get("source", ""), n.get("source", "未知")),
                    "channel": channel,
                })
                if ew > 0:
                    rec["pos"] += 1
                else:
                    rec["neg"] += 1

    ranked = sorted(per_stock.values(), key=lambda r: -r["score"])
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    lines = [
        "# 股票新闻信号日报",
        f"",
        f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M}",
        f"- 新闻条数：{len(news)}，命中股票数：{len(ranked)}",
        f"- 词典规模：{len(terms)} 个匹配词",
        "",
        "> 定位：研究漏斗（缩小范围），非交易指令。负面多/已大涨的标的慎入。",
        "",
        "| 排名 | 代码 | 名称 | 综合分 | 新闻来源 | 正面 | 负面 | 主要事件 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(ranked[:30], 1):
        top_events = sorted({h["event"] for h in r["hits"]}, key=lambda e: -len(e))[:3]
        srcs = "、".join(sorted({h.get("source", "未知") for h in r["hits"]}))
        lines.append(f"| {i} | {r['code']} | {r['name']} | {r['score']:.1f} | {srcs} | {r['pos']} | {r['neg']} | {'、'.join(top_events)} |")
    lines.append("")
    for r in ranked[:10]:
        lines.append(f"## {r['name']}（{r['code']}）score={r['score']:.1f}")
        for h in sorted(r["hits"], key=lambda h: -h["score"])[:5]:
            reason = f"（{h['reason']}）" if h.get("reason") else ""
            lines.append(f"- [{h['time']}] {h['event']}{reason} | {h['title']}" + (f" | [原文]({h['url']})" if h["url"] else ""))
        lines.append("")
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"→ {OUT}")
    for r in ranked[:10]:
        print(f"{r['score']:7.1f}  {r['code']} {r['name']}")
    write_daily(ranked, len(news), news)


def write_daily(ranked, news_count, news=None):
    """每日归档：daily/yyyymmdd.md（同日多次运行覆盖，最新一次为准）。

    Markdown 格式：概览表 + 每股明细（标题可点击跳原文）。
    """
    daily_dir = os.path.join(BASE, "daily")
    os.makedirs(daily_dir, exist_ok=True)
    now = datetime.now()
    path = os.path.join(daily_dir, now.strftime("%Y%m%d") + ".md")

    out = [
        f"# 股票新闻信号日报 {now:%Y%m%d}",
        "",
        f"> 运行 {now:%Y-%m-%d %H:%M} | 新闻 {news_count} 条 | 命中 {len(ranked)} 只 | TOP{min(30, len(ranked))}",
        "> 定位：研究漏斗（缩小范围），非交易指令。",
        "",
        "## 概览",
        "",
        "| 排名 | 公司名称 | 代码 | 综合分 | 新闻来源 | 正面 | 负面 | 事件 |",
        "|---:|---|---|---:|---|---:|---:|---|",
    ]
    for i, r in enumerate(ranked[:30], 1):
        events = sorted({h["event"] for h in r["hits"]})
        srcs = "、".join(sorted({h.get("source", "未知") for h in r["hits"]}))
        out.append(f"| {i} | {r['name']} | {r['code']} | {r['score']:.1f} | {srcs} | {r['pos']} | {r['neg']} | {'、'.join(events)} |")

    out += ["", "## 明细", ""]
    for i, r in enumerate(ranked[:30], 1):
        reasons = [h["reason"] for h in r["hits"] if h.get("reason")][:2]
        reason = f"　*理由：{' / '.join(reasons)}*" if reasons else ""
        out.append(f"### {i}. {r['name']}（{r['code']}）score={r['score']:.1f}{reason}")
        out.append("")
        for h in sorted(r["hits"], key=lambda h: -h["score"])[:3]:
            tm = (h.get("time") or "")[11:16]  # 只取 HH:MM
            title = f"[{h['title']}]({h['url']})" if h.get("url") else h["title"]
            out.append(f"- `{tm}` **{h['event']}**（{h.get('source', '未知')}） {title}")
        out.append("")

    # 宏观/地缘动态板块（东财关键词搜索源，独立展示不进排名）
    macro = [n for n in (news or []) if n.get("source") == "eastmoney-search"]
    if macro:
        macro.sort(key=lambda n: n.get("time") or "", reverse=True)
        out += ["## 宏观/地缘动态（贸易战/制裁/出口管制）", ""]
        for n in macro[:20]:
            tm = (n.get("time") or "")[5:16]
            tag = n.get("tag") or "未分类"
            title = f"[{n['title']}]({n['url']})" if n.get("url") else n["title"]
            media = f"（{n['media']}）" if n.get("media") else ""
            out.append(f"- `{tm}` **[{tag}]** {title} {media}")
        out.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print(f"→ {path}")

    # 结构化信号顺产（DB 同步/回测用）：output/signals_yyyymmdd.json
    sig_path = os.path.join(BASE, "output", "signals_" + now.strftime("%Y%m%d") + ".json")
    sig = [{
        "trade_date": now.strftime("%Y-%m-%d"),
        "rank": i, "code": r["code"], "name": r["name"],
        "score": round(r["score"], 2), "pos": r["pos"], "neg": r["neg"],
        "events": sorted({h["event"].split("] ")[-1] for h in r["hits"]}),
        "hits": r["hits"],
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
    } for i, r in enumerate(ranked[:100], 1)]
    with open(sig_path, "w", encoding="utf-8") as f:
        json.dump(sig, f, ensure_ascii=False, indent=1)
    print(f"→ {sig_path}（{len(sig)} 条信号）")


if __name__ == "__main__":
    main()
