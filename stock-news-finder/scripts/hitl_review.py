#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HITL 判定导入：解析 hitl_pending 回填 → 标注库 → 重跑当日打分即生效。

用法：
  python3 scripts/hitl_review.py --import output/hitl_pending_20260915.md
  python3 scripts/hitl_review.py --stats          # 标注库统计（周报素材）
"""
import json
import os
import re
import sys
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LABELS = os.path.join(BASE, "data", "hitl_labels.jsonl")
VALID = {"正", "负", "中性"}
# 自然写法归一化（用户可能写"正面/负面"全称）
NORMALIZE = {"正面": "正", "负面": "负", "中性": "中性", "正": "正", "负": "负"}


def parse_pending(path):
    """解析回填文件 → [(code_str, event, judgment, reason)]。

    按表头列名定位 `#判定结果` / `#判定原因`（v1.2 模板，预判列不干扰）；
    兼容旧格式（代码块行 / 表格末列判定）。
    """
    rows, header_idx = [], {}
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if not any(c.startswith("P") and c[1:].isdigit() for c in cells[:1]):
                # 表头行：记录 #判定结果 / #判定原因 的列位置
                for idx, c in enumerate(cells):
                    if "判定结果" in c:
                        header_idx["j"] = idx
                    elif "判定原因" in c:
                        header_idx["r"] = idx
                continue
            # 数据行
            if re.match(r"^P\d+$", cells[0]):
                if "j" in header_idx and len(cells) > max(header_idx.values()):
                    judgment, reason = cells[header_idx["j"]], cells[header_idx.get("r", 0)]
                    if judgment in NORMALIZE:  # 占位符/未填跳过；正面/负面归一化
                        rows.append((cells[1], cells[2], NORMALIZE[judgment], reason))
                    continue
                # 旧格式兼容：最后一个有效判定列
                judged = next((c for c in reversed(cells) if c in NORMALIZE), None)
                if judged:
                    rows.append((cells[1], cells[2], NORMALIZE[judged], ""))
            continue
        parts = [x.strip() for x in line.split("|")]   # 代码块行（v1）
        if len(parts) >= 4 and re.match(r"^P\d+$", parts[0]) and parts[3] in NORMALIZE:
            rows.append((parts[1], parts[2], NORMALIZE[parts[3]], ""))
    return rows


def append_labels(rows, pending_path):
    """标注入库：key=(url或标题, 事件名)。从 pending 生成文件反查 url/标题。"""
    # pending md 里编号与 key 的映射需从 match_score 重算太重——直接用「标题模糊匹配」：
    # 简化契约：标注 key 存 (事件名+股票, 事件) 不够稳，改为存标题匹配片段。
    # 最终方案：labels 记录 {key:[url,title], event, judgment}，match_score 侧按
    # (url||title, event) 双键匹配——此处从 pending md 表格行提取标题片段。
    # 表格行含关键句不含标题 → 从回填行无法拿到 url。
    # 落地妥协（v1）：判定行带股票代码，标注库存 (代码,事件)→判定，作用于
    # 该股票该事件的所有当日新闻（粒度足够：同一公司同类澄清场景一致）。
    out = 0
    with open(LABELS, "a", encoding="utf-8") as f:
        for codes, event, judgment, reason in rows:
            for code in [c for c in codes.split(",") if c] or ["-"]:
                doc = {"key": code, "code": code, "event": event,
                       "judgment": judgment, "reason": reason,   # 学习语料（HITL 学习闭环核心）
                       "labeled_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                       "from": os.path.basename(pending_path)}
                f.write(json.dumps(doc, ensure_ascii=False) + "\n")
                out += 1
    return out


def stats():
    if not os.path.exists(LABELS):
        print("标注库为空")
        return
    rows = [json.loads(x) for x in open(LABELS, encoding="utf-8") if x.strip()]
    by_j = {}
    for r in rows:
        by_j[r["judgment"]] = by_j.get(r["judgment"], 0) + 1
    print(f"标注库累计 {len(rows)} 条：{by_j}")
    by_e = {}
    for r in rows:
        by_e.setdefault(r["event"], []).append(r["judgment"])
    print("\n按事件（学习闭环：一致性>90%可提案固化事件类型）：")
    for e, js in sorted(by_e.items(), key=lambda x: -len(x[1])):
        dist = {j: js.count(j) for j in set(js)}
        print(f"  {e}: {dist}")


def main():
    args = sys.argv[1:]
    if "--stats" in args:
        return stats()
    if "--import" in args:
        path = args[args.index("--import") + 1]
        if not os.path.exists(path):
            sys.exit(f"[error] 文件不存在: {path}")
        rows = parse_pending(path)
        if not rows:
            sys.exit("[error] 未发现已判定行（格式：P1|代码|事件|正/负/中性），请先回填")
        n = append_labels(rows, path)
        print(f"已导入 {n} 条标注 → {LABELS}")
        print("下一步：重跑当日打分生效（python3 scripts/match_score.py）")
        return
    print(__doc__)


if __name__ == "__main__":
    main()
