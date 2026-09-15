#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""法人司法风险检查 P0（半自动：机器拉公司画像 + 人工核执行网 + 结果入库出表）。

数据链路：
  signals_YYYYMMDD.json TOP-N ──东财F10──▶ 公司画像(法人/信用代码) ──人工查执行网──▶ 风险记录 ──▶ Mongo + 附录表

用法：
  python scripts/legal_check.py                          # 今天：生成待核清单 output/legal_pending_日期.md
  python scripts/legal_check.py --date 20260913 --top 30 # 指定日期/条数
  python scripts/legal_check.py --result output/legal_result_20260913.md   # 导入人工核查结果 → 出附录
  python scripts/legal_check.py --show 20260913          # 查看某日已入库风险表

人工结果文件格式（每行一条，竖线分隔；md 表格行也兼容）：
  股票代码|法人姓名|类型|案号|标的金额|立案日期|具体原因
  600519|陈华|无||||                                  ← 查了没问题，写「无」
  类型枚举：被执行 / 失信 / 限高 / 无

Mongo（库 stock，缺失自动降级文件缓存 data/legal_fallback.jsonl）：
  legal_companies  公司画像：_id=股票代码 {uscc, company, legal_person, ...}
  legal_risks      风险记录：唯一键(code, risk_type, case_no) {person, amount, filed_date, reason, status}
  legal_checks     运行日志：{trade_date, top_n, fetched, cached, pending}
"""
import gzip
import json
import os
import re
import ssl
import sys
import time
import urllib.request
import zlib
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE, "output")
DATA_DIR = os.path.join(BASE, "data")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36"
F10_API = "https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/PageAjax?code={code}"
RISK_TYPES = {"被执行": "executed", "失信": "dishonest", "限高": "limit_high", "无": "none"}
RISK_NAMES = {v: k for k, v in RISK_TYPES.items()}
RECHECK_DAYS = 7          # 公司画像/人工核查 7 天内不重复核
F10_SLEEP = 0.4           # 东财限速

MONGO_URI = os.environ.get("MONGODB_URI") or \
    "mongodb://root:236e2cb4f9c16647367fdaa1@127.0.0.1:27017/stock?authSource=admin&directConnection=true"


def _deco(raw):
    for fn in (gzip.decompress, lambda x: zlib.decompress(x, -15), zlib.decompress, lambda x: x):
        try:
            return fn(raw)
        except Exception:
            continue
    return raw


def http_get(url, timeout=15):
    """GET → bytes；公司 TLS 拦截自动降级（同 zhihu_pins 策略）。"""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return _deco(r.read())
    except ssl.SSLError:
        pass
    except urllib.error.URLError as e:
        if not isinstance(getattr(e, "reason", None), ssl.SSLError):
            raise
    ctx = ssl._create_unverified_context()
    ctx.set_ciphers("DEFAULT@SECLEVEL=1")
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return _deco(r.read())


# ---------------- Mongo（可选，降级文件缓存） ----------------

def get_db():
    try:
        from pymongo import MongoClient
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=4000)
        db = client["stock"]
        db.command("ping")
        _ensure_index(db)
        return db, None
    except Exception as e:
        fallback = os.path.join(DATA_DIR, "legal_fallback.jsonl")
        print(f"[warn] Mongo 不可用（{e}），降级文件缓存 {fallback}", file=sys.stderr)
        return None, fallback


def _ensure_index(db):
    db.legal_companies.create_index("uscc")
    db.legal_risks.create_index([("code", 1), ("risk_type", 1), ("case_no", 1)], unique=True)
    db.legal_risks.create_index([("person", 1), ("status", 1)])
    db.legal_checks.create_index("trade_date")


def _fallback_rows(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return [json.loads(x) for x in f if x.strip()]
    return []


def _fallback_append(path, doc):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(doc, ensure_ascii=False) + "\n")


def upsert_company(db, fallback, doc):
    if db is not None:
        db.legal_companies.update_one({"_id": doc["code"]}, {"$set": doc}, upsert=True)
    else:
        rows = [r for r in _fallback_rows(fallback) if r.get("code") != doc["code"]]
        rows.append(doc)
        with open(fallback, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")


def load_company(db, fallback, code):
    if db is not None:
        return db.legal_companies.find_one({"_id": code})
    for r in _fallback_rows(fallback):
        if r.get("code") == code:
            return r
    return None


def upsert_risk(db, fallback, doc):
    key = {"code": doc["code"], "risk_type": doc["risk_type"], "case_no": doc["case_no"]}
    if db is not None:
        db.legal_risks.update_one(key, {"$set": doc, "$setOnInsert": {"created_at": datetime.now()}}, upsert=True)
    else:
        rows = _fallback_rows(fallback)
        out, replaced = [], False
        for r in rows:
            if r.get("code") == doc["code"] and r.get("risk_type") == doc["risk_type"] \
                    and r.get("case_no") == doc["case_no"]:
                out.append(doc)
                replaced = True
            else:
                out.append(r)
        if not replaced:
            out.append(doc)
        with open(fallback, "w", encoding="utf-8") as f:
            for r in out:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")


def find_risks(db, fallback, codes):
    if db is not None:
        return list(db.legal_risks.find({"code": {"$in": codes}, "status": "active"}))
    return [r for r in _fallback_rows(fallback)
            if r.get("code") in codes and r.get("status") == "active" and r.get("_type") == "risk"]


# ---------------- ① 公司画像（东财 F10） ----------------

def exchange_prefix(code):
    if code.startswith("6"):
        return "SH"
    if code.startswith(("0", "3")):
        return "SZ"
    return "BJ"


def fetch_f10_profile(code):
    """东财 F10 公司概况 → 画像 dict；失败返回 None。"""
    for attempt in range(3):
        try:
            d = json.loads(http_get(F10_API.format(code=exchange_prefix(code) + code)).decode("utf-8", "ignore"))
            jb = d.get("jbzl") or []
            if isinstance(jb, list) and jb:
                jb = jb[0]
            if not jb or not jb.get("LEGAL_PERSON"):
                return None
            return {
                "code": code,
                "name": jb.get("SECURITY_NAME_ABBR") or "",
                "company": jb.get("ORG_NAME") or "",
                "uscc": jb.get("REG_NUM") or "",
                "legal_person": jb.get("LEGAL_PERSON") or "",
                "chairman": jb.get("CHAIRMAN") or "",
                "president": jb.get("PRESIDENT") or "",
                "province": jb.get("PROVINCE") or "",
                "industry": jb.get("EM2016") or "",
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        except Exception as e:
            if attempt == 2:
                print(f"[warn] F10 {code} 失败: {e}", file=sys.stderr)
            time.sleep(2)
    return None


def load_signals(date, top_n):
    path = os.path.join(OUT_DIR, f"signals_{date}.json")
    if not os.path.exists(path):
        sys.exit(f"找不到 {path}（先跑 match_score.py）")
    with open(path, encoding="utf-8") as f:
        rows = json.load(f)
    rows.sort(key=lambda r: r.get("rank", 999))
    seen, out = set(), []
    for r in rows:
        c = str(r.get("code", "")).zfill(6)
        if c and c not in seen:
            seen.add(c)
            out.append({"code": c, "name": r.get("name", ""), "score": r.get("score", 0)})
        if len(out) >= top_n:
            break
    return out


def build_profiles(signals, db, fallback):
    """画像缓存优先（7 天内有效），否则 F10 拉取。"""
    fetched = cached = 0
    out = []
    for i, s in enumerate(signals):
        doc = load_company(db, fallback, s["code"])
        fresh = False
        if doc and doc.get("updated_at"):
            try:
                fresh = (datetime.now() - datetime.strptime(doc["updated_at"][:19], "%Y-%m-%d %H:%M:%S")) < timedelta(days=RECHECK_DAYS)
            except Exception:
                pass
        if fresh:
            cached += 1
        else:
            doc = fetch_f10_profile(s["code"])
            if doc is None:
                print(f"[warn] {s['code']} 画像缺失，跳过", file=sys.stderr)
                continue
            upsert_company(db, fallback, doc)
            fetched += 1
            time.sleep(F10_SLEEP)
        doc["_signal"] = s
        out.append(doc)
    return out, fetched, cached


# ---------------- ② 待核清单生成 ----------------

ZXGK = {
    "失信": "https://zxgk.court.gov.cn/shixin/",
    "被执行": "https://zxgk.court.gov.cn/zhixing/new/select",
    "限高": "https://zxgk.court.gov.cn/limit/limit?layui",
}


def gen_pending(date, profiles, db, fallback):
    """output/legal_pending_日期.md：去重法人 + 查询入口 + 填写模板。"""
    def checked_recently(doc):
        t = doc.get("last_checked")
        if not t:
            return False
        try:
            return (datetime.now() - datetime.strptime(t[:19], "%Y-%m-%d %H:%M:%S")) < timedelta(days=RECHECK_DAYS)
        except Exception:
            return False

    persons = {}
    for p in profiles:
        key = (p.get("legal_person"), p.get("code"))
        persons.setdefault(key, p)
    todo = [p for p in persons.values() if not checked_recently(p)]
    done = len(persons) - len(todo)

    path = os.path.join(OUT_DIR, f"legal_pending_{date}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# 法人司法风险 · 待核清单 {date}\n\n")
        f.write(f"> 公司 {len(profiles)} 家 | 需人工核查 {len(todo)} 人 | 7 天内核过跳过 {done} 人\n")
        f.write("> 入口（复制姓名/信用代码粘贴查询，验证码人工点）：\n")
        for name, url in ZXGK.items():
            f.write(f"> - {name}：{url}\n")
        f.write("\n## 待核（按日报得分排序）\n\n")
        f.write("| 股票代码 | 公司 | 法人 | 信用代码 | 省份 | 查询姓名 |\n|---|---|---|---|---|---|\n")
        for p in sorted(todo, key=lambda x: -x["_signal"]["score"]):
            f.write(f"| {p['code']} | {p['company']} | {p['legal_person']} | {p.get('uscc','')} | "
                    f"{p.get('province','')} | {p['legal_person']} |\n")
        f.write("\n## 结果填写区（查完在下面对应行补充，或新建 legal_result_日期.md 同格式）\n\n")
        f.write("```\n# 格式：股票代码|法人姓名|类型|案号|标的金额|立案日期|具体原因   （无风险填：代码|姓名|无||||）\n")
        for p in todo:
            f.write(f"{p['code']}|{p['legal_person']}|||||\n")
        f.write("```\n")
        f.write("\n完成后执行：`python scripts/legal_check.py --result 本文件路径`\n")
    print(f"→ 待核清单 {path}（{len(todo)} 人待查，{done} 人 7 天内已核）")
    return len(todo)


# ---------------- ③ 结果导入 + 附录表 ----------------

def parse_result_lines(text):
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        if line.startswith("```") or set(line) <= {"|", "-", " ", ":"}:  # 代码栏/表头分隔线
            continue
        parts = [x.strip() for x in line.strip("|").split("|")]
        if len(parts) < 3 or not re.match(r"^\d{6}$", parts[0]):
            continue
        rows.append(parts)
    return rows


def import_results(date, result_path, db, fallback):
    with open(result_path, encoding="utf-8") as f:
        rows = parse_result_lines(f.read())
    n_risk = n_clean = 0
    for parts in rows:
        code, person = parts[0], parts[1]
        rtype_cn = parts[2] if len(parts) > 2 else ""
        rtype = RISK_TYPES.get(rtype_cn)
        if rtype is None:
            print(f"[warn] 未知类型行跳过: {parts}", file=sys.stderr)
            continue
        doc = load_company(db, fallback, code)
        base = {"code": code, "person": person, "trade_date": date,
                "company": (doc or {}).get("company", ""), "uscc": (doc or {}).get("uscc", ""),
                "source": "zxgk-manual", "status": "active", "updated_at": datetime.now()}
        if rtype == "none":
            base.update({"risk_type": "none", "case_no": "", "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
            # 「无风险」写进画像的 last_checked，风险表不落脏数据
            if db is not None:
                db.legal_companies.update_one({"_id": code}, {"$set": {"last_checked": base["last_checked"]}})
            else:
                c = load_company(None, fallback, code) or {"code": code}
                c["last_checked"] = base["last_checked"]
                upsert_company(None, fallback, c)
            n_clean += 1
            continue
        base.update({
            "risk_type": rtype,
            "case_no": parts[3] if len(parts) > 3 else "",
            "amount": parts[4] if len(parts) > 4 else "",
            "filed_date": parts[5] if len(parts) > 5 else "",
            "reason": parts[6] if len(parts) > 6 else "",
            "_type": "risk",
        })
        upsert_risk(db, fallback, base)
        n_risk += 1
    print(f"导入完成：风险 {n_risk} 条 / 无风险 {n_clean} 条")
    return n_risk


def gen_appendix(date, db, fallback):
    """4 列附录表：公司代码(信用代码) | 法人姓名 | 股票代码 | 具体原因。"""
    signals = load_signals(date, 10 ** 6)
    codes = [s["code"] for s in signals]
    risks = find_risks(db, fallback, codes)
    by_code = {}
    for r in risks:
        by_code.setdefault(r["code"], []).append(r)
    path = os.path.join(OUT_DIR, f"legal_risk_{date}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# 法人司法风险附录 · {date}\n\n")
        f.write(f"> 数据源：中国执行信息公开网（人工核查）| 覆盖 TOP{len(codes)} 信号股 | 风险 {len(risks)} 条\n\n")
        f.write("| 公司代码 | 法人姓名 | 股票代码 | 具体原因 |\n|---|---|---|---|\n")
        for s in signals:
            for r in by_code.get(s["code"], []):
                seg = [RISK_NAMES.get(r.get("risk_type"), r.get("risk_type"))]
                if r.get("case_no"):
                    seg.append(str(r["case_no"]))
                if r.get("amount"):
                    seg.append(f"标的{r['amount']}")
                if r.get("filed_date"):
                    seg.append(f"{r['filed_date']}立案")
                if r.get("reason"):
                    seg.append(str(r["reason"]))
                uscc = r.get("uscc") or "—"
                f.write(f"| {uscc} | {r.get('person','')} | {s['code']} | {'·'.join(seg)} |\n")
        if not risks:
            f.write("| — | — | — | 暂无已导入的风险记录 |\n")
    print(f"→ 附录表 {path}（{len(risks)} 条风险）")
    return path


def show(date, db, fallback):
    signals = load_signals(date, 10 ** 6)
    codes = [s["code"] for s in signals]
    for r in find_risks(db, fallback, codes):
        print(f"{r['code']} {r.get('person')} {RISK_NAMES.get(r['risk_type'], r['risk_type'])} "
              f"{r.get('case_no','')} {r.get('reason','')}")


def main():
    args = sys.argv[1:]
    date = args[args.index("--date") + 1] if "--date" in args else datetime.now().strftime("%Y%m%d")
    top_n = int(args[args.index("--top") + 1]) if "--top" in args else 30
    db, fallback = get_db()

    if "--show" in args:
        return show(date, db, fallback)

    if "--result" in args:
        result_path = args[args.index("--result") + 1]
        import_results(date, result_path, db, fallback)
        return gen_appendix(date, db, fallback)

    signals = load_signals(date, top_n)
    print(f"信号股 TOP{len(signals)}（{date}）")
    profiles, fetched, cached = build_profiles(signals, db, fallback)
    print(f"公司画像：新拉 {fetched} / 缓存 {cached}")
    pending = gen_pending(date, profiles, db, fallback)
    log = {"trade_date": date, "top_n": top_n, "companies": len(profiles),
           "fetched": fetched, "cached": cached, "pending": pending, "ts": datetime.now()}
    if db is not None:
        db.legal_checks.update_one({"trade_date": date}, {"$set": log}, upsert=True)
    print("下一步：打开待核清单 → 浏览器查执行网 → 填写结果 → "
          f"python scripts/legal_check.py --result output/legal_pending_{date}.md")


if __name__ == "__main__":
    main()
