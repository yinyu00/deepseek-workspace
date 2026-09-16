#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实体信息累积层挖取脚本（ent_* 三表，模型见方案 2.11）。

通道：
  ① 词典命中 → ent_company_news（新闻×词典匹配 + risk_tags 打标）
  ③ 官方种子 → ent_person_company（legal_companies 的 F10 法人，confidence=official）
  ② LLM 人物抽取 → 第二批实现（预筛逻辑已就绪：--precheck-person 看候选量）

每条记录强制带 url + body_snapshot（仅文字快照，防撤回）。

用法：
  python scripts/ent_mine.py                    # 今日：读 output/raw_news.json
  python scripts/ent_mine.py --date 20260915    # 指定日（读 raw/yyyymmdd.json）
  python scripts/ent_mine.py --backfill         # 全量回填 raw/*.json
  python scripts/ent_mine.py --seed-person      # ③通道：F10法人 → ent_person_company
  python scripts/ent_mine.py --stats            # 三表统计
  python scripts/ent_mine.py --precheck-person  # ②通道候选量预览（职位词命中数）
"""
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "scripts"))
RAW_DIR = os.path.join(BASE, "raw")
OUT_RAW = os.path.join(BASE, "output", "raw_news.json")

MONGO_URI = os.environ.get("MONGODB_URI") or \
    "mongodb://root:236e2cb4f9c16647367fdaa1@127.0.0.1:27017/stock?authSource=admin&directConnection=true"

# 司法风险标签（正则 → 标签名，可扩）
RISK_TAG_RULES = [
    (r"立案|调查", "立案调查"),
    (r"处罚|罚款|罚没", "行政处罚"),
    (r"诉讼|起诉|被告|判决|裁决", "诉讼判决"),
    (r"冻结", "冻结"),
    (r"破产|重整|清算", "破产重整"),
    (r"退市", "退市"),
    (r"失信|被执行|强制执行", "失信执行"),
    (r"限制消费|限高|限制出境", "限高限出境"),
    (r"违规|违法|违纪", "违法违规"),
    (r"仲裁", "仲裁"),
]
# ②通道人物预筛：职位词（新闻标题/正文出现才送 LLM）
TITLE_WORDS = re.compile(
    r"(董事长|法定代表人|法人代表|实际控制人|实控人|总经理|首席执行官|CEO|CFO|总裁|创始人|董事|监事|高管|董秘)")

# ---- ②通道人物抽取（2026-09-15，方案：三级置信分流）----
# 姓名前置剥离（单字动词/介词粘连，实测伪姓名主源："为任在栋"→任在栋）
_LEAD = r"[为刚当将已正在又再曾被其该和与及由从对向并即仍便却]"
# 姓名 2-4 字（召回优先，碎片噪声交给 LLM 层精判——正则修不完滑窗切分问题）
P_NAME_TITLE = re.compile(rf"({_LEAD}?[\u4e00-\u9fa5]{{2,4}})(?:[^。，,；;！？\s]{{0,10}})?(董事长|法定代表人|法人代表|实际控制人|实控人|总经理|首席执行官|CEO|CFO|总裁|创始人|董秘)")
P_TITLE_NAME = re.compile(r"(董事长|法定代表人|实际控制人|总经理|总裁|创始人)[、，,\s:：]*([\u4e00-\u9fa5]{2,3})")
# 非人名黑名单（实测误命中：产品名/短语/机构词根）
STOP_WORDS = {"飞书", "职务", "中国", "安全", "龙头", "今日", "昨日", "近日", "此前", "随后",
              "公司", "集团", "股份", "科技", "电子", "智能", "能源", "生物", "方正"}
CORP_SUFFIX = re.compile(r"(公司|集团|股份|科技|电子|证券|银行|药业|控股|尚无|板上)$")
# 人物事件正则（无命中默认「观点言论」）
PERSON_EVENT = [
    (r"被查|留置|逮捕|被捕|拘留|判刑|调查|立案", "司法风险"),
    (r"失信|被执行|强制执行|限高|限制消费|限制出境", "司法风险"),
    (r"处罚|罚款|罚没|违纪|违法", "司法风险"),
    (r"减持|增持|质押", "增减持"),
    (r"辞任|辞职|离任|卸任|去职", "人事变动"),
    (r"聘任|上任|履新|接任|获任|出任", "人事变动"),
]


# 姓名后置剥离（动词/时间副词粘连："陈刚任中"→陈刚、"郭大勇履"→郭大勇、"李柯近日"→李柯）
_TRAIL = re.compile(r"(任|履|将|迎|超|执|辞|离|出|到|称|表示|指出|近日|昨日|今日|此前|当天|当天上午)$")


def _clean_name(raw):
    """剥离前后置单字动词，黑名单/企业词根过滤；非法返回 None。"""
    name = re.sub(rf"^({_LEAD})", "", raw or "").strip()
    name = _TRAIL.sub("", name)
    if len(name) < 2 or name in STOP_WORDS or CORP_SUFFIX.search(name):
        return None
    return name


def extract_persons(text):
    """文本 → [{name, role}]（去重）。"""
    out = {}
    for m in P_NAME_TITLE.finditer(text):
        n = _clean_name(m.group(1))
        if n:
            out[n] = m.group(2)
    for m in P_TITLE_NAME.finditer(text):
        n = _clean_name(m.group(2))
        if n and n not in out:
            out[n] = m.group(1)
    return [{"name": k, "role": v} for k, v in out.items()]


def person_event(text):
    for pat, ev in PERSON_EVENT:
        if re.search(pat, text):
            return ev
    return "观点言论"


# ---- ②通道 LLM 判定（suspected → 是否人名 + 事件精分，glm-4v-flash 免费批量）----
LLM_PROMPT = """你是A股新闻分析师。判断下面每条候选是否为「真实人物姓名」，并分类其动态。

事件枚举（选其一）：司法风险(被查/逮捕/限高/失信/处罚)、人事变动(辞任/聘任)、增减持(减持/增持/质押)、观点言论、其他

输出 JSON 数组：
[{{"id": 编号, "is_person": true/false, "name": "从原文提取的完整真实姓名(is_person=false时空串)", "event": "类型", "reason": "8字内理由"}}]

候选列表（格式：[id] 候选名 | 标题 | 正文片段）：
{items}"""


def llm_verify_persons(cands):
    """cands: [{id,name,title,body}] → {id: {is_person, event, reason}}；失败返回 {}。"""
    sys.path.insert(0, os.path.join(BASE, "scripts"))
    try:
        from llm_classify import get_key, call_llm, parse_json_loose
    except ImportError:
        return {}
    key = get_key()
    if not key:
        print("[warn] 无 GLM key，suspected 全部丢弃（只保留 confirmed）")
        return {}
    out = {}
    B = 8
    for i in range(0, len(cands), B):
        chunk = cands[i:i + B]
        items = "\n".join(f"[{c['id']}] {c['name']} | {c['title'][:40]} | {c['body'][:100]}"
                          for c in chunk)
        try:
            raw = call_llm(LLM_PROMPT.format(items=items), key)
        except Exception as e:
            print(f"[warn] LLM 批次失败: {e}", file=sys.stderr)
            continue
        for item in parse_json_loose(raw):
            if isinstance(item, dict) and "id" in item:
                out[item["id"]] = item
        time.sleep(1)
    return out


def mine_person_news(db, news_list, matcher, trade_date, known=None, dry=False, use_llm=True):
    """②通道：职位预筛 → 姓名抽取 → 三级置信 → ent_person_news。

    known: 已知人物库 {name: (code, company)}；db 为 None（dry-run）时从文件画像降级。
    返回 (统计, 样本列表)。
    """
    UpdateOne = None
    if not dry:
        from pymongo import UpdateOne  # dry-run 无 pymongo 依赖
    known = known or {}
    stats = {"candidates": 0, "extracted": 0, "confirmed": 0, "llm_ok": 0, "discarded": 0}
    samples, ops, link_ops = [], [], []

    for n in news_list:
        title = (n.get("title") or "").strip()
        body = (n.get("body") or "").strip()
        text = title + "\n" + body[:500]
        if not TITLE_WORDS.search(title + body[:300]):
            continue
        stats["candidates"] += 1
        persons = extract_persons(text)
        if not persons:
            continue
        stats["extracted"] += 1
        # 新闻关联公司上下文（复用词典，取最强命中）
        ctx = {}
        for term, code, name, w in matcher:
            if term in text and (code not in ctx or w > ctx[code][1]):
                ctx[code] = (name, w)
        tm = _parse_time(n.get("time"))
        url = n.get("url") or title
        for p in persons:
            name = p["name"]
            if name in known:
                conf, code_ctx, comp_ctx = "confirmed", known[name][0], known[name][1]
                stats["confirmed"] += 1
            else:
                conf = "suspected"
                code_ctx = next(iter(ctx), "") or ""
                comp_ctx = (ctx.get(code_ctx) or ("", 0))[0] if code_ctx else ""
            ev = person_event(text)
            rec = {
                "person_name": name, "role_mentioned": p["role"],
                "company_context": comp_ctx, "code_context": code_ctx,
                "person_event": ev, "title": title,
                "body_snapshot": body[:5000], "url": n.get("url") or "",
                "source": n.get("source") or "", "news_time": tm,
                "news_time_s": n.get("time") or "",
                "confidence": conf, "trade_date": (n.get("time") or "")[:10].replace("-", "") or trade_date,
                "mined_at": datetime.now(),
            }
            samples.append(rec)
            if not dry and conf == "confirmed":
                ops.append(UpdateOne({"_id": _md5(url + "|" + name)},
                                     {"$set": rec}, upsert=True))

    # suspected 批量送 LLM 判定
    suspected = [r for r in samples if r["confidence"] == "suspected"]
    if suspected and use_llm and not dry:
        cands = [{"id": i, "name": r["person_name"], "title": r["title"],
                  "body": r["body_snapshot"][:150]} for i, r in enumerate(suspected)]
        verdicts = llm_verify_persons(cands)
        keep_ops = []
        for i, r in enumerate(suspected):
            v = verdicts.get(i) or {}
            if v.get("is_person"):
                r["confidence"] = "llm_verified"
                # LLM 修正碎片名（"陈刚任中"→陈刚、"任在"→任在栋）
                fixed = str(v.get("name") or "").strip()
                if 2 <= len(fixed) <= 4 and fixed != r["person_name"]:
                    r["name_raw_extract"] = r["person_name"]  # 保留痕迹
                    r["person_name"] = fixed
                r["person_event"] = v.get("event") or r["person_event"]
                r["reason"] = v.get("reason", "")
                stats["llm_ok"] += 1
                keep_ops.append(UpdateOne({"_id": _md5(r["url"] + "|" + r["person_name"])},
                                          {"$set": r}, upsert=True))
            else:
                stats["discarded"] += 1
        ops.extend(keep_ops)
    elif suspected:
        stats["discarded"] += len(suspected)  # dry-run / 无 LLM：只展示不入库

    # confirmed 的回填 ent_person_company 关联（confidence=news）
    if not dry and db is not None:
        for r in samples:
            if r["confidence"] in ("confirmed", "llm_verified") and r["code_context"]:
                link_ops.append(UpdateOne(
                    {"_id": f"{r['person_name']}|{r['code_context']}|news"},
                    {"$set": {"person_name": r["person_name"], "code": r["code_context"],
                              "company": r["company_context"], "role": r["role_mentioned"],
                              "share_pct": None, "confidence": r["confidence"],
                              "evidence": r["url"], "first_seen": datetime.now(),
                              "last_seen": datetime.now(), "active": True,
                              "source": "news"},
                     "$setOnInsert": {"created_at": datetime.now()}}, upsert=True))
        if ops:
            db.ent_person_news.bulk_write(ops, ordered=False)
        if link_ops:
            db.ent_person_company.bulk_write(link_ops, ordered=False)
    return stats, samples


def load_known_persons(db):
    """已知人物库：ent_person_company（F10法人种子+新闻回填）。dry-run 无 db 时降级文件画像。"""
    known = {}
    if db is not None:
        for p in db.ent_person_company.find({}, {"person_name": 1, "code": 1, "company": 1}):
            known[p["person_name"]] = (p.get("code", ""), p.get("company", ""))
        return known
    # Mac dry-run：legal_fallback.jsonl 画像降级（有就用，没有 suspected 全走 LLM）
    fb = os.path.join(BASE, "data", "legal_fallback.jsonl")
    if os.path.exists(fb):
        for line in open(fb, encoding="utf-8"):
            try:
                r = json.loads(line)
                if r.get("legal_person"):
                    known[r["legal_person"]] = (r.get("code", ""), r.get("company", ""))
            except Exception:
                pass
    return known


def _md5(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def _parse_time(s):
    try:
        return datetime.strptime((s or "")[:19], "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def risk_tags(text):
    return [tag for pat, tag in RISK_TAG_RULES if re.search(pat, text)]


def get_db():
    try:
        from pymongo import MongoClient
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=4000)
        db = client["stock"]
        db.command("ping")
        return db
    except Exception as e:
        sys.exit(f"[err] Mongo 不可用：{e}")


def ensure_index(db):
    db.ent_company_news.create_index([("code", 1), ("news_time", -1)])
    db.ent_company_news.create_index("risk_tags")
    db.ent_company_news.create_index("event_type")
    db.ent_person_news.create_index([("person_name", 1), ("news_time", -1)])
    db.ent_person_news.create_index("person_event")
    db.ent_person_company.create_index("person_name")
    db.ent_person_company.create_index([("code", 1), ("active", 1)])
    db.ent_person_company.create_index([("person_name", 1), ("code", 1)])


def build_matcher():
    """复用 match_score 的词典构建（名称 w=2 / 别名 w=1，长词优先）。"""
    import match_score as ms
    return ms.build_matcher()


def mine_company_news(db, news_list, matcher, trade_date):
    """①通道：新闻×词典 → ent_company_news（一新闻多公司=多条）。"""
    from pymongo import UpdateOne
    ops = []
    for n in news_list:
        title = (n.get("title") or "").strip()
        body = (n.get("body") or "").strip()
        if not title:
            continue
        text = title + "\n" + body
        # 公司命中（按 code 去重，保最强命中词）
        best = {}
        for term, code, name, w in matcher:
            if term in text and (code not in best or w > best[code][1]):
                best[code] = (name, w, term)
        if not best:
            continue
        tags = risk_tags(text)
        tm = _parse_time(n.get("time"))
        news_date = (n.get("time") or "")[:10].replace("-", "") or trade_date
        key_src = (n.get("url") or title)
        for code, (name, w, term) in best.items():
            doc = {
                "code": code, "name": name, "company": "",  # 全称后续 F10 补
                "title": title, "body_snapshot": body[:5000],
                "url": n.get("url") or "", "source": n.get("source") or "",
                "news_time": tm, "news_time_s": n.get("time") or "",
                "event_type": "", "impact": None, "confidence": None, "reason": "",
                "risk_tags": tags, "match_term": term,
                "trade_date": news_date, "mined_at": datetime.now(),
            }
            ops.append(UpdateOne({"_id": _md5(key_src + "|" + code)},
                                 {"$set": doc}, upsert=True))
    if ops:
        db.ent_company_news.bulk_write(ops, ordered=False)
    return len(ops)


def seed_person_company(db):
    """③通道：legal_companies（F10 官方法人）→ ent_person_company 种子。"""
    from pymongo import UpdateOne
    ops = []
    for p in db.legal_companies.find({}, {"code": 1, "company": 1, "legal_person": 1, "name": 1}):
        person = (p.get("legal_person") or "").strip()
        code = p.get("code")
        if not person or not code:
            continue
        ops.append(UpdateOne(
            {"_id": f"{person}|{code}|legal_rep"},
            {"$set": {
                "person_name": person, "code": code,
                "company": p.get("company") or p.get("name") or "",
                "role": "legal_rep", "share_pct": None,
                "confidence": "official", "evidence": None,
                "first_seen": datetime.now(), "last_seen": datetime.now(),
                "active": True, "source": "f10",
            }, "$setOnInsert": {"created_at": datetime.now()}},
            upsert=True))
    if ops:
        db.ent_person_company.bulk_write(ops, ordered=False)
    return len(ops)


def load_news(date=None, backfill=False):
    """待挖新闻集：指定日 / 今日工作区 / 全量归档。"""
    if backfill:
        out = []
        for fn in sorted(os.listdir(RAW_DIR)):
            if fn.endswith(".json"):
                try:
                    out.extend(json.load(open(os.path.join(RAW_DIR, fn), encoding="utf-8")))
                except Exception:
                    pass
        return out, "backfill"
    path = os.path.join(RAW_DIR, f"{date}.json") if date else OUT_RAW
    if not os.path.exists(path):
        path = OUT_RAW
    if not os.path.exists(path):
        sys.exit("无可用新闻（先跑 fetch_news.py）")
    return json.load(open(path, encoding="utf-8")), os.path.basename(path)


def main():
    args = sys.argv[1:]
    if "--dry-run" in args:
        db = None  # dry-run 不连 Mongo（Mac 开发验证用）
    else:
        db = get_db()
        ensure_index(db)

    if "--stats" in args:
        for col in ("ent_company_news", "ent_person_news", "ent_person_company"):
            print(f"{col}: {db[col].count_documents({})} 条")
        s = db.command("dbstats")
        print(f"库大小: {s.get('dataSize', 0) / 1024 / 1024:.1f} MB")
        return

    if "--seed-person" in args:
        n = seed_person_company(db)
        print(f"③官方种子: ent_person_company upsert {n} 条")
        return

    if "--mine-person" in args:
        dry = "--dry-run" in args
        if dry:
            db = None
            print("[dry-run] 不连 Mongo，只预览抽取结果")
        date = args[args.index("--date") + 1] if "--date" in args else datetime.now().strftime("%Y%m%d")
        news, src = load_news(None if "--backfill" in args else date, "--backfill" in args)
        known = load_known_persons(db)
        matcher = build_matcher()
        stats, samples = mine_person_news(db, news, matcher, date, known=known,
                                          dry=dry, use_llm="--no-llm" not in args)
        print(f"②人物通道 [{src}]: 候选 {stats['candidates']} → 抽中 {stats['extracted']}"
              f" → confirmed {stats['confirmed']} / llm_verified {stats['llm_ok']}"
              f" / 丢弃 {stats['discarded']}")
        print(f"已知人物库: {len(known)} 人")
        for r in samples[:15]:
            tag = {"confirmed": "✓库确认", "suspected": "?待LLM", "llm_verified": "◈LLM过"}.get(
                r["confidence"], r["confidence"])
            print(f"  [{tag}] {r['person_name']}({r['role_mentioned']}) {r['person_event']}"
                  f" | {r['company_context'] or '—'} | {r['title'][:32]}")
        return

    if "--precheck-person" in args:
        i = args.index("--precheck-person")
        d = None
        if i + 1 < len(args) and not args[i + 1].startswith("--"):
            d = args[i + 1]
        news, src = load_news(d, "--backfill" in args)
        cand = [n for n in news if TITLE_WORDS.search((n.get("title") or "") + (n.get("body") or "")[:300])]
        print(f"{src}: {len(news)} 条中职位词候选 {len(cand)} 条（②通道 LLM 输入量）")
        for n in cand[:5]:
            print("  ·", (n.get("title") or "")[:50])
        return

    date = args[args.index("--date") + 1] if "--date" in args else datetime.now().strftime("%Y%m%d")
    news, src = load_news(None if "--backfill" in args else date, "--backfill" in args)
    trade_date = date if not args or "--backfill" not in args else "backfill"
    matcher = build_matcher()
    n = mine_company_news(db, news, matcher, trade_date)
    print(f"①词典通道 [{src}]: ent_company_news upsert {n} 条")


if __name__ == "__main__":
    main()
