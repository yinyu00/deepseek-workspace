#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""人民法院公告网采集器插件（type: rmfygg-notice）——法院视角司法风险流。

信息价值：送达/开庭/破产/清算公告的受送达主体（tosendPeople）是涉诉信号，
与 cninfo-legal（公司自披露）互补。小艺 11 源清单实测后的唯一可行免费路径。

接口：Liferay portlet initNoticeList（参数由用户浏览器抓包提供，2026-09-17）。
要点（踩坑记录）：
- 请求头完整度敏感：origin/sec-fetch-*/accept-language 全套必带，
  精简 headers 返回空 data（iTotalRecords=0 但 HTTP 200，易误判为无数据）
- aoData 的 DataTables 字段全必填（sEcho/iColumns/sColumns/iDisplayStart/
  iDisplayLength/mDataProp_0-5），缺 sColumns 或 mDataProp 都返回空
- tosendPeople 直供主体名（人名或公司全称），无需 LLM 抽取
- 股票关联用双向子串匹配（股票简称通常是公司全称子串）
- 会话：先 GET 列表页拿 JSESSIONID 再 POST（cookie 失效表现同空 data）
"""
import datetime as _dt
import http.cookiejar
import json
import re
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

SOURCE = "rmfygg-notice"
BASE_URL = "https://rmfygg.court.gov.cn/web/rmfyportal/noticeinfo"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36")

# 公告类型 → 事件分类（match_score 正则配套）
HEAVY_TYPES = re.compile(r"(破产|清算|拍卖|竞买|变卖)")   # 全保留 + 资产风险
LITIGATION_TYPES = re.compile(r"(送达|传票|开庭|起诉|判决|执行)")  # 需 A 股关联才收
DISHONEST_CTX = re.compile(r"(失信|被执行|限制消费|限制高消费)")


def _curl(args, timeout=20):
    r = subprocess.run(["curl", "-s", "-m", str(timeout), "--noproxy", "*"] + args,
                       capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


# ---- urllib 兜底通道（Windows：curl schannel 对本域 TLS 失败 rc=35，D5 家族问题）----
_URNET = {"use": False, "jar": None}


def _urlopen(url, data=None, headers=None):
    """urllib + CookieJar 会话；SSL 失败自动降级（unverified + SECLEVEL=1）。"""
    if _URNET["jar"] is None:
        _URNET["jar"] = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_URNET["jar"]))
    req = urllib.request.Request(url, data=data, headers=headers or {"User-Agent": UA})
    try:
        with op.open(req, timeout=20) as r:
            return r.read().decode("utf-8", "ignore")
    except ssl.SSLError:
        pass
    except urllib.error.URLError as e:
        if not isinstance(getattr(e, "reason", None), ssl.SSLError):
            raise
    ctx = ssl._create_unverified_context()
    ctx.set_ciphers("DEFAULT@SECLEVEL=1")
    with op.open(req, timeout=20, context=ctx) as r:
        return r.read().decode("utf-8", "ignore")


def _fetch_page(cookie, start=0, length=15):
    """拉一页公告列表。curl 优先（Mac），失败（Windows schannel TLS）切 urllib 会话。
    返回 data 数组（空=会话失效或被风控）。"""
    ao = [{"name": "sEcho", "value": 3}, {"name": "iColumns", "value": 6},
          {"name": "sColumns", "value": ",,,,,,,"},
          {"name": "iDisplayStart", "value": start},
          {"name": "iDisplayLength", "value": length}]
    ao += [{"name": f"mDataProp_{i}", "value": None} for i in range(6)]
    form = {
        "_noticelist_WAR_rmfynoticeListportlet_content": "",
        "_noticelist_WAR_rmfynoticeListportlet_searchContent": "",
        "_noticelist_WAR_rmfynoticeListportlet_courtParam": "",
        "_noticelist_WAR_rmfynoticeListportlet_IEVersion": "ie",
        "_noticelist_WAR_rmfynoticeListportlet_flag": "init",
        "_noticelist_WAR_rmfynoticeListportlet_noticeType": "",
        "_noticelist_WAR_rmfynoticeListportlet_noticeTypeVal": "全部",
        "_noticelist_WAR_rmfynoticeListportlet_noticeSource": "",
        "_noticelist_WAR_rmfynoticeListportlet_sourceTypeVal": "全部",
        "_noticelist_WAR_rmfynoticeListportlet_isWebCountNotice": "",
        "_noticelist_WAR_rmfynoticeListportlet_aoData": json.dumps(ao),
    }
    url = BASE_URL + "?" + urllib.parse.urlencode({
        "p_p_id": "noticelist_WAR_rmfynoticeListportlet",
        "p_p_lifecycle": "2", "p_p_state": "normal", "p_p_mode": "view",
        "p_p_resource_id": "initNoticeList",
        "p_p_cacheability": "cacheLevelPage",
        "p_p_col_id": "column-1", "p_p_col_count": "1"})
    headers = {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "origin": "https://rmfygg.court.gov.cn",
        "referer": "https://rmfygg.court.gov.cn/web/rmfyportal/noticeinfo",
        "user-agent": UA,
        "x-requested-with": "XMLHttpRequest",
        "sec-fetch-dest": "empty", "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
    }
    body = ""
    if not _URNET["use"]:
        body = _curl([
            "-c", cookie, "-b", cookie, "--url", url,
            *sum([["-H", f"{k}: {v}"] for k, v in headers.items()], []),
            "--data-raw", urllib.parse.urlencode(form, quote_via=urllib.parse.quote),
        ])
    if not body:
        # curl 通道失败（Windows TLS）→ urllib 会话（CookieJar 自动管 JSESSIONID）
        _URNET["use"] = True
        if not _URNET.get("warmed"):
            _urlopen(BASE_URL)  # 会话预热（等价原 curl -c 首访）
            _URNET["warmed"] = True
        body = _urlopen(url, data=urllib.parse.urlencode(form).encode("utf-8"),
                        headers=headers)
    try:
        return json.loads(body).get("data") or []
    except Exception:
        return []


def _dict_matcher():
    """A 股词典：[(名称/别名, code)]，供主体名双向子串匹配。"""
    import os
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "stock_dict.json")
    terms = []
    try:
        for e in json.load(open(path, encoding="utf-8")):
            terms.append((e["name"], e["code"]))
            for a in e.get("aliases", []):
                if len(a) >= 3:
                    terms.append((a, e["code"]))
    except Exception:
        pass
    return terms


def _match_stocks(subject, terms):
    """主体名 ↔ 股票简称双向子串（'宁德时代' ⊂ '宁德时代新能源科技股份有限公司'）。"""
    out = []
    for name, code in terms:
        if name in subject or (len(subject) >= 4 and subject in name):
            out.append(code)
        if len(out) >= 3:
            break
    return out


def fetch(cfg: dict) -> list:
    """采集器插件统一入口。max_pages 默认 4（60 条/日滚动窗口）。"""
    import os
    stop_date = cfg.get("_stop_date") or _dt.date.today().strftime("%Y-%m-%d")
    max_pages = int(cfg.get("max_pages", 4))
    cookie = os.path.join(tempfile.gettempdir(), f"rmfygg_ck_{os.getpid()}.txt")
    terms = _dict_matcher()
    if not _URNET["use"]:
        # 会话预热（JSESSIONID）——curl 通道专用；urllib 通道在 _fetch_page 内预热
        _curl(["-c", cookie, "--url", BASE_URL, "-H", f"user-agent: {UA}"])

    items, seen = [], set()
    for page in range(max_pages):
        rows = _fetch_page(cookie, start=page * 15)
        if not rows:
            print(f"[warn] 公告网第{page+1}页空（会话/风控），止步", file=sys.stderr)
            break
        for r in rows:
            code_id = str(r.get("noticeCode") or r.get("uuid") or "")
            if not code_id or code_id in seen:
                continue
            seen.add(code_id)
            subject = str(r.get("tosendPeople") or "").strip()
            ntype = str(r.get("noticeType") or "").strip()
            court = str(r.get("court") or "").strip()
            content = str(r.get("noticeContent") or "").strip()
            date = str(r.get("publishDate") or "")[:10]
            if stop_date and date and date > stop_date:
                continue
            stocks = _match_stocks(subject, terms)
            # 策略：重类（破产/清算/拍卖）全收；轻类（送达/开庭）需 A 股关联
            if not HEAVY_TYPES.search(ntype + content[:80]) and not stocks:
                continue
            title = f"[{ntype}] {subject[:30]}（{court[:12]}）"
            items.append({
                "title": title,
                "body": f"法院公告（{subject}）：{content[:500]}（{court} {date} 发布）",
                "time": f"{date} 08:00:00" if date else "",
                "source": SOURCE,
                "url": f"https://rmfygg.court.gov.cn/web/rmfyportal/noticeinfo",
                "stocks": stocks,
            })
        time.sleep(1)  # 礼貌限速
    n_a = sum(1 for i in items if i["stocks"])
    print(f"  [rmfygg] 公告 {len(items)} 条（A 股关联 {n_a} 条）")
    return items


def selftest() -> bool:
    tm_re = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
    try:
        items = fetch({"max_pages": 1})
    except Exception as e:
        print(f"[warn] selftest 失败: {e}", file=sys.stderr)
        return False
    if not items:
        print("[warn] selftest 未取到数据", file=sys.stderr)
        return False
    for it in items[:5]:
        if set(it) != {"title", "body", "time", "source", "url", "stocks"}:
            return False
        if it["time"] and not tm_re.match(it["time"]):
            return False
        if it["source"] != SOURCE:
            return False
    return True


if __name__ == "__main__":
    print(selftest())
