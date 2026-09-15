#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""巨潮司法风险公告采集器插件（type: cninfo-legal）——法人风险预警自动化 P0.5。

信息价值：公司自披露的诉讼/冻结/破产类公告 = 最权威及时的司法风险信号
（披露义务保证覆盖重大案件），零成本替代部分人工核查。

与 legal_check.py（P0 人工通道）的关系：
  本插件自动发现「已披露司法风险」的公司 → 推荐层自动回避；
  人工通道只需核查「无披露」的公司（被执行/失信名单里未达披露标准的）。

接口：复用巨潮 hisAnnouncement/query 的 searchkey 全文搜索模式。
要点（2026-09-15 实测）：
- searchkey=诉讼/冻结 等词直接命中标题，30 天窗口效果最佳（诉讼公告低频）
- 类别参数对诉讼类无效（回退默认流），必须走 searchkey
- 同一公告可能命中多个关键词：announcementId 去重
"""
import datetime as _dt
import re
import sys
import time

from cninfo_announce import _post_form, _query, _fmt_time, PDF_BASE

SOURCE = "cninfo-legal"
# 司法风险搜索词（每个词一次请求，30 天窗口）
SEARCH_WORDS = ["诉讼", "冻结", "破产重整", "司法拍卖"]
LOOKBACK_DAYS = 30


def fetch(cfg: dict) -> list:
    """采集器插件统一入口。"""
    stop_date = cfg.get("_stop_date") or _dt.date.today().strftime("%Y-%m-%d")
    words = cfg.get("search_words", SEARCH_WORDS)
    lookback = int(cfg.get("lookback_days", LOOKBACK_DAYS))
    end = _dt.datetime.strptime(stop_date, "%Y-%m-%d").date()
    start = end - _dt.timedelta(days=lookback)
    sedate = f"{start}~{end}"

    items, seen = [], set()
    for kw in words:
        try:
            rows = _query({"searchkey": kw, "seDate": sedate, "pageSize": "30"})
        except Exception as e:
            print(f"[warn] 司法风险搜索失败 [{kw}]: {e}", file=sys.stderr)
            continue
        for a in rows:
            aid = a.get("announcementId")
            title = re.sub(r"</?em>", "", str(a.get("announcementTitle") or ""))
            # 二次校验：标题必须真实含风险词（搜索偶有模糊匹配）
            if not any(w in title for w in ("诉讼", "仲裁", "冻结", "破产", "重整", "清算", "司法拍卖", "冻结")):
                continue
            if aid in seen:
                continue
            seen.add(aid)
            code = str(a.get("secCode") or "")
            name = str(a.get("secName") or "")
            if not (len(code) == 6 and code.isdigit()):
                continue
            items.append({
                "title": f"司法风险：{name}{title[:44]}",
                "body": f"司法风险公告（{name}（{code}））：{title}",
                "time": _fmt_time(a.get("announcementTime")),
                "source": SOURCE,
                "url": PDF_BASE + str(a.get("adjunctUrl") or ""),
                "stocks": [code],
            })
        time.sleep(0.3)
    return items


def selftest() -> bool:
    tm_re = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
    try:
        items = fetch({"_stop_date": _dt.date.today().strftime("%Y-%m-%d"),
                       "search_words": ["诉讼"], "lookback_days": 30})
    except Exception as e:
        print(f"[warn] selftest 网络失败: {e}", file=sys.stderr)
        return False
    if not items:
        print("[warn] selftest 未取到数据", file=sys.stderr)
        return False
    for it in items[:5]:
        if set(it) != {"title", "body", "time", "source", "url", "stocks"}:
            return False
        if not tm_re.match(it["time"]) or it["source"] != SOURCE:
            return False
        if not it["url"].startswith(PDF_BASE):
            return False
    return True


if __name__ == "__main__":
    print(selftest())
