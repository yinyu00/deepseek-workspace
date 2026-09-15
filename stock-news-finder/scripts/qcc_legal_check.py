#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""企查查 MCP 法人司法风险查询（P1 自动化，Windows 主机运行）。

链路：recommend TOP20 → F10 画像补全 → 15天缓存过滤 → 生成名单 CSV
      → tools/qcc-mcp-batch/qcc_mcp.py 精查 4 字段（工商信息/失信/被执行人/限高）
      → 结果解析 → 风险报告 + 回写 legal_risks（source: qcc-mcp）+ 更新缓存

积分账：4 字段 × 1 积分/tool = 4 积分/家；TOP20 = 80 积分/天 < 每日赠送 100。
token：tools/qcc-mcp-batch/config.json（gitignore，登录 agent.qcc.com 领取）。

用法：
  python scripts/qcc_legal_check.py                 # 全流程（今天）
  python scripts/qcc_legal_check.py --date 20260915 # 指定日期的推荐
  python scripts/qcc_legal_check.py --dry-run       # 只出待查清单不调用（无 token 自动进此模式）
"""
import csv
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # 复用 legal_check

QCC_DIR = os.path.join(BASE, "tools", "qcc-mcp-batch")
QCC_CFG = os.path.join(QCC_DIR, "config.json")
QCC_CSV = os.path.join(QCC_DIR, "qcc_search_list.csv")
QCC_OUT = os.path.join(QCC_DIR, "qcc_data_mcp", "json")
CACHE = os.path.join(BASE, "data", "qcc_check_cache.json")
OUT_DIR = os.path.join(BASE, "output")

FIELDS = ["工商信息", "失信", "被执行人", "限制高消费"]  # 4 积分/家
COST_PER = len(FIELDS)
TOP_N = 20
RECHECK_DAYS = 15

# 企查查返回 → legal_risks.risk_type（与 legal_check.py RISK_TYPES 对齐）
RISK_MAP = {"失信": "dishonest", "被执行人": "executed", "限制高消费": "limit_high"}


def have_token():
    if not os.path.exists(QCC_CFG):
        return False
    txt = open(QCC_CFG, encoding="utf-8").read()
    return "YOUR_TOKEN_HERE" not in txt


def load_cache():
    if os.path.exists(CACHE):
        try:
            return json.load(open(CACHE, encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_cache(c):
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False, indent=1)


def load_top_recommend(date8, top_n=TOP_N):
    path = os.path.join(OUT_DIR, f"recommend_{date8}.json")
    if not os.path.exists(path):
        sys.exit(f"[error] 不存在 {path}（先跑 recommend.py）")
    rec = json.load(open(path, encoding="utf-8"))
    rows = rec.get("recommended", [])[:top_n]
    return [{"code": r["code"], "name": r["name"], "r_score": r.get("r_score", 0),
             "tier": r.get("tier", "")} for r in rows]


def fresh_within(entry, days):
    if not entry or not entry.get("last_checked"):
        return False
    try:
        t = datetime.strptime(entry["last_checked"][:19], "%Y-%m-%d %H:%M:%S")
        return (datetime.now() - t) < timedelta(days=days)
    except Exception:
        return False


def build_targets(date8, db, fallback):
    """TOP20 → 15天内查过的剔除 → F10 画像补全（公司全称+USCC）。"""
    import legal_check
    cands = load_top_recommend(date8)
    cache = load_cache()
    todo, skipped = [], []
    for c in cands:
        if fresh_within(cache.get(c["code"]), RECHECK_DAYS):
            skipped.append(c)
            continue
        todo.append(c)
    # 画像：legal_companies 7 天缓存优先，否则 F10 现拉
    targets = []
    for c in todo:
        doc = legal_check.load_company(db, fallback, c["code"])
        fresh = False
        if doc and doc.get("updated_at"):
            try:
                fresh = (datetime.now() - datetime.strptime(doc["updated_at"][:19], "%Y-%m-%d %H:%M:%S")) < timedelta(days=7)
            except Exception:
                pass
        if not fresh:
            doc = legal_check.fetch_f10_profile(c["code"])
            if doc is None:
                print(f"[warn] {c['code']} 画像缺失，跳过")
                continue
            legal_check.upsert_company(db, fallback, doc)
        targets.append({**c, "company": doc.get("company") or c["name"],
                        "uscc": doc.get("uscc") or ""})
    return targets, skipped


def write_csv(targets):
    """qcc_search_list.csv（覆盖写）。返回 公司名→code 映射（文件名按公司名落盘）。"""
    with open(QCC_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["entity_name", "entity_type", "source", "uscc"])
        for t in targets:
            w.writerow([t["company"], "股票", t["code"], t["uscc"]])
    return {t["company"]: t for t in targets}


def run_qcc():
    cmd = [sys.executable, "qcc_mcp.py", "--fields", ",".join(FIELDS)]
    print(f"[run] {' '.join(cmd)}  (cwd={QCC_DIR})")
    # Windows 控制台 GBK：强制 UTF-8 输出避免乱码炸解码
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    p = subprocess.run(cmd, cwd=QCC_DIR, env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    print(p.stdout[-1500:] if p.stdout else "")
    if p.stderr:
        print("[stderr]", p.stderr[-500:], file=sys.stderr)
    return p.returncode == 0


def _pick(d, *keys):
    """防御性取值：企查查返回结构以真实数据为准，此处宽松提取。"""
    for k in keys:
        if isinstance(d, dict) and d.get(k):
            return d[k]
    return ""


def parse_results(name_map, db, fallback):
    """qcc_data_mcp/json/*.json → 风险判定 + legal_risks 回写 + 缓存更新。"""
    import legal_check
    cache = load_cache()
    report_rows = []
    for fname in sorted(os.listdir(QCC_OUT)) if os.path.isdir(QCC_OUT) else []:
        if not fname.endswith(".json"):
            continue
        try:
            d = json.load(open(os.path.join(QCC_OUT, fname), encoding="utf-8"))
        except Exception:
            continue
        t = name_map.get(d.get("entity_name") or fname[:-5])
        if not t:
            continue  # 非本批次（历史遗留文件）
        code = t["code"]
        data, no_match = d.get("data") or {}, d.get("no_match") or {}
        risks, legal_person = [], ""
        reg = data.get("工商信息") or {}
        if isinstance(reg, dict):
            legal_person = str(_pick(reg, "OperName", "法人", "法定代表人", "legal_person") or "")
        for field, rtype in RISK_MAP.items():
            payload = data.get(field)
            if payload is None or (isinstance(payload, dict) and payload.get("无匹配项")) or field in no_match:
                continue
            # 有数据即视为存在记录（明细结构上线后按真实字段精化）
            risks.append(rtype)
            doc = {"code": code, "person": legal_person, "risk_type": rtype,
                   "case_no": "", "amount": "", "filed_date": "",
                   "reason": f"企查查MCP:{field}有记录", "trade_date": datetime.now().strftime("%Y%m%d"),
                   "company": t["company"], "uscc": t.get("uscc", ""),
                   "source": "qcc-mcp", "status": "active",
                   "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
            try:
                legal_check.upsert_risk(db, fallback, doc)
            except Exception as e:
                print(f"[warn] 风险入库失败 {code}: {e}", file=sys.stderr)
        result = "risk" if risks else ("error" if d.get("errors") else "clean")
        cache[code] = {"last_checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                       "result": result, "legal_person": legal_person}
        report_rows.append({**t, "legal_person": legal_person, "risks": risks,
                            "result": result})
    save_cache(cache)
    return report_rows


def gen_report(date8, rows, targets, skipped):
    path = os.path.join(OUT_DIR, f"qcc_legal_{date8}.md")
    L = [f"# 企查查法人司法风险报告 {date8}", "",
         f"> 生成 {datetime.now():%Y-%m-%d %H:%M} | 查询 {len(rows)}/{len(targets)} 家"
         f"（{COST_PER} 积分/家，共 {len(rows) * COST_PER} 积分）| 15天内已查跳过 {len(skipped)} 家",
         "",
         "| 公司 | 代码 | 推荐档 | 法人 | 失信 | 被执行 | 限高 | 判定 |",
         "|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda x: (x["result"] != "risk", -x.get("r_score", 0))):
        rs = [k for k, v in RISK_MAP.items() if v in r["risks"]]
        mark = {k: "⚠️" for k in rs}
        verdict = {"risk": "🔴 有风险", "clean": "🟢 干净", "error": "⚪ 查询失败"}.get(r["result"], r["result"])
        L.append(f"| {r['company']} | {r['code']} | {r['tier']} | {r['legal_person'] or '—'} | "
                 f"{mark.get('失信', '')} | {mark.get('被执行人', '')} | {mark.get('限制高消费', '')} | {verdict} |")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print(f"→ {path}")
    return path


def main():
    args = sys.argv[1:]
    dry = "--dry-run" in args
    date = args[args.index("--date") + 1] if "--date" in args else datetime.now().strftime("%Y%m%d")

    import legal_check
    db, fallback = legal_check.get_db()
    targets, skipped = build_targets(date, db, fallback)
    print(f"TOP{TOP_N} 推荐：待查 {len(targets)} 家（{len(targets) * COST_PER} 积分），"
          f"15天内已查 {len(skipped)} 家，画像齐全 {sum(1 for t in targets if t['uscc'])} 家")
    if not targets:
        print("[done] 全部 15 天内已查过，无需消耗积分")
        return

    if dry or not have_token():
        if not dry:
            print("[dry-run] 未配置 token（tools/qcc-mcp-batch/config.json），仅生成待查清单")
        name_map = write_csv(targets)
        print(f"→ 待查清单已写入 {QCC_CSV}")
        for t in targets:
            print(f"  {t['code']} {t['company']} uscc={t['uscc'] or '—'}")
        return

    # 清空本批次输出目录（防止旧文件误匹配）+ 备份断点进度
    prog = os.path.join(QCC_DIR, "qcc_data_mcp", "_progress.json")
    if os.path.exists(prog):
        os.rename(prog, prog + f".bak{datetime.now():%H%M%S}")
    os.makedirs(QCC_OUT, exist_ok=True)
    for f in os.listdir(QCC_OUT):
        os.remove(os.path.join(QCC_OUT, f))

    name_map = write_csv(targets)
    if not run_qcc():
        print("[warn] qcc_mcp.py 运行异常（积分不足/网络），可重跑续传", file=sys.stderr)
    rows = parse_results(name_map, db, fallback)
    n_risk = sum(1 for r in rows if r["result"] == "risk")
    print(f"查询完成：{len(rows)} 家，其中风险 {n_risk} 家")
    gen_report(date, rows, targets, skipped)


if __name__ == "__main__":
    main()
