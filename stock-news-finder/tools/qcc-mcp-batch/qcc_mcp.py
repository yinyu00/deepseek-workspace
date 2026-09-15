"""企查查 MCP 批量爬取主脚本。

================================================================
使用前请把同目录 config.json 里的 YOUR_TOKEN_HERE 换成你自己的 Token
================================================================


特性：
- 4 个 server 各保持一个 session（cookie 自动维护）
- 支持全部 67 项 MCP 工具，并行调用（线程池），可自由选择字段
- 默认跑推荐核心 25 项，加 --all-fields 跑全部 67 项
- 断点续爬（progress.json 记录已完成的 USCC/名称）
- 错误重试 + 限流退避
- 每条实体单独 JSON 落盘 + 全量汇总

用法：
    py qcc_mcp.py --test                             # 跑名单前 5 条试试
    py qcc_mcp.py --start 0 --end 100                # 跑名单指定区间
    py qcc_mcp.py                                    # 全量名单（默认核心 25 项，带断点续爬）
    py qcc_mcp.py --all-fields                       # 全部 67 项字段（消耗 ×2.68 积分）
    py qcc_mcp.py --merge                            # 仅合并已抓数据为大 JSON + CSV
    py qcc_mcp.py --entity 9144030059070463XP        # 手动抓一个 USCC
    py qcc_mcp.py --entity "深圳华信股权投资基金管理有限公司"  # 手动抓一个企业名
    py qcc_mcp.py --entity USCC1 USCC2 "名字A"        # 手动抓多个
    py qcc_mcp.py -i                                 # 交互模式
    py qcc_mcp.py --entity-file list.txt             # 从文本文件读
    py qcc_mcp.py --list-fields                      # 查看全部 67 项字段及分组
    py qcc_mcp.py --fields 工商信息 股东信息 专利      # 只抓指定字段
    py qcc_mcp.py --fields-group 工商 风险            # 按分类抓取
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import requests

# Windows 控制台编码（GUI 场景下 buffer 可能为 None，忽略即可）
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

ROOT = Path(__file__).parent
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))

# Token 友好校验：萌新如果没填 token，给一个清楚的提示而不是后面接口报 401
for _srv, _info in CFG.get("mcpServers", {}).items():
    _auth = _info.get("headers", {}).get("Authorization", "")
    if "YOUR_TOKEN_HERE" in _auth or _auth.strip() in ("Bearer", "Bearer ", ""):
        print(
            "\n[配置错误] config.json 里的 Authorization 还没填 Token。\n"
            "  请打开同目录的 config.json，把 4 处 'YOUR_TOKEN_HERE' 替换成你自己的企查查 MCP Token。\n"
            "  Token 在企查查 agent 平台（agent.qcc.com）登录后获取，4 个 server 用同一个 token 即可。\n"
        )
        sys.exit(1)

INPUT_CSV = ROOT / "qcc_search_list.csv"
OUT_DIR = ROOT / "qcc_data_mcp"
JSON_DIR = OUT_DIR / "json"
PROGRESS_FILE = OUT_DIR / "_progress.json"
LOG_FILE = OUT_DIR / "_log.txt"
MERGED_JSON = OUT_DIR / "qcc_全量数据.json"
MERGED_CSV = OUT_DIR / "qcc_全量数据汇总.csv"

JSON_DIR.mkdir(parents=True, exist_ok=True)

# 全量 67 项工具：(server, tool_name, 中文标签, 分类)
# 原 25 项"核心集"的中文标签保持不变（避免打乱已抓 JSON 的 data 键），新增 42 项按 md 命名
CORE_TOOLS: list[tuple[str, str, str, str]] = [
    # 工商 14 项
    ("qcc-company", "get_company_registration_info", "工商信息",     "工商"),
    ("qcc-company", "get_company_profile",           "企业简介",     "工商"),
    ("qcc-company", "get_shareholder_info",          "股东信息",     "工商"),
    ("qcc-company", "get_actual_controller",         "实控人",       "工商"),
    ("qcc-company", "get_beneficial_owners",         "受益所有人",   "工商"),
    ("qcc-company", "get_key_personnel",             "主要人员",     "工商"),
    ("qcc-company", "get_external_investments",      "对外投资",     "工商"),
    ("qcc-company", "get_branches",                  "分支机构",     "工商"),
    ("qcc-company", "get_change_records",            "变更记录",     "工商"),
    ("qcc-company", "get_annual_reports",            "年报",         "工商"),
    ("qcc-company", "get_listing_info",              "上市信息",     "工商"),
    ("qcc-company", "get_contact_info",              "联系方式",     "工商"),
    ("qcc-company", "get_tax_invoice_info",          "税号开票",     "工商"),
    ("qcc-company", "verify_company_accuracy",       "准确性验证",   "工商"),
    # 经营 13 项
    ("qcc-operation", "get_financing_records",       "融资历程",     "经营"),
    ("qcc-operation", "get_news_sentiment",          "新闻舆情",     "经营"),
    ("qcc-operation", "get_qualifications",          "资质",         "经营"),
    ("qcc-operation", "get_bidding_info",            "招投标",       "经营"),
    ("qcc-operation", "get_credit_evaluation",       "信用评价",     "经营"),
    ("qcc-operation", "get_administrative_license",  "行政许可",     "经营"),
    ("qcc-operation", "get_recruitment_info",        "招聘信息",     "经营"),
    ("qcc-operation", "get_import_export_credit",    "进出口信用",   "经营"),
    ("qcc-operation", "get_spot_check_info",         "抽查检查",     "经营"),
    ("qcc-operation", "get_telecom_license",         "电信许可",     "经营"),
    ("qcc-operation", "get_ranking_list_info",       "上榜榜单",     "经营"),
    ("qcc-operation", "get_honor_info",              "荣誉信息",     "经营"),
    ("qcc-operation", "get_company_announcement",    "企业公告",     "经营"),
    # 风险 34 项
    ("qcc-risk", "get_dishonest_info",               "失信",         "风险"),
    ("qcc-risk", "get_business_exception",           "经营异常",     "风险"),
    ("qcc-risk", "get_administrative_penalty",       "行政处罚",     "风险"),
    ("qcc-risk", "get_judicial_documents",           "裁判文书",     "风险"),
    ("qcc-risk", "get_equity_pledge_info",           "股权出质",     "风险"),
    ("qcc-risk", "get_judgment_debtor_info",         "被执行人",     "风险"),
    ("qcc-risk", "get_high_consumption_restriction", "限制高消费",   "风险"),
    ("qcc-risk", "get_serious_violation",            "严重违法",     "风险"),
    ("qcc-risk", "get_terminated_cases",             "终本案件",     "风险"),
    ("qcc-risk", "get_case_filing_info",             "立案信息",     "风险"),
    ("qcc-risk", "get_hearing_notice",               "开庭公告",     "风险"),
    ("qcc-risk", "get_court_notice",                 "法院公告",     "风险"),
    ("qcc-risk", "get_service_notice",               "送达公告",     "风险"),
    ("qcc-risk", "get_bankruptcy_reorganization",    "破产重整",     "风险"),
    ("qcc-risk", "get_equity_freeze",                "股权冻结",     "风险"),
    ("qcc-risk", "get_judicial_auction",             "司法拍卖",     "风险"),
    ("qcc-risk", "get_valuation_inquiry",            "询价评估",     "风险"),
    ("qcc-risk", "get_pre_litigation_mediation",     "诉前调解",     "风险"),
    ("qcc-risk", "get_exit_restriction",             "限制出境",     "风险"),
    ("qcc-risk", "get_environmental_penalty",        "环保处罚",     "风险"),
    ("qcc-risk", "get_tax_abnormal",                 "税务非正常户", "风险"),
    ("qcc-risk", "get_tax_arrears_notice",           "欠税公告",     "风险"),
    ("qcc-risk", "get_tax_violation",                "税收违法",     "风险"),
    ("qcc-risk", "get_disciplinary_list",            "惩戒名单",     "风险"),
    ("qcc-risk", "get_default_info",                 "违约事项",     "风险"),
    ("qcc-risk", "get_guarantee_info",               "担保信息",     "风险"),
    ("qcc-risk", "get_stock_pledge_info",            "股权质押",     "风险"),
    ("qcc-risk", "get_chattel_mortgage_info",        "动产抵押",     "风险"),
    ("qcc-risk", "get_land_mortgage_info",           "土地抵押",     "风险"),
    ("qcc-risk", "get_simple_cancellation_info",     "简易注销",     "风险"),
    ("qcc-risk", "get_cancellation_record_info",     "注销备案",     "风险"),
    ("qcc-risk", "get_liquidation_info",             "清算信息",     "风险"),
    ("qcc-risk", "get_service_announcement",         "劳动仲裁",     "风险"),
    ("qcc-risk", "get_public_exhortation",           "公示催告",     "风险"),
    # 知产 6 项
    ("qcc-ipr", "get_patent_info",                   "专利",         "知产"),
    ("qcc-ipr", "get_trademark_info",                "商标",         "知产"),
    ("qcc-ipr", "get_software_copyright_info",       "软著",         "知产"),
    ("qcc-ipr", "get_internet_service_info",         "互联网备案",   "知产"),
    ("qcc-ipr", "get_copyright_work_info",           "作品著作权",   "知产"),
    ("qcc-ipr", "get_standard_info",                 "标准信息",     "知产"),
]

ALL_GROUPS = {"工商", "经营", "风险", "知产"}

# 推荐核心集（25 项）：CLI 不传 --fields 时的默认行为，避免意外烧积分
# 也是 GUI 启动时的默认勾选集
DEFAULT_CORE_LABELS: set[str] = {
    # 工商 12
    "工商信息", "企业简介", "股东信息", "实控人", "受益所有人", "主要人员",
    "对外投资", "分支机构", "变更记录", "年报", "上市信息", "联系方式",
    # 经营 4
    "融资历程", "新闻舆情", "资质", "招投标",
    # 风险 5
    "失信", "经营异常", "行政处罚", "裁判文书", "股权出质",
    # 知产 4
    "专利", "商标", "软著", "互联网备案",
}


def get_default_tools() -> list[tuple[str, str, str, str]]:
    """返回推荐核心 25 项工具列表（CLI 默认、GUI 默认勾选）"""
    return [t for t in CORE_TOOLS if t[2] in DEFAULT_CORE_LABELS]


def resolve_tools(
    fields: list[str] | None,
    groups: list[str] | None,
    all_fields: bool = False,
) -> list[tuple[str, str, str, str]]:
    """根据参数筛选要跑的工具：
    - all_fields=True → 全部 67 项
    - fields / groups 非空 → 按筛选结果
    - 都不传 → 推荐核心 25 项（保持兼容）
    """
    if all_fields:
        return CORE_TOOLS
    if not fields and not groups:
        return get_default_tools()

    selected: list[tuple[str, str, str, str]] = []
    seen: set[str] = set()

    # 先展开逗号（支持 "工商信息,股东信息" 写法）
    flat_fields: set[str] = set()
    for f in (fields or []):
        for part in f.split(","):
            s = part.strip()
            if s:
                flat_fields.add(s)

    flat_groups: set[str] = set()
    for g in (groups or []):
        for part in g.split(","):
            s = part.strip()
            if s:
                flat_groups.add(s)

    # 校验 group 名
    bad_groups = flat_groups - ALL_GROUPS
    if bad_groups:
        raise ValueError(f"未知分类：{bad_groups}；可选：{ALL_GROUPS}")

    for tool in CORE_TOOLS:
        _, _, label, group = tool
        if label in flat_fields or group in flat_groups:
            if label not in seen:
                selected.append(tool)
                seen.add(label)

    # 校验字段名
    all_labels = {t[2] for t in CORE_TOOLS}
    bad_fields = flat_fields - all_labels
    if bad_fields:
        raise ValueError(
            f"未知字段：{bad_fields}\n"
            f"运行 --list-fields 查看全部可选字段"
        )

    if not selected:
        raise ValueError("--fields / --fields-group 未匹配到任何字段，请检查输入")

    return selected


def list_fields():
    """打印全部可选字段，核心 25 项前带 ★"""
    print(f"\n{'分类':<6}  {'中文标签':<14}  tool_name")
    print("-" * 60)
    prev_group = ""
    for _, tool_name, label, group in CORE_TOOLS:
        sep = "\n" if group != prev_group and prev_group else ""
        mark = "★" if label in DEFAULT_CORE_LABELS else " "
        print(f"{sep}{group:<6}  {mark} {label:<12}  {tool_name}")
        prev_group = group
    print(
        f"\n共 {len(CORE_TOOLS)} 项字段，分 {len(ALL_GROUPS)} 组"
        f"（★ 为推荐核心 {len(DEFAULT_CORE_LABELS)} 项，CLI 默认跑这 25 项）"
    )
    print("示例：--fields 工商信息 股东信息 专利")
    print("      --fields-group 工商 风险")
    print("      --all-fields                     # 跑全部 67 项")

# 服务器名 -> 客户端的全局缓存（每个 server 保持一个 session）
_clients: dict[str, "MCPClient"] = {}
_clients_lock = threading.Lock()

# 限速：每个 server 的最近一次调用时间，强制间隔
_last_call: dict[str, float] = {}
_last_call_lock = threading.Lock()
MIN_INTERVAL = 0.15  # 每个 server 调用最小间隔（秒）


class MCPClient:
    """单 server 单 session 的 MCP 客户端"""
    def __init__(self, server_name: str):
        cfg = CFG["mcpServers"][server_name]
        self.server = server_name
        self.url = cfg["url"]
        self.session = requests.Session()
        # 企查查只接受国内 IP，强制不读环境变量代理（HTTP_PROXY/HTTPS_PROXY），
        # 否则挂着 Clash/V2ray 等会被服务端 100002 拒绝。
        self.session.trust_env = False
        self.session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **cfg.get("headers", {}),
        })
        self._req_id = 0
        self._lock = threading.Lock()
        self._initialized = False

    def _next_id(self):
        self._req_id += 1
        return self._req_id

    def _post(self, payload: dict, expect_response: bool = True):
        # 限速
        with _last_call_lock:
            now = time.monotonic()
            last = _last_call.get(self.server, 0)
            wait = MIN_INTERVAL - (now - last)
            if wait > 0:
                time.sleep(wait)
            _last_call[self.server] = time.monotonic()

        r = self.session.post(self.url, json=payload, timeout=120)
        if not expect_response:
            return None
        ctype = r.headers.get("Content-Type", "")
        r.encoding = "utf-8"
        body = r.text
        # 即便 HTTP 4xx/5xx，企查查也会把真实错误码塞进 JSON-RPC body
        # （比如 100002 境外IP / 300008 积分不足）。优先解析，让真实信息透出来。
        if body.strip().startswith("{"):
            try:
                obj = json.loads(body)
                if isinstance(obj, dict) and ("result" in obj or "error" in obj):
                    return obj
            except json.JSONDecodeError:
                pass
        # 不是 JSON-RPC 响应才按 HTTP 错误抛
        r.raise_for_status()
        if "text/event-stream" in ctype:
            for line in body.split("\n"):
                line = line.rstrip("\r")
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data:
                    continue
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if "result" in obj or "error" in obj:
                    return obj
            return None
        return r.json()

    def initialize(self):
        with self._lock:
            if self._initialized:
                return
            self._post({
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "qcc-batch", "version": "0.1"},
                },
            })
            self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, expect_response=False)
            self._initialized = True

    def call_tool(self, name: str, arguments: dict, max_retry: int = 3) -> dict:
        last_err = None
        for attempt in range(max_retry):
            try:
                # initialize 放进 try 里，cold start 的 SSL EOF 等网络抖动也能重试
                self.initialize()
                payload = {
                    "jsonrpc": "2.0",
                    "id": self._next_id(),
                    "method": "tools/call",
                    "params": {"name": name, "arguments": arguments},
                }
                resp = self._post(payload)
                if resp is None:
                    raise RuntimeError("empty response")
                if "error" in resp:
                    err = resp["error"]
                    msg = str(err)
                    # 限流退避
                    if "429" in msg or "rate" in msg.lower() or "limit" in msg.lower():
                        sleep_t = 2 ** attempt + 1
                        time.sleep(sleep_t)
                        last_err = err
                        continue
                    return {"_error": err}
                return resp.get("result", {})
            except Exception as e:
                last_err = str(e)
                time.sleep(1 + attempt)
        return {"_error": f"max_retry exhausted: {last_err}"}


def get_client(server: str) -> MCPClient:
    with _clients_lock:
        if server not in _clients:
            _clients[server] = MCPClient(server)
        return _clients[server]


def _is_no_match(parsed: Any) -> bool:
    """MCP 在实体查不到时会返回 {"无匹配项": "..."}。识别这种情形便于后续导出 missing.csv。"""
    return isinstance(parsed, dict) and "无匹配项" in parsed and len(parsed) <= 2


def parse_tool_result(result: dict) -> Any:
    """MCP 返回的 result.content[0].text 是一个 JSON 字符串，二次解析"""
    if "_error" in result:
        return {"_error": result["_error"]}
    content = result.get("content", [])
    if not content:
        return None
    parts = []
    for c in content:
        if c.get("type") == "text":
            txt = c.get("text", "")
            try:
                parts.append(json.loads(txt))
            except json.JSONDecodeError:
                parts.append(txt)
        else:
            parts.append(c)
    return parts[0] if len(parts) == 1 else parts


def crawl_one(
    entity: dict,
    max_workers: int = 6,
    tools: list[tuple[str, str, str, str]] | None = None,
) -> dict:
    """对一个实体，并行调用指定工具（默认全部）"""
    name = entity["entity_name"]
    uscc = (entity.get("uscc") or "").strip()
    search_key = uscc if uscc else name
    active_tools = tools if tools is not None else CORE_TOOLS

    record: dict[str, Any] = {
        "entity_name": name,
        "uscc": uscc,
        "entity_type": entity.get("entity_type", ""),
        "source": entity.get("source", ""),
        "search_key": search_key,
        "crawled_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "fields": [t[2] for t in active_tools],
        "data": {},
        "no_match": {},
        "errors": {},
    }

    def task(server: str, tool: str, label: str):
        try:
            cli = get_client(server)
            result = cli.call_tool(tool, {"searchKey": search_key})
            return label, tool, parse_tool_result(result)
        except Exception as e:
            return label, tool, {"_error": f"task exception: {e}"}

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(task, s, t, l) for (s, t, l, _g) in active_tools]
        for fut in as_completed(futures):
            label, tool, parsed = fut.result()
            if isinstance(parsed, dict) and "_error" in parsed:
                record["errors"][label] = str(parsed["_error"])[:200]
            elif _is_no_match(parsed):
                record["no_match"][label] = True
            else:
                record["data"][label] = parsed

    return record


def load_progress() -> set[str]:
    if PROGRESS_FILE.exists():
        return set(json.loads(PROGRESS_FILE.read_text(encoding="utf-8")))
    return set()


def save_progress(done: set[str]):
    PROGRESS_FILE.write_text(json.dumps(sorted(done), ensure_ascii=False, indent=2), encoding="utf-8")


def log(msg: str):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def safe_filename(s: str) -> str:
    bad = '<>:"/\\|?*'
    for ch in bad:
        s = s.replace(ch, "_")
    return s[:120]


def load_entities() -> list[dict]:
    rows = []
    with INPUT_CSV.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows


def merge_all():
    """把 json/ 目录下所有文件合并"""
    all_records = []
    for fp in sorted(JSON_DIR.glob("*.json")):
        try:
            all_records.append(json.loads(fp.read_text(encoding="utf-8")))
        except Exception as e:
            log(f"merge: skip {fp.name}: {e}")
    MERGED_JSON.write_text(
        json.dumps(all_records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # 扁平化 CSV：每行一个实体，列为 工商.企业名称 / 工商.注册资本 / ...
    rows = []
    all_keys = set()
    for rec in all_records:
        flat = {
            "entity_name": rec.get("entity_name"),
            "uscc": rec.get("uscc"),
            "entity_type": rec.get("entity_type"),
            "crawled_at": rec.get("crawled_at"),
        }
        for label, payload in rec.get("data", {}).items():
            if isinstance(payload, dict):
                for k, v in payload.items():
                    col = f"{label}.{k}"
                    flat[col] = v if not isinstance(v, (list, dict)) else json.dumps(v, ensure_ascii=False)
                    all_keys.add(col)
            elif isinstance(payload, list):
                flat[f"{label}_count"] = len(payload)
                flat[f"{label}_raw"] = json.dumps(payload, ensure_ascii=False)
                all_keys.add(f"{label}_count")
                all_keys.add(f"{label}_raw")
        rows.append(flat)
    base_cols = ["entity_name", "uscc", "entity_type", "crawled_at"]
    cols = base_cols + sorted(all_keys)
    with MERGED_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    log(f"合并完成: {len(all_records)} 条 → {MERGED_JSON.name} / {MERGED_CSV.name}")


def _parse_manual_entity(raw: str) -> dict:
    """18 位字母数字识别为 USCC，否则当企业名。"""
    s = raw.strip()
    if len(s) == 18 and s.isalnum():
        return {"entity_name": "", "uscc": s, "entity_type": "", "source": "manual"}
    return {"entity_name": s, "uscc": "", "entity_type": "", "source": "manual"}


def main():
    ap = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--test", action="store_true", help="只跑名单前 5 条")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=None)
    ap.add_argument("--merge", action="store_true", help="只做合并")
    ap.add_argument("--workers", type=int, default=6, help="单实体内的工具并发数")
    ap.add_argument(
        "--entity",
        nargs="+",
        metavar="NAME_OR_USCC",
        help="手动抓取一个或多个实体（18 位字母数字识别为 USCC，否则当企业名）。不影响名单进度文件。",
    )
    ap.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="交互模式：启动后从控制台逐行输入公司名或 USCC，空行结束。",
    )
    ap.add_argument(
        "--entity-file",
        metavar="PATH",
        help="从文本文件读取实体（一行一条，# 开头视为注释）。",
    )
    ap.add_argument(
        "--list-fields",
        action="store_true",
        help="列出所有可选字段及其分组，然后退出。",
    )
    ap.add_argument(
        "--fields",
        nargs="+",
        metavar="字段名",
        help="只抓指定字段（中文名，空格或逗号分隔）。例：--fields 工商信息 股东信息 专利",
    )
    ap.add_argument(
        "--fields-group",
        nargs="+",
        metavar="分组名",
        dest="fields_group",
        help="按分组抓取（工商/经营/风险/知产，可多选）。例：--fields-group 工商 风险",
    )
    ap.add_argument(
        "--all-fields",
        action="store_true",
        dest="all_fields",
        help="跑全部 67 项字段（不传此开关时默认只跑核心 25 项，避免意外烧积分）。",
    )
    args = ap.parse_args()

    if args.list_fields:
        list_fields()
        return

    try:
        active_tools = resolve_tools(args.fields, args.fields_group, args.all_fields)
    except ValueError as e:
        print(f"错误：{e}")
        return

    total_tools = len(CORE_TOOLS)
    if len(active_tools) == total_tools:
        log(f"字段范围：全部 {total_tools} 项（--all-fields）")
    elif args.fields or args.fields_group:
        labels = "、".join(t[2] for t in active_tools)
        log(f"字段筛选：共 {len(active_tools)} 项 → {labels}")
    else:
        log(f"字段范围：推荐核心 {len(active_tools)} 项（加 --all-fields 可跑全部 {total_tools} 项）")

    if args.merge:
        merge_all()
        return

    manual_mode = bool(args.entity or args.interactive or args.entity_file)
    if manual_mode:
        raws: list[str] = []
        if args.entity:
            raws.extend(args.entity)
        if args.entity_file:
            fp = Path(args.entity_file)
            if not fp.exists():
                log(f"文件不存在: {fp}")
                return
            for line in fp.read_text(encoding="utf-8-sig").splitlines():
                s = line.strip()
                if s and not s.startswith("#"):
                    raws.append(s)
        if args.interactive:
            print("请输入公司名或 USCC（每行一条，空行或 Ctrl+Z 回车结束）:", flush=True)
            while True:
                try:
                    line = input("> ").strip()
                except EOFError:
                    break
                if not line:
                    break
                raws.append(line)
        if not raws:
            log("未收到任何实体，退出。")
            return
        entities = [_parse_manual_entity(e) for e in raws]
        done: set[str] = set()
        log(f"手动模式: {len(entities)} 条（不读写进度文件）")
    else:
        entities = load_entities()
        if args.test:
            entities = entities[:5]
        else:
            entities = entities[args.start : args.end]
        done = load_progress()
        log(f"待爬: {len(entities)} 条；已完成: {len(done)} 条")

    t0 = time.time()
    for i, ent in enumerate(entities, 1):
        key = ent.get("uscc") or ent["entity_name"]
        if not manual_mode and key in done:
            continue
        try:
            display = ent["entity_name"] or "(仅 USCC)"
            log(f"[{i}/{len(entities)}] {display} ({key})")
            rec = crawl_one(ent, max_workers=args.workers, tools=active_tools)
            ok = len(rec["data"])
            nm = len(rec["no_match"])
            err = len(rec["errors"])
            tag = ""
            if ok == 0 and nm > 0:
                tag = " ⚠ 全部无匹配（可能 USCC/名称错误）"
            log(f"   → 成功 {ok} 项 / 无匹配 {nm} 项 / 错误 {err} 项{tag}")
            # 文件名：企业中文名优先，没有才退回 USCC（仅 --entity 手动给 USCC 的情况）
            fname_base = ent["entity_name"] or ent.get("uscc") or "unnamed"
            fname = safe_filename(fname_base) + ".json"
            (JSON_DIR / fname).write_text(
                json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            if not manual_mode:
                done.add(key)
                if i % 5 == 0:
                    save_progress(done)
        except KeyboardInterrupt:
            log("用户中断，保存进度…")
            if not manual_mode:
                save_progress(done)
            return
        except Exception as e:
            log(f"   ! 失败: {e}")
    if not manual_mode:
        save_progress(done)
    elapsed = time.time() - t0
    log(f"全部完成。共 {len(entities)} 条，耗时 {elapsed:.1f}s（平均 {elapsed/max(1,len(entities)):.1f}s/条）")


if __name__ == "__main__":
    main()
