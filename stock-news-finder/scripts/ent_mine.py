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
