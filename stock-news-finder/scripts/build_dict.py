#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""关联层词典构建：
- 基础：data/companies.txt（手动维护，热插拔）
- 可选：--ak 参数且本机装了 akshare 时，合并全市场股票列表作为兜底词典
输出 data/stock_dict.json：[{code, name, aliases:[...]}]
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根 = scripts/ 上一级
TXT = os.path.join(BASE, "data", "companies.txt")
OUT = os.path.join(BASE, "data", "stock_dict.json")


def load_manual():
    entries = {}
    if not os.path.exists(TXT):
        return entries
    with open(TXT, encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 2 or len(parts[0]) != 6 or not parts[0].isdigit():
                print(f"[warn] 第{ln}行格式不符（应为：代码 名称 别名,...）: {line}", file=sys.stderr)
                continue
            code, name = parts[0], parts[1]
            if name.lstrip("*").startswith(("退", "ST")):
                continue  # 过滤退市/ST 风险股
            aliases = [a for a in "".join(parts[2:]).split(",") if a]
            entries[code] = {"code": code, "name": name, "aliases": aliases, "origin": "manual"}
    return entries


def load_akshare():
    try:
        import akshare as ak  # noqa
    except ImportError:
        return {}
    entries = {}
    for board, col in [("stock_zh_a_spot_em", None)]:
        try:
            df = getattr(ak, board)()
            for _, r in df.iterrows():
                code = str(r["代码"]).zfill(6)
                entries[code] = {"code": code, "name": str(r["名称"]), "aliases": [], "origin": "akshare"}
        except Exception as e:
            print(f"[warn] akshare 拉取失败: {e}", file=sys.stderr)
    return entries


def main():
    use_ak = "--ak" in sys.argv
    manual = load_manual()
    print(f"手动词典: {len(manual)} 只")
    merged = dict(manual)
    if use_ak:
        akd = load_akshare()
        # 手动维护的条目优先（别名保留）
        for c, e in akd.items():
            merged.setdefault(c, e)
        print(f"akshare 兜底合并后: {len(merged)} 只")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(list(merged.values()), f, ensure_ascii=False, indent=1)
    print(f"→ {OUT}")


if __name__ == "__main__":
    main()
