#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公司名/简称 → 股票代码 查询工具（东方财富搜索联想接口）。

用法：
    python3 lookup.py 立讯精密          # 单个查询
    python3 lookup.py 立讯精密 万华化学  # 批量查询
    python3 lookup.py --add 立讯精密     # 查询并追加到 companies.txt

注意：结果过滤 Classify == "AStock"，排除港股/美股同名标的。
"""
import json
import os
import sys
import urllib.request
import urllib.parse

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根 = scripts/ 上一级
TXT = os.path.join(BASE, "data", "companies.txt")
API = ("https://searchapi.eastmoney.com/api/suggest/get"
       "?input={input}&type=14&token=D43BF722C8E33BDC906FB84D85E326E8&count=5")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Referer": "https://www.eastmoney.com/",
}


def suggest(name):
    """返回 A 股候选列表：[{code, name, market}]"""
    url = API.format(input=urllib.parse.quote(name))
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read().decode("utf-8", "ignore"))
    items = []
    for it in (data.get("QuotationCodeTable") or {}).get("Data") or []:
        if not it:
            continue
        # 关键过滤：只要 A 股（排除港股/美股/基金/债券等同名标的）
        if it.get("Classify") != "AStock":
            continue
        code = str(it.get("Code", ""))
        if not (len(code) == 6 and code.isdigit()):
            continue
        items.append({
            "code": code,
            "name": it.get("Name", ""),
            "market": it.get("SecurityTypeName", ""),  # 沪A/深A/北A
        })
    return items


def load_existing_codes():
    codes = set()
    if os.path.exists(TXT):
        with open(TXT, encoding="utf-8") as f:
            for line in f:
                p = line.split()
                if len(p) >= 2 and len(p[0]) == 6 and p[0].isdigit() and not line.startswith("#"):
                    codes.add(p[0])
    return codes


def main():
    args = sys.argv[1:]
    do_add = "--add" in args
    names = [a for a in args if not a.startswith("--")]
    if not names:
        print(__doc__)
        return
    existing = load_existing_codes()
    to_append = []
    for name in names:
        items = suggest(name)
        if not items:
            print(f"✗ {name}: 无A股结果")
            continue
        # 第一个结果为最匹配；多个候选全部展示供人工确认
        top = items[0]
        more = f"（其余候选: {', '.join(i['name'] + '(' + i['market'] + ')' for i in items[1:3])}）" if len(items) > 1 else ""
        flag = "" if top["code"] not in existing else " [已在词典]"
        print(f"✓ {name} → {top['code']} {top['name']} ({top['market']}){flag}{more}")
        if do_add and top["code"] not in existing:
            to_append.append(f"{top['code']} {top['name']}")
            existing.add(top["code"])
    if to_append:
        with open(TXT, "a", encoding="utf-8") as f:
            f.write("\n" + "\n".join(to_append) + "\n")
        print(f"\n已追加 {len(to_append)} 只到 companies.txt（下次运行自动生效）")


if __name__ == "__main__":
    main()
