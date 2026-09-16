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
    "zhihu-pins": "知乎·关注",
    "cninfo-announce": "巨潮资讯",
    "cninfo-legal": "司法风险",
    "sina-live": "新浪7x24",
    "longhubang": "龙虎榜",
    "irm-qa": "互动易",
    "org-survey": "机构调研",
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
    (r"(分红|派息|利润分配)", 1.5, "分红派息"),
    (r"(并购|重组|借壳|收购)", 2.5, "并购重组"),
    (r"(涨停|大涨|飙升|暴涨)", 1.0, "已大涨(谨慎)"),
    (r"(下跌|暴跌|亏损|预减|减持|质押|立案|调查|处罚|退市)", -3.0, "负面"),
    (r"(涉及诉讼|重大诉讼|诉讼.{0,4}进展|仲裁)", -2.5, "诉讼仲裁"),
    (r"(股份.{0,6}被.{0,4}冻结|资金被冻结|司法拍卖|破产重整|清算)", -3.0, "资产风险"),
    (r"(龙虎榜).{0,30}(净买入)", 2.0, "资金异动"),
    (r"(龙虎榜).{0,30}(净卖出)", -2.0, "资金流出"),
    (r"(\d+)家机构调研", 1.8, "机构调研"),
    (r"互动易", 1.0, "互动易回复"),
]
DECAY_HOURS = 72.0  # 时效半衰期：3 天
HITL_PENDING = {}   # classify 收集的待判定 {(url,事件): 详情}，main 末尾写文件
HITL_LABELS_LOADED = {}

# ---- HITL 语义歧义闭环（F4.7）：负面事件命中否定/澄清语境 → 挂起待人工判定 ----
NEG_EVENT_NAMES = {"负面", "诉讼仲裁", "资产风险", "资金流出"}
AMBIG_CTX = re.compile(r"(未|不是|不再|没有|澄清|否认|不存在|否认知情|传闻|媒体报道)")
# 人工判定 → (权重, 事件名)；"负" 维持原值
HITL_JUDGE = {"正": (2.0, "人工确认正面"), "中性": (0.0, "澄清/中性")}
HITL_LABELS = os.path.join(BASE, "data", "hitl_labels.jsonl")


def load_hitl_labels():
    """标注库：{(url或标题, 事件名): 正/负/中性}（hitl_review.py --import 维护）。"""
    out = {}
    if os.path.exists(HITL_LABELS):
        for line in open(HITL_LABELS, encoding="utf-8"):
            try:
                r = json.loads(line)
                out[(r.get("key") or "", r.get("event") or "")] = r.get("judgment", "")
            except Exception:
                pass
    return out


def is_ambiguous(text, pattern):
    """负面事件词命中处前 30 字窗口含否定/澄清语境 → 语义歧义（需人工）。
    30 字依据：'公司未直接或通过控制主体间接参与XX的破产重整'类长否定（实测案例）。"""
    for m in re.finditer(pattern, text):
        ctx = text[max(0, m.start() - 30):m.start() + len(m.group(0)) + 5]
        if AMBIG_CTX.search(ctx):
            return True
    return False


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


def _name_from_body(text, code):
    """词典外代码的公司名提取：匹配 body 中「名称（代码）」模式（巨潮公告 body 内置）。"""
    m = re.search(r"([\u4e00-\u9fa5A-Za-z0-9·]{2,20})（" + code + "）", text)
    return m.group(1) if m else None


def classify(text, news=None, labels=None, codes=None):
    """正则事件分类（含 HITL：负面歧义挂起/标注生效）。

    labels 键 = (股票代码, 事件名)（hitl_labels.jsonl 粒度契约：同一公司
    同类事件的判定一致）。codes = 本条新闻命中的股票集，任一命中即生效。
    """
    hits = []
    for pat, w, name in EVENT_RULES:
        if not re.search(pat, text):
            continue
        if w < 0 and name in NEG_EVENT_NAMES and news is not None:
            judged = None
            for c in (codes or []):
                judged = (labels or {}).get((c, name))
                if judged:
                    break
            if judged in HITL_JUDGE:
                jw, jname = HITL_JUDGE[judged]
                hits.append((jw, jname))
                continue
            if judged != "负" and is_ambiguous(text, pat):
                HITL_PENDING.setdefault((news.get("url") or news.get("title") or "", name), {
                    "title": news.get("title", ""), "event": name,
                    "suspended": round(w, 2), "source": news.get("source", ""),
                    "stocks": [c for c in (codes or [])][:5] or list(news.get("stocks") or [])[:5],
                    "text": text[:160],
                    "body": news.get("body", ""),          # 完整原文（判断依据）
                    "url": news.get("url", ""),
                    "time": news.get("time", ""),
                    "pattern": pat,                          # 命中的风险词模式（歧义证据）
                })
                hits.append((0.0, name + "(待判定)"))
                continue
        hits.append((w, name))
    if not hits:
        hits.append((0.5, "一般资讯"))
    return hits


def main():
    global HITL_LABELS_LOADED
    HITL_LABELS_LOADED = load_hitl_labels()
    if HITL_LABELS_LOADED:
        print(f"HITL 标注库: {len(HITL_LABELS_LOADED)} 条生效")
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
    # 网络差时整个通道拖慢主流程（每词 curl 多节点重试最长 90s）：
    # 设环境变量 SKIP_PRODUCTS=1 可跳过（快速模式，只损失板块联动信号）
    product_terms = []
    ptxt = os.path.join(BASE, "data", "products.txt")
    if os.environ.get("SKIP_PRODUCTS"):
        print("产品通道: SKIP_PRODUCTS=1，本次跳过（快速模式）")
    elif os.path.exists(ptxt):
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
        # 官方标注通道（东财 stockList / 巨潮公告）：权威性最高，权重 1.2。
        # 词典外代码也收录（一手公告源可发现词典外公司），名称从 body「名称（代码）」提取。
        # 只收 A 股股票代码段：沪 60/68、深 00/30；排除 ETF(15/51/56/58) 与北交所
        for code in n.get("stocks") or []:
            code = str(code).strip()
            if len(code) == 6 and code.isdigit() and code[:2] in ("60", "68", "00", "30"):
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
                    if code[:2] not in ("60", "68", "00", "30"):
                        continue  # 只收 A 股股票代码段，排除 ETF
                    if len(code) == 6 and code.isdigit():
                        matched.setdefault(code, (None, 1.0))
            events = [(
                item.get("impact", 0),
                LLM_EVENT_NAMES.get(item.get("event", "neutral"), item.get("event", "?")),
                item.get("confidence", 0.5),
                item.get("reason", ""),
            ) for item in llm_items]
        else:
            events = [(ew, ename, 1.0, "") for ew, ename in
                      classify(text, n, HITL_LABELS_LOADED, matched.keys())]
        for code, (term, mw) in matched.items():
            for ew, ename, conf, reason in events:
                key = (ename, ew > 0)
                rec = per_stock.setdefault(code, {
                    "code": code, "name": None, "hits": [],
                    "score": 0.0, "pos": 0, "neg": 0,
                })
                if rec["name"] is None:
                    rec["name"] = (next((nm for tm, c, nm, _ in terms if c == code), None)
                                   or _name_from_body(text, code) or code)
                # 一手信息源权威加成：官方公告/交易所榜单/董秘口径/调研披露 > 新闻转述
                auth = 1.5 if n.get("source") in (
                    "cninfo-announce", "longhubang", "irm-qa", "org-survey",
                    "cninfo-legal") else 1.0
                s = ew * conf * mw * d * auth
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
    write_hitl_pending()


def hitl_prejudge(items):
    """LLM 预判（公司/法人两维度）供人工参考。失败降级规则版。

    items: [{title, body, event}] -> [{"company","person","reason"}]（与输入等长）。
    """
    fallback = [{"company": "倾向中性", "person": "不涉及", "reason": "LLM不可用·歧义默认"}
                for _ in items]
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from llm_classify import get_key, call_llm, parse_json_loose
        key = get_key()
        if not key:
            return fallback
    except Exception:
        return fallback
    prompt_t = (
        "你是A股分析师。对下面每条「负面事件被否定/澄清语境修饰」的新闻，"
        "从两个维度预判影响方向：\n"
        "- company 公司维度：该新闻对公司(股票)层面是 正面/负面/中性\n"
        "- person 法人维度：对该公司法定代表人/高管个人的风险含义是 正面/负面/中性/不涉及\n"
        "输出 JSON 数组：\n"
        '[{{"id": 编号, "company": "正面/负面/中性", "person": "正面/负面/中性/不涉及", '
        '"reason": "15字内"}}]\n'
        "新闻：\n{items}")
    news_str = "\n".join(f"[{i}] {it['title']} | {it['body'][:200]}"
                         for i, it in enumerate(items))
    try:
        raw = call_llm(prompt_t.format(items=news_str), key)
    except Exception as e:
        print(f"[warn] HITL 预判 LLM 失败，用默认: {e}", file=sys.stderr)
        return fallback
    out = list(fallback)
    for r in parse_json_loose(raw):
        if isinstance(r, dict) and isinstance(r.get("id"), int) and 0 <= r["id"] < len(out):
            out[r["id"]] = {"company": str(r.get("company", "?"))[:6],
                            "person": str(r.get("person", "?"))[:6],
                            "reason": str(r.get("reason", ""))[:20]}
    return out


def write_hitl_pending():
    """HITL 待判定清单：output/hitl_pending_日期.md（人工回填后 hitl_review.py --import）。

    模板：预判三列（公司/法人/理由，LLM 生成，用户勿动）在 #判定结果/#判定原因 前作参考。
    """
    if not HITL_PENDING:
        return
    now = datetime.now()
    date8 = now.strftime("%Y%m%d")
    path = os.path.join(BASE, "output", f"hitl_pending_{date8}.md")
    L = [f"# HITL 待判定 {date8}", "",
         f"> {len(HITL_PENDING)} 条负面事件命中否定/澄清语境，负分已挂起（未计入综合分）。",
         "> 判定方法：把 `#判定结果` 占位符改为 正 / 负 / 中性；`#判定原因` 填简短原因（学习语料）。",
         "> 预判三列（公司/法人/理由）为系统参考，请勿改动。保存后执行：",
         "> `python3 scripts/hitl_review.py --import {本文件路径}`，再重跑当日打分生效。", "",
         "| 编号 | 股票 | 初判事件 | 挂起分 | 关键句 | 预判-公司 | 预判-法人 | 预判理由 | #判定结果 | #判定原因 |",
         "|---|---|---|---:|---|---|---|---|---|---|"]
    pend = sorted(HITL_PENDING.items())
    pre = hitl_prejudge([{"title": p["title"], "body": p.get("body", ""), "event": p["event"]}
                         for _, p in pend])
    for i, ((key, ev), p) in enumerate(pend):
        codes = ",".join(p["stocks"]) or "—"
        snippet = p["text"].replace("\n", " ")[:60]
        j = pre[i] if i < len(pre) else {}
        L.append(f"| P{i+1} | {codes} | {p['event']} | {p['suspended']} | {snippet} | "
                 f"{j.get('company', '—')} | {j.get('person', '—')} | {j.get('reason', '')} | "
                 f"#判定结果 | #判定原因 |")
    L += ["", "## 原文详情（判断依据）", ""]
    for i, ((key, ev), p) in enumerate(pend):
        src = SOURCE_NAMES.get(p["source"], p["source"])
        L += [f"### P{i+1} {p['title']}", "",
              f"- **股票**: {','.join(p['stocks']) or '—'} | **初判**: {p['event']}（挂起 {p['suspended']}）",
              f"- **来源**: {src} {p.get('time', '')}",
              f"- **歧义证据**: 风险词命中 `{p.get('pattern', '')}`，前 30 字含否定/澄清语境",
              f"- **链接**: {p.get('url') or '无'}", "", "**原文**:", "", p.get("body") or "（无正文）", ""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"→ {path}（{len(HITL_PENDING)} 条待人工判定）")


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
    # 正分 TOP100 + 负分 TOP20（最负优先）：纯负面股（司法风险等）也要可见，
    # 否则推荐层回避区永远看不到它们（负分进不了正序 TOP100）
    sig_path = os.path.join(BASE, "output", "signals_" + now.strftime("%Y%m%d") + ".json")
    pos_rows = [r for r in ranked if r["score"] > 0][:100]
    neg_rows = sorted([r for r in ranked if r["score"] <= 0], key=lambda r: r["score"])[:20]
    sig = [{
        "trade_date": now.strftime("%Y-%m-%d"),
        "rank": i, "code": r["code"], "name": r["name"],
        "score": round(r["score"], 2), "pos": r["pos"], "neg": r["neg"],
        "events": sorted({h["event"].split("] ")[-1] for h in r["hits"]}),
        "hits": r["hits"],
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
    } for i, r in enumerate(pos_rows + neg_rows, 1)]
    with open(sig_path, "w", encoding="utf-8") as f:
        json.dump(sig, f, ensure_ascii=False, indent=1)
    print(f"→ {sig_path}（{len(sig)} 条信号）")


if __name__ == "__main__":
    main()
