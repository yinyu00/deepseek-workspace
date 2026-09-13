#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知乎关注人「想法」采集器插件（type: zhihu-pins）。

接口：https://www.zhihu.com/api/v4/members/{url_token}/pins?offset=&limit=（匿名可用）。
说明：
- 知乎已把「关注流动态/回答/文章」藏到登录后（匿名返回空数据或 401），
  但单个用户的「想法 pins」接口仍匿名开放——本插件即走此通道。
- 关注人清单文本化维护：data/zhihu_people.txt，一行一人：
    url_token [显示名]      # 显示名可省略；# 开头为注释
  url_token = 知乎个人主页 zhihu.com/people/<url_token> 的最后一段。
- 正文为 content 块列表中的 text 块拼接（<br> 转换行）。
- 本机（公司 TLS 拦截）需 SSL 降级重试：先常规请求，SSL 失败后降级重试。
"""
import json
import os
import re
import sys
import time
import urllib.request
import ssl

SOURCE = "zhihu-pins"
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Referer": "https://www.zhihu.com/",
}
MAX_PEOPLE = 50          # 关注人数安全上限
MAX_PAGES_PER_PERSON = 3 # 每人翻页安全上限


def _get_json(url, timeout=15):
    """GET → JSON；SSL 失败（公司 TLS 拦截）自动降级重试一次。"""
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "ignore"))
    except ssl.SSLError:
        pass
    except urllib.error.URLError as e:
        if not isinstance(getattr(e, "reason", None), ssl.SSLError):
            raise
    ctx = ssl._create_unverified_context()
    ctx.set_ciphers("DEFAULT@SECLEVEL=1")
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def _fmt_time(ts):
    try:
        ts = int(float(str(ts)))
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
    except (ValueError, TypeError):
        return ""


def _pin_text(pin):
    """content 块列表 → 纯文本（text 块拼接，<br> 转换行）。"""
    parts = []
    for b in pin.get("content") or []:
        if isinstance(b, dict) and b.get("type") == "text":
            t = str(b.get("content") or "")
            t = t.replace("<br>", "\n").replace("<br/>", "\n")
            t = re.sub(r"<[^>]+>", "", t)
            parts.append(t.strip())
    return "\n".join(p for p in parts if p).strip()


def _load_people(cfg):
    """读关注人清单：cfg['people_file'] 或 data/zhihu_people.txt → [(token, name)]。"""
    path = cfg.get("people_file") or os.path.join(BASE, "data", "zhihu_people.txt")
    people = []
    if not os.path.exists(path):
        print(f"[warn] 关注人清单不存在: {path}（空跑）", file=sys.stderr)
        return people
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            seg = line.split()
            token = seg[0]
            name = seg[1] if len(seg) > 1 else token
            people.append((token, name))
    return people[:MAX_PEOPLE]


def fetch(cfg):
    limit = int(cfg.get("limit", 20))
    stop_date = cfg.get("_stop_date") or None  # "YYYY-MM-DD"：该日 00:00 前的不收
    people = _load_people(cfg)
    items = []
    for i, (token, name) in enumerate(people):
        for page in range(MAX_PAGES_PER_PERSON):
            url = (f"https://www.zhihu.com/api/v4/members/{token}/pins"
                   f"?offset={page * limit}&limit={limit}")
            try:
                data = _get_json(url)
            except Exception as e:
                print(f"[warn] 知乎 {name}({token}) 第{page + 1}页失败: {e}", file=sys.stderr)
                break
            rows = data.get("data") or []
            if not rows:
                break
            stop = False
            for p in rows:
                tm = _fmt_time(p.get("created"))
                if stop_date and tm[:10] < stop_date:
                    stop = True
                    break
                body = _pin_text(p)
                if not body:  # 纯图/转发无文本，跳过
                    continue
                pid = str(p.get("id") or "")
                items.append({
                    "title": body[:40],
                    "body": f"【{name}·知乎想法】\n{body}",
                    "time": tm,
                    "source": SOURCE,
                    "url": f"https://www.zhihu.com/pin/{pid}" if pid else "",
                    "stocks": [],
                })
            paging = data.get("paging") or {}
            if stop or paging.get("is_end") or len(rows) < limit:
                break
        if i < len(people) - 1:
            time.sleep(0.5)  # 温和限速
    return items


def selftest():
    """真实抓样本用户 1 页，校验字段格式（不依赖清单文件是否已配）。"""
    try:
        items = _fetch_with_people([("zhang-jia-wei", "张佳玮")], limit=5)
    except Exception as e:
        print(f"[warn] selftest 网络失败: {e}", file=sys.stderr)
        return False
    if not items:
        print("[warn] selftest: 未抓到数据", file=sys.stderr)
        return False
    pat = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
    for n in items:
        if set(n) != {"title", "body", "time", "source", "url", "stocks"}:
            print(f"[warn] selftest: 字段不齐 {sorted(n)}", file=sys.stderr)
            return False
        if n["source"] != SOURCE or n["stocks"] != []:
            print("[warn] selftest: source/stocks 不符", file=sys.stderr)
            return False
        if not pat.match(n["time"]):
            print(f"[warn] selftest: time 格式错误 {n['time']!r}", file=sys.stderr)
            return False
    print(f"[ok] selftest: {len(items)} 条校验通过")
    return True


def _fetch_with_people(people, limit=5):
    """selftest 专用：跳过清单文件，直接抓指定用户。"""
    items = []
    for token, name in people:
        url = f"https://www.zhihu.com/api/v4/members/{token}/pins?offset=0&limit={limit}"
        try:
            data = _get_json(url)
        except Exception as e:
            print(f"[warn] selftest 请求失败: {e}", file=sys.stderr)
            return []
        for p in data.get("data") or []:
            body = _pin_text(p)
            if not body:
                continue
            tm = _fmt_time(p.get("created"))
            items.append({
                "title": body[:40], "body": body, "time": tm,
                "source": SOURCE,
                "url": f"https://www.zhihu.com/pin/{p.get('id', '')}",
                "stocks": [],
            })
    return items


if __name__ == "__main__":
    print(selftest())
