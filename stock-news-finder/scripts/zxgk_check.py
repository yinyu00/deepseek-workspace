#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""执行网失信名单查询（P1 方案 A 全自动，Windows 运行）。

链路：playwright 真浏览器（过瑞数）→ 滑块验证码（GLM-4v-flash 识别缺口
+ 拟人轨迹拖拽）→ network 拦截 searchSX 响应 → 会话复用批量查询 → 入库。

三层防护应对（抓包还原，见设计 2.10.1）：
  瑞数 cookie/URL 令牌 → 真浏览器 JS 自动生成
  滑块行为校验(trackList) → GLM 识别缺口 x + 拟人轨迹（先快后慢+抖动）
  pCode 通行码 → 一次验证后绑定会话，批量查询复用

用法：
  python scripts/zxgk_check.py                      # 今日推荐 TOP20 法人
  python scripts/zxgk_check.py --names 张三,李四     # 指定名单
  python scripts/zxgk_check.py --one 恒大            # 单查（调试）
"""
import base64
import json
import os
import random
import sys
import time
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "scripts"))

SHIXIN_URL = "https://zxgk.court.gov.cn/shixin/"
CACHE = os.path.join(BASE, "data", "zxgk_check_cache.json")
RECHECK_DAYS = 15
MAX_SLIDE_RETRY = 3
SLEEP_BETWEEN = 3   # 查询间隔（秒），防频控


# ---------------- GLM 缺口识别 ----------------

def glm_find_gap(bg_b64, tpl_b64=None):
    """GLM-4v-flash 识别滑块缺口位置（单图模式）。

    ⚠️ 双图并发会触发 400（16K 上下文限制，glm4v-image-compress skill 记录的坑），
    只发背景图——缺口轮廓在背景上本就可见。返回缺口最左边缘 x 像素，失败 None。
    """
    from llm_classify import get_key, call_llm, parse_json_loose
    key = get_key()
    if not key:
        print("[warn] 无 GLM key，无法识别缺口")
        return None
    import urllib.request
    body = json.dumps({
        "model": "glm-4v-flash",
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{bg_b64}"}},
            {"type": "text", "text":
                "这是滑块验证码背景图（宽360像素），图中有一个人字形/几何形状的缺口。"
                "请定位缺口的最左边缘位置，"
                '输出 JSON：{"gap_x": <整数像素>}。只输出 JSON。'},
        ]}],
        "temperature": 0.1,
    }).encode()
    req = urllib.request.Request(
        "https://open.bigmodel.cn/api/paas/v4/chat/completions", data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        import ssl
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode())
        except Exception:
            ctx = ssl._create_unverified_context()
            with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
                data = json.loads(r.read().decode())
        txt = data["choices"][0]["message"]["content"]
        m = parse_json_loose(txt) or []
        if m and isinstance(m[0], dict) and isinstance(m[0].get("gap_x"), (int, float)):
            return int(m[0]["gap_x"])
        # 宽松兜底：正文里的数字
        import re
        mm = re.search(r"(\d{2,3})\s*(?:像素|px)?", txt)
        return int(mm.group(1)) if mm else None
    except Exception as e:
        print(f"[warn] GLM 缺口识别失败: {e}", file=sys.stderr)
        return None


# ---------------- 拟人轨迹 ----------------

def human_track(distance, duration_ms=None):
    """生成拟人拖拽轨迹：easeOut（先快后慢）+ y 抖动 + 末端微调。

    返回 [(dx, dy, dt_ms)] 相对增量序列，累计 dx ≈ distance。
    """
    duration = duration_ms or random.randint(900, 1400)
    steps = max(18, distance // 8)
    points, prev_x = [], 0.0
    for i in range(1, steps + 1):
        p = i / steps
        ease = 1 - (1 - p) ** 3                 # easeOutCubic
        target_x = ease * distance              # 累计目标位置
        jitter_y = random.uniform(-2.5, 2.5) if p < 0.85 else random.uniform(-1, 1)
        dt = duration / steps + (random.uniform(-8, 8) if p > 0.1 else 0)
        points.append((target_x - prev_x, jitter_y, max(dt, 5)))
        prev_x = target_x
    # 末端停顿微调（人类对准动作）
    points.append((random.uniform(0.5, 1.5), 0, random.randint(120, 260)))
    points.append((0, 0, random.randint(80, 150)))
    return points


def drag_slider(page, slider, distance):
    """playwright 鼠标拖拽（拟人轨迹）。"""
    box = slider.bounding_box()
    sx, sy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(sx, sy)
    page.mouse.down()
    cx = 0.0
    for dx, dy, dt in human_track(distance):
        cx += dx
        page.mouse.move(sx + cx, sy + dy, steps=1)
        time.sleep(dt / 1000.0)
    page.mouse.up()


# ---------------- 主流程 ----------------

def load_targets(date8=None):
    """查询名单：推荐 TOP20 的法人（legal_companies F10 画像），15 天缓存过滤。"""
    import legal_check
    db, fallback = legal_check.get_db()
    date8 = date8 or datetime.now().strftime("%Y%m%d")
    path = os.path.join(BASE, "output", f"recommend_{date8}.json")
    if not os.path.exists(path):
        sys.exit(f"[error] 无 {path}（先跑 recommend.py）")
    rec = json.load(open(path, encoding="utf-8"))
    cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}
    out = []
    for r in rec.get("recommended", [])[:20]:
        code = r["code"]
        c = cache.get(code) or {}
        if c.get("last_checked"):
            try:
                if (datetime.now() - datetime.strptime(c["last_checked"][:19], "%Y-%m-%d %H:%M:%S")) < timedelta(days=RECHECK_DAYS):
                    continue
            except Exception:
                pass
        doc = legal_check.load_company(db, fallback, code)
        person = (doc or {}).get("legal_person", "")
        if person:
            out.append({"code": code, "name": r["name"], "person": person})
    return out, cache, db, fallback


def save_cache(cache):
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)


def query_one(page, person, resp_holder):
    """在页面查一个名字，拦截 searchSX 响应。返回结果 list（空=无记录）。"""
    resp_holder.clear()
    inp = page.locator("input[name='pName'], input.pName, #pName").first
    inp.fill("")
    inp.fill(person)
    page.locator("button:has-text('查询'), a:has-text('查询'), input[type='submit']").first.click()
    page.wait_for_timeout(2500)
    return resp_holder[-1] if resp_holder else None


def run(names):
    """playwright 主循环：滑块验证（GLM 打码）+ 批量查询。"""
    from playwright.sync_api import sync_playwright
    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)   # 有头模式便于观察/调试
        page = browser.new_page()
        holder = []

        def on_resp(resp):
            if "searchSX" in resp.url:
                try:
                    holder.append(resp.json())
                except Exception:
                    pass
        page.on("response", on_resp)

        page.goto(SHIXIN_URL, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(3000)  # 瑞数 JS 冷启

        for i, t in enumerate(names):
            person = t.get("person") or t.get("name")
            print(f"[{i+1}/{len(names)}] 查询: {person}（{t.get('code','')}）")
            data = None
            for attempt in range(1, MAX_SLIDE_RETRY + 1):
                try:
                    data = query_one(page, person, holder)
                    if data is not None:
                        break
                except Exception as e:
                    print(f"  [warn] 查询异常: {e}", file=sys.stderr)
                # 滑块出现 → GLM 识别 + 拖拽
                try:
                    slider = page.locator(".slider-btn, .slide-btn, [class*=handler], [class*=slider]").first
                    if slider.is_visible(timeout=3000):
                        bg = page.locator("[class*=bg], canvas").first
                        bg_b64 = bg.screenshot() if bg.count() else None
                        # 优化路径：从网络层抓验证码图（页面 <img src=data:...>）
                        imgs = page.evaluate("""() => [...document.images]
                            .map(i => i.src).filter(s => s.startsWith('data:image/png'))""")
                        if len(imgs) >= 1:
                            bg_b64 = imgs[-2] if len(imgs) >= 2 else imgs[0]
                            tpl_b64 = imgs[-1] if len(imgs) >= 2 else None
                            bg_b64 = bg_b64.split(",", 1)[1]
                            tpl_b64 = tpl_b64.split(",", 1)[1] if tpl_b64 else None
                            gap_x = glm_find_gap(bg_b64, tpl_b64)
                            if gap_x:
                                # 缺口 x - 滑块当前 x ≈ 拖拽距离（页面坐标缩放换算）
                                scale = page.evaluate(
                                    "() => { const i = [...document.images].pop();"
                                    "return i ? i.clientWidth / 360 : 1; }")
                                dist = max(20, int(gap_x * scale) - 8)
                                drag_slider(page, slider, dist)
                                page.wait_for_timeout(2000)
                                data = query_one(page, person, holder)
                                if data is not None:
                                    break
                except Exception as e:
                    print(f"  [warn] 滑块处理失败(第{attempt}次): {e}", file=sys.stderr)
                page.wait_for_timeout(1500)
            if data is None:
                print("  ✗ 未能获取结果（滑块/频控）")
                results[t.get("code", person)] = {"ok": False}
            else:
                rows = (data if isinstance(data, list) else data.get("result") or data.get("data") or [])
                results[t.get("code", person)] = {"ok": True, "count": len(rows), "rows": rows}
                print(f"  ✓ 命中 {len(rows)} 条")
            time.sleep(SLEEP_BETWEEN)
        browser.close()
    return results


def main():
    args = sys.argv[1:]
    if "--one" in args:
        names = [{"code": "", "name": args[args.index("--one") + 1], "person": args[args.index("--one") + 1]}]
        cache, db, fallback = {}, None, None
    elif "--names" in args:
        raw = args[args.index("--names") + 1]
        names = [{"code": "", "name": x.strip(), "person": x.strip()}
                 for x in raw.split(",") if x.strip()]
        cache, db, fallback = {}, None, None
    else:
        names, cache, db, fallback = load_targets()
        print(f"待查 {len(names)} 个法人（15 天缓存已过滤）")
        if not names:
            print("[done] 全部近期已查")
            return

    results = run(names)

    # 入库 + 缓存 + 报告
    import legal_check
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report = ["# 执行网失信查询报告 " + datetime.now().strftime("%Y%m%d"), "",
              "| 股票 | 法人 | 命中 | 明细 |", "|---|---|---:|---|"]
    n_hit = 0
    for t in names:
        code, person = t.get("code", ""), t["person"]
        r = results.get(code or person, {})
        cache[code or person] = {"last_checked": now, "ok": r.get("ok", False)}
        rows = r.get("rows") or []
        if rows:
            n_hit += 1
            for row in rows[:3]:
                if db is not None:
                    try:
                        legal_check.upsert_risk(db, fallback, {
                            "code": code or "-", "person": person, "risk_type": "dishonest",
                            "case_no": str(row.get("caseCode") or ""), "amount": "",
                            "filed_date": str(row.get("regDate") or ""),
                            "reason": f"执行网失信:{row.get('disruptName','')[:30]}",
                            "trade_date": datetime.now().strftime("%Y%m%d"),
                            "company": t.get("name", ""), "uscc": "",
                            "source": "zxgk-auto", "status": "active", "updated_at": now})
                    except Exception as e:
                        print(f"[warn] 入库失败 {person}: {e}", file=sys.stderr)
        detail = "；".join(str(x.get("caseCode", ""))[:20] for x in rows[:2]) or "—"
        report.append(f"| {t.get('name','')} | {person} | {len(rows)} | {detail} |")
    if cache:
        save_cache(cache)
    report.append("")
    out = os.path.join(BASE, "output", f"zxgk_check_{datetime.now():%Y%m%d}.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(report) + "\n")
    print(f"→ {out}（命中 {n_hit}/{len(names)}）")


if __name__ == "__main__":
    main()
