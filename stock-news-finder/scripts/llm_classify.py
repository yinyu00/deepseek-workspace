#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""解析层（LLM 版）：调用 GLM API 对命中词典的新闻做事件分类。

- 只送「预匹配到词典股票」的新闻（省 token）
- 输出 output/llm_events.json，供 match_score.py 合并使用
- key 从环境变量 GLM_VISION_API_KEY 读取（本机在 ~/.zshrc）
- 失败/无 key 时静默降级（match_score 回退正则规则）

用法：python3 llm_classify.py [批量大小，默认8]
"""
import json
import os
import subprocess
import sys
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根 = scripts/ 上一级
DICT = os.path.join(BASE, "data", "stock_dict.json")
NEWS = os.path.join(BASE, "output", "raw_news.json")
OUT = os.path.join(BASE, "output", "llm_events.json")
API = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
MODEL = "glm-4v-flash"  # 免费文本能力够用

EVENT_ENUM = [
    "earnings_beat 业绩大超预期",
    "order 订单/中标/大合同",
    "buyback 回购/增持",
    "ma 并购/重组",
    "policy 政策利好(行业/公司)",
    "product 产品/研发/获批进展",
    "rating 机构评级/目标价调整",
    "negative 负面(亏损/减持/处罚/风险)",
    "neutral 一般资讯",
]

PROMPT_TMPL = """你是A股新闻分析师。对下面每条新闻判断：涉及哪些候选股票、事件类型、对股价的短期影响分。

候选股票（格式 代码:名称，只能从中选，没有合适的选空数组）：
{candidates}

事件类型（只能选其一）：
{events}

输出 JSON 数组，每条新闻一个对象：
[{{"id": 新闻编号, "stocks": ["代码"], "event": "类型英文", "impact": -5到5的整数, "confidence": 0到1的小数, "reason": "10字以内理由"}}]

新闻列表：
{news}"""


def get_key():
    key = os.environ.get("GLM_VISION_API_KEY")
    if key:
        return key
    # 从登录 shell 取（本机 key 写在 ~/.zshrc）
    try:
        out = subprocess.run(["zsh", "-ic", "echo $GLM_VISION_API_KEY"],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or None
    except Exception:
        return None


def call_llm(prompt, key):
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
        "temperature": 0.1,
    }).encode()
    req = urllib.request.Request(API, data=body, headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read().decode())
    return data["choices"][0]["message"]["content"]


def parse_json_loose(text):
    text = text.strip()
    s, e = text.find("["), text.rfind("]")
    if s == -1 or e == -1:
        return []
    try:
        return json.loads(text[s:e + 1])
    except json.JSONDecodeError:
        return []


def main():
    batch = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    key = get_key()
    if not key:
        print("[skip] 无 GLM_VISION_API_KEY，跳过 LLM 分类（回退正则）")
        return

    with open(NEWS, encoding="utf-8") as f:
        news = json.load(f)
    with open(DICT, encoding="utf-8") as f:
        entries = json.load(f)
    # 匹配词 → 新闻预筛 + 候选集
    terms = []
    for e in entries:
        terms.append((e["name"], e["code"]))
        for a in e.get("aliases", []):
            if len(a) >= 3:  # LLM 层只送低歧义词预筛
                terms.append((a, e["code"]))

    matched_news, candidates = [], set()
    for n in news:
        text = n["title"] + " " + n["body"]
        hit_codes = {c for t, c in terms if t in text}
        if hit_codes:
            n["_id"] = len(matched_news)
            n["_cands"] = sorted(hit_codes)
            matched_news.append(n)
            candidates |= hit_codes
    print(f"预筛命中新闻 {len(matched_news)}/{len(news)} 条，涉及 {len(candidates)} 只候选")

    cand_str = "\n".join(f"{e['code']}:{e['name']}" for e in entries if e["code"] in candidates)
    event_str = "\n".join(EVENT_ENUM)

    results = []
    for i in range(0, len(matched_news), batch):
        chunk = matched_news[i:i + batch]
        news_str = "\n".join(
            f"[{n['_id']}] {n['title']} | {n['body'][:150]}" for n in chunk)
        prompt = PROMPT_TMPL.format(candidates=cand_str, events=event_str, news=news_str)
        try:
            raw = call_llm(prompt, key)
        except Exception as e:
            print(f"[warn] 批次 {i//batch} 调用失败: {e}", file=sys.stderr)
            continue
        for item in parse_json_loose(raw):
            if isinstance(item, dict) and "id" in item:
                results.append(item)
        print(f"  批次 {i//batch + 1}/{(len(matched_news)+batch-1)//batch}: 累计 {len(results)} 条")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    print(f"→ {OUT}（{len(results)} 条分类结果）")


if __name__ == "__main__":
    main()
