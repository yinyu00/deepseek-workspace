#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""深市词典导入：东财 datacenter F10 机构信息接口 → data/companies.txt 合并。

只导 .SZ 且 000/001/002/300/301 开头的 A 股（排除 B 股 200、退市整理等），
ST/退市过滤与 import_excel.py 一致。已有代码保留（含手写别名）。

用法：python3 import_sz.py [--dry]
"""
import json
import os
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根 = scripts/ 上一级
TXT = os.path.join(BASE, "data", "companies.txt")
API = ("https://datacenter-web.eastmoney.com/api/data/v1/get"
       "?reportName=RPT_F10_BASIC_ORGINFO&columns=SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR"
       "&pageSize=500&pageNumber={page}&sortColumns=SECURITY_CODE&sortTypes=1")
# 注：filter 参数各种 like 语法均被拒，改为全量拉取后本地过滤（SECUCODE .SZ + A股前缀）

SZ_PREFIX = ("000", "001", "002", "300", "301")


def get_page(page):
    for attempt in range(3):
        r = subprocess.run(["curl", "-s", "-m", "20", "-A", "Mozilla/5.0", API.format(page=page)],
                           capture_output=True, text=True)
        if r.stdout.strip().startswith("{"):
            d = json.loads(r.stdout)
            res = d.get("result") or {}
            return res.get("data") or [], res.get("pages") or 0
        time.sleep(1 + attempt)
    return [], 0


def load_existing():
    entries = {}
    if not os.path.exists(TXT):
        return entries
    with open(TXT, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            p = line.split()
            if len(p) >= 2 and len(p[0]) == 6 and p[0].isdigit():
                aliases = [a for a in "".join(p[2:]).split(",") if a]
                entries[p[0]] = (p[1], aliases)
    return entries


def main():
    dry = "--dry" in sys.argv
    entries = load_existing()
    before = len(entries)

    imported, skipped = 0, 0
    page = 1
    pages = 1
    while page <= pages:
        rows, pages = get_page(page)
        if not rows:
            break
        for r in rows:
            secucode = str(r.get("SECUCODE") or "")
            code = str(r.get("SECURITY_CODE") or "")
            name = str(r.get("SECURITY_NAME_ABBR") or "").strip()
            if not secucode.endswith(".SZ"):
                continue  # 只收深市
            if not code.startswith(SZ_PREFIX) or not name:
                skipped += 1
                continue
            if name.lstrip("*").startswith(("退", "ST")):
                skipped += 1
                continue
            if code in entries:
                continue
            entries[code] = (name, [])
            imported += 1
        page += 1
        if page % 10 == 0:
            print(f"  ... 第{page}/{pages}页, 累计新增 {imported}")

    print(f"深市候选新增 {imported} 只，跳过 {skipped} 只（B股/退市/ST/非A股前缀），原词典 {before} 只")
    if dry:
        print("[dry] 未写入")
        return

    import shutil
    shutil.copy(TXT, TXT + ".bak2")
    lines = ["# 公司/股票词典（沪市 GPLIST.xls + 深市 import_sz.py 导入，别名手动维护）"]
    for code in sorted(entries):
        name, aliases = entries[code]
        lines.append(" ".join([code, name, ",".join(aliases)]) if aliases else f"{code} {name}")
    with open(TXT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"合计 {len(entries)} 只 → {TXT}（备份 .bak2）")


if __name__ == "__main__":
    main()
