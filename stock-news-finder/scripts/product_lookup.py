#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""产品 → 板块 → 成分股 解析工具（东财两步接口）。

第1步 suggest 接口查产品词的板块代码（Classify == "BK"）
第2步 clist 接口拉板块全部成分股
结果缓存到 data/board_cache.json（当日有效），避免每次运行重复请求。

用法：
    python3 product_lookup.py 固态电池        # 解析并列出成分股
"""
import json
import os
import sys
import urllib.request
import urllib.parse
from datetime import date

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根 = scripts/ 上一级
CACHE = os.path.join(BASE, "data", "board_cache.json")
SUGGEST = ("https://searchapi.eastmoney.com/api/suggest/get"
           "?input={input}&type=14&token=D43BF722C8E33BDC906FB84D85E326E8&count=8")
CLIST = "/api/qt/clist/get?pz=100&po=1&np=1&fltt=2&invt=2&fid=f3&fs=b:{bk}&fields=f12,f14&pn={pn}"
# push2 是 CDN 集群，个别节点瞬断：http 优先 + 多节点轮询
CLIST_HOSTS = ["http://80.push2.eastmoney.com", "http://90.push2.eastmoney.com",
               "https://80.push2.eastmoney.com", "https://90.push2.eastmoney.com"]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Referer": "https://www.eastmoney.com/",
}


def _get_json(path_or_url, timeout=12, retries=3):
    """path（走 CLIST_HOSTS 轮询）或完整 URL → JSON。

    push2 CDN 对本机网络路径不稳定（urllib 直连常被瞬断），
    用 curl 子进程 + 代理/直连/多节点全排列重试，实测最稳。
    """
    import subprocess
    import time
    if path_or_url.startswith("http"):
        urls = [path_or_url]
    else:
        urls = [h + path_or_url for h in CLIST_HOSTS]
    variants = []  # (url, noproxy)
    for u in urls:
        variants.append((u, True))   # 直连
        variants.append((u, False))  # 走系统代理
    last = None
    for attempt in range(retries):
        for u, np_ in variants:
            try:
                cmd = ["curl", "-s", "-m", str(timeout), "-A", "Mozilla/5.0", u]
                if np_:
                    cmd[2:2] = ["--noproxy", "*"]
                r = subprocess.run(cmd, capture_output=True, timeout=timeout + 5)
                if r.stdout.strip().startswith(b"{"):
                    return json.loads(r.stdout.decode("utf-8", "ignore"))
                last = RuntimeError(f"empty response: {r.stdout[:50]!r}")
            except Exception as e:
                last = e
        time.sleep(1)
    raise last


def find_board(word):
    """产品词 → 板块代码（Classify=="BK"），找不到返回 None。"""
    data = _get_json(SUGGEST.format(input=urllib.parse.quote(word)))
    for it in (data.get("QuotationCodeTable") or {}).get("Data") or []:
        if it and it.get("Classify") == "BK" and it.get("Name"):
            # 名称需与产品词相近（包含关系），避免"电池"误配到无关板块
            if word in it["Name"] or it["Name"] in word:
                return it["Code"], it["Name"]
    return None


def board_stocks(bk_code):
    """板块代码 → [(code, name), ...] 全部成分股（分页拉全，单页上限100）。"""
    stocks, page = [], 1
    while page <= 10:
        data = _get_json(CLIST.format(bk=bk_code, pn=page))
        d = data.get("data") or {}
        diff = d.get("diff") or []
        if not diff:
            break
        for x in diff:
            stocks.append((str(x.get("f12", "")), str(x.get("f14", ""))))
        if len(stocks) >= d.get("total", 0):
            break
        page += 1
    return stocks


def resolve(word, use_cache=True):
    """产品词 → 成分股列表（带当日缓存）。返回 (board_name, [(code,name)...]) 或 None。"""
    cache = {}
    today = str(date.today())
    if use_cache and os.path.exists(CACHE):
        try:
            cache = json.load(open(CACHE, encoding="utf-8"))
        except Exception:
            cache = {}
    ent = cache.get(word)
    if ent and ent.get("date") == today:
        return ent["board"], [tuple(s) for s in ent["stocks"]]

    bk = find_board(word)
    if not bk:
        return None
    stocks = board_stocks(bk[0])
    cache[word] = {"date": today, "board": bk[1], "stocks": stocks}
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)
    return bk[1], stocks


if __name__ == "__main__":
    for w in sys.argv[1:]:
        r = resolve(w)
        if not r:
            print(f"✗ {w}: 未找到对应板块")
            continue
        board, stocks = r
        print(f"✓ {w} → 板块[{board}] {len(stocks)} 只: {'、'.join(n for _, n in stocks[:8])}...")
