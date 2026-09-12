#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导入 Excel 公司清单 → data/companies.txt（手动词典格式）。

策略：Excel 作为底座全量导入；已存在于 companies.txt 的股票，
保留其手写别名（手动优先）。生成前备份旧文件。

用法：PYTHONPATH=../pylibs 或 ./pylibs 已包含 xlrd
    python3 import_excel.py data/GPLIST.xls
"""
import os
import shutil
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根 = scripts/ 上一级
sys.path.insert(0, os.path.join(BASE, "pylibs"))
import xlrd  # noqa: E402

TXT = os.path.join(BASE, "data", "companies.txt")


def load_existing():
    """读现有 companies.txt：code -> (name, [aliases])，只保留非注释有效行。"""
    entries = {}
    if not os.path.exists(TXT):
        return entries, []
    comments = []
    with open(TXT, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                comments.append(line)
                continue
            parts = line.split()
            if len(parts) >= 2 and len(parts[0]) == 6 and parts[0].isdigit():
                aliases = [a for a in "".join(parts[2:]).split(",") if a]
                entries[parts[0]] = (parts[1], aliases)
    return entries, comments


def main(xls_path):
    entries, comments = load_existing()
    manual_count = len(entries)

    wb = xlrd.open_workbook(xls_path)
    sh = wb.sheet_by_index(0)
    hdr = [str(sh.cell_value(0, c)).strip() for c in range(sh.ncols)]
    ci = {name: hdr.index(name) for name in ("A股代码", "证券简称", "扩位证券简称")}

    imported, skipped = 0, 0
    for r in range(1, sh.nrows):
        code = str(sh.cell_value(r, ci["A股代码"])).strip().zfill(6)
        name = str(sh.cell_value(r, ci["证券简称"])).strip()
        ext = str(sh.cell_value(r, ci["扩位证券简称"])).strip()
        if not (len(code) == 6 and code.isdigit() and name) or name.lstrip("*").startswith(("退", "ST")):
            skipped += 1
            continue
        aliases = [ext] if ext and ext != name else []
        if code in entries:
            # 手动已有：保留名称与别名，补充扩位简称
            old_name, old_alias = entries[code]
            if ext and ext != old_name and ext not in old_alias:
                old_alias.append(ext)
            entries[code] = (old_name, old_alias)
        else:
            entries[code] = (name, aliases)
        imported += 1

    if os.path.exists(TXT):
        shutil.copy(TXT, TXT + ".bak")

    lines = [
        "# 公司/股票词典 —— 由 import_excel.py 生成，可继续手动增删",
        "# 格式：股票代码 股票名 别名1,别名2,...（# 开头为注释）",
        f"# 最近导入：{xls_path}（导入 {imported} 行，跳过 {skipped} 行，手动保留 {manual_count} 只的别名）",
    ] + comments[:0]  # 原注释已含在头部说明中，不重复
    for code in sorted(entries):
        name, aliases = entries[code]
        lines.append(" ".join([code, name, ",".join(aliases)]) if aliases else f"{code} {name}")

    with open(TXT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"导入 {imported} 行，跳过 {skipped} 行（退市/ST/无效），合计 {len(entries)} 只 → {TXT}")
    print(f"旧文件备份: {TXT}.bak")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, "data", "GPLIST.xls")
    main(path)
