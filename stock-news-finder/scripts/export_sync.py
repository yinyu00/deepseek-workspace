#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导出打包 + FTP 上传（Mac 侧，DB 同步第 1 跳）。

把当日全部产物打包成 JSONL 到 sync/<yyyymmdd>/，再按 data/ftp.json 上传。
幂等可重跑；FTP 未配置时只打包不上传。

用法：
    python3 scripts/export_sync.py              # 今天
    python3 scripts/export_sync.py 20260826     # 指定日期
"""
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FTP_CFG = os.path.join(BASE, "data", "ftp.json")


def jsonl(rows):
    return "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n"


def md5(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def package(date):
    d8 = date.replace("-", "")
    sync_dir = os.path.join(BASE, "sync", d8)
    os.makedirs(sync_dir, exist_ok=True)
    counts = {}

    # 1) news：raw/<d8>.json
    raw = os.path.join(BASE, "raw", d8 + ".json")
    if os.path.exists(raw):
        rows = []
        for n in json.load(open(raw, encoding="utf-8")):
            t = (n.get("time") or "")[:10]
            rows.append({
                "news_id": None,  # 东财 url 里有 id，此处不强解析；用 title_hash 兜底
                "title": n["title"], "title_hash": md5(n["title"].strip()),
                "body": n.get("body", ""), "time": n.get("time", ""),
                "trade_date": t or None,
                "source": n.get("source", ""), "source_name": n.get("source", ""),
                "url": n.get("url", ""), "stocks": n.get("stocks", []),
                "tag": n.get("tag", ""), "media": n.get("media", ""),
            })
        open(os.path.join(sync_dir, "news.jsonl"), "w", encoding="utf-8").write(jsonl(rows))
        counts["news"] = len(rows)

    # 2) signals：output/signals_<d8>.json
    sig = os.path.join(BASE, "output", "signals_" + d8 + ".json")
    if os.path.exists(sig):
        rows = json.load(open(sig, encoding="utf-8"))
        open(os.path.join(sync_dir, "signals.jsonl"), "w", encoding="utf-8").write(jsonl(rows))
        counts["signals"] = len(rows)

    # 3) llm_events：output/llm_events.json（当日运行产物）
    llm = os.path.join(BASE, "output", "llm_events.json")
    if os.path.exists(llm):
        rows = [{"trade_date": date, **r} for r in json.load(open(llm, encoding="utf-8"))]
        open(os.path.join(sync_dir, "llm_events.jsonl"), "w", encoding="utf-8").write(jsonl(rows))
        counts["llm_events"] = len(rows)

    # 4) stocks：data/stock_dict.json
    sd = os.path.join(BASE, "data", "stock_dict.json")
    if os.path.exists(sd):
        rows = [{"origin": "dict", **r} for r in json.load(open(sd, encoding="utf-8"))]
        open(os.path.join(sync_dir, "stocks.jsonl"), "w", encoding="utf-8").write(jsonl(rows))
        counts["stocks"] = len(rows)

    # 5) boards：data/board_cache.json（标记当日版本）
    bc = os.path.join(BASE, "data", "board_cache.json")
    if os.path.exists(bc):
        cache = json.load(open(bc, encoding="utf-8"))
        rows = []
        for word, ent in cache.items():
            if not ent or ent.get("date") != date:  # 只导当日解析的成分版本
                continue
            rows.append({"word": word, "board_code": None, "board_name": ent.get("board"),
                         "date": date, "constituents": ent.get("stocks", []),
                         "count": len(ent.get("stocks", []))})
        open(os.path.join(sync_dir, "boards.jsonl"), "w", encoding="utf-8").write(jsonl(rows))
        counts["boards"] = len(rows)

    manifest = {"date": date, "counts": counts,
                "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "host": os.uname().nodename}
    open(os.path.join(sync_dir, "manifest.json"), "w", encoding="utf-8").write(
        json.dumps(manifest, ensure_ascii=False, indent=1))
    print(f"打包完成 → sync/{d8}/: {counts}")
    return sync_dir, manifest


def ftp_upload(sync_dir, date):
    if not os.path.exists(FTP_CFG):
        print("[skip] data/ftp.json 未配置，跳过上传（包已就绪）")
        return
    cfg = json.load(open(FTP_CFG, encoding="utf-8"))
    if not cfg.get("url"):
        print("[skip] ftp.json url 为空，跳过上传")
        return
    remote_dir = cfg.get("remote_dir", "stock-sync").strip("/") + "/" + date.replace("-", "")
    user = f"{cfg.get('user','')}:{cfg.get('pass','')}"
    files = [f for f in os.listdir(sync_dir) if f.endswith((".jsonl", ".json"))]
    ok = 0
    for fn in sorted(files):
        r = subprocess.run(
            ["curl", "-sS", "-T", os.path.join(sync_dir, fn),
             "--ftp-create-dirs", "-u", user, f"{cfg['url'].rstrip('/')}/{remote_dir}/{fn}"],
            capture_output=True, text=True, timeout=120)
        if r.returncode == 0:
            ok += 1
        else:
            print(f"[warn] 上传失败 {fn}: {r.stderr[:120]}", file=sys.stderr)
    print(f"FTP 上传 {ok}/{len(files)} 个文件 → {cfg['url']}/{remote_dir}")


def main():
    date = next((a for a in sys.argv[1:] if a.isdigit() and len(a) == 8), None)
    if not date:
        date = datetime.now().strftime("%Y%m%d")
    date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    sync_dir, manifest = package(date)
    ftp_upload(sync_dir, date)


if __name__ == "__main__":
    main()
