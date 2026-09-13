#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""东财资讯全文搜索采集器（宏观/地缘关键词定向抓取）。

读 data/macro_keywords.txt：[search] 主词逐个调搜索接口（每词前 N 条），
[expand] 分组扩展词给结果打主题标签（tag 字段，如 "制裁/关税"）。
新闻接口：search-api-web.eastmoney.com（jsonp，cb 剥壳）。
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KW_FILE = os.path.join(BASE, "data", "macro_keywords.txt")
SEARCH_API = "https://search-api-web.eastmoney.com/search/jsonp?cb=cb&param="
HEADERS_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"


def load_keywords():
    search_words, expand_groups = [], {}
    section = None
    with open(KW_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line == "[search]":
                section = "s"; continue
            if line == "[expand]":
                section = "e"; continue
            if section == "s":
                search_words.append(line)
            elif section == "e" and ":" in line:
                grp, words = line.split(":", 1)
                expand_groups[grp.strip()] = [w.strip() for w in words.split(",") if w.strip()]
    return search_words, expand_groups


def _search_one(keyword, page_size=8):
    param = json.dumps({
        "uid": "", "keyword": keyword, "type": ["cmsArticleWebOld"],
        "client": "web", "clientType": "web", "clientVersion": "curr",
        "param": {"cmsArticleWebOld": {
            "searchScope": "default", "sort": "default",
            "pageIndex": 1, "pageSize": page_size,
            "preTag": "<em>", "postTag": "</em>"}},
    }, ensure_ascii=False)
    url = SEARCH_API + urllib.parse.quote(param)
    s = _http_get(url)
    if not s.startswith("cb("):
        return []
    try:
        d = json.loads(s[3:s.rfind(")")])
    except json.JSONDecodeError:
        return []
    return (d.get("result") or {}).get("cmsArticleWebOld") or []


def _http_get(url):
    """curl 子进程优先（Mac/D5 决策）；失败（Windows schannel TLS 拦截）降级 urllib+SSL。"""
    r = subprocess.run(["curl", "-s", "-m", "15", "-A", HEADERS_UA,
                        "-H", "Referer: https://so.eastmoney.com/", url],
                       capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    import ssl
    req = urllib.request.Request(url, headers={
        "User-Agent": HEADERS_UA, "Referer": "https://so.eastmoney.com/"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode("utf-8", "ignore").strip()
    except ssl.SSLError:
        pass
    except urllib.error.URLError as e:
        if not isinstance(getattr(e, "reason", None), ssl.SSLError):
            raise
    ctx = ssl._create_unverified_context()
    ctx.set_ciphers("DEFAULT@SECLEVEL=1")
    with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
        return resp.read().decode("utf-8", "ignore").strip()


def _tag(text, expand_groups):
    tags = [g for g, words in expand_groups.items() if any(w in text for w in words)]
    return "/".join(tags[:3])


def _clean(s):
    return (s or "").replace("<em>", "").replace("</em>", "").strip()


def fetch(cfg):
    search_words, expand_groups = load_keywords()
    per_word = int(cfg.get("per_word", 8))
    items, seen = [], set()
    for kw in search_words:
        try:
            rows = _search_one(kw, per_word)
        except Exception as e:
            print(f"[warn] 搜索「{kw}」失败: {e}", file=sys.stderr)
            continue
        for r in rows:
            title = _clean(r.get("title"))
            body = _clean(r.get("content"))
            url = str(r.get("url") or "")
            key = url or title
            if not title or key in seen:
                continue
            # 严格过滤：东财搜索是模糊匹配且正文长文常擦边命中，
            # 要求搜索词或扩展词真实出现在【标题】里（宏观事件标题必然含主题词）
            all_words = [kw] + [w for words in expand_groups.values() for w in words]
            if not any(w in title for w in all_words):
                continue
            seen.add(key)
            items.append({
                "title": title,
                "body": body,
                "time": str(r.get("date") or ""),
                "source": "eastmoney-search",
                "url": url,
                "stocks": [],
                "tag": _tag(title + " " + body, expand_groups) or kw,  # 无扩展词命中时用搜索词兜底
                "media": _clean(r.get("mediaName")),
            })
    return items


def selftest():
    rows = _search_one("制裁", 3)
    if not rows:
        return False
    r = rows[0]
    return bool(_clean(r.get("title")) and r.get("date") and r.get("url"))


if __name__ == "__main__":
    for n in fetch({"per_word": 8})[:5]:
        print(f"[{n['tag']}] {n['time']} {n['title']} ({n['media']})")
