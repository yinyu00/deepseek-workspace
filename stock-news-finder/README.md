# stock-news-finder

新闻 → 股票候选 的选股漏斗原型。

## 设计原则（两条硬约束）

1. **数据源可动态添加**：`sources.json` 配置驱动，加一个源 = 加一段 JSON，不改代码。
2. **公司词典文本化维护**：`data/companies.txt` 一行一只股票，手动增删改后重新运行即生效。

## 目录结构

```
stock-news-finder/
├── scripts/                 # 全部可执行脚本
│   ├── run.sh / cron_run.sh # 一键全流程 / 备用入口
│   ├── fetch_news.py        # 采集层 loader（动态加载 11 源插件）
│   ├── build_dict.py / import_sz.py / import_excel.py / lookup.py / expand_products.py
│   ├── llm_classify.py      # LLM 事件分类（免费 glm-4v-flash，失败降级正则）
│   ├── match_score.py       # 匹配打分 + 信号日报（含 HITL 歧义挂起）
│   ├── recommend.py         # 推荐层（★强推/★关注/★观察 + 回避区 + 联动池）
│   ├── review.py            # 验证层（次日行情复盘 + 命中率累计）
│   ├── ent_mine.py          # 实体累积层①②③通道（公司新闻/人物/关联）
│   ├── legal_check.py       # 法人风险 P0（画像 + 待核清单 + Mongo 入库）
│   ├── qcc_legal_check.py   # 法人风险 P1（企查查 MCP 精查，Token 池）
│   ├── hitl_review.py       # HITL 判定导入（标注库沉淀）
│   ├── push_channels.py / push_daily.py / push_md.py / report_calendar.py
│   ├── export_sync.py       # 跨机同步打包（JSONL → FTP）
│   └── product_lookup.py    # 产品词→板块成分股
├── scripts-win/import_to_mongo.py  # Windows 侧 Mongo 幂等导入
├── fetchers/                # 采集器插件（SPEC.md 为接口规范，11 源 + 2 模板）
├── tools/qcc-mcp-batch/     # 企查查 MCP 批量抓取工具（多账号 Token 池）
├── sources.json             # 新闻源配置（动态添加）
├── data/                    # 词典与缓存（companies/products/zhihu_people/macro 等）
├── raw/                     # 新闻历史归档（按日）
├── output/                  # 当次运行产物（不入库）
├── daily/                   # 信号/推荐/复盘日报归档（按日）
├── 需求/                    # 需求.md · 代办.md
├── 方案/                    # 概要设计.md · 接口方案.md · Mongo数据模型.md · 流程图.md
└── 维护/                    # 操作手册.md
```

## 文档索引

> **文档即事实源**：凭需求 + 方案两份文档可重建并运行整个项目。新会话/跨机接手从
> `代办.md` 入手最快（活 backlog + 会话交接备忘）。

| 文档 | 定位 | 关键内容 |
|---|---|---|
| [需求/需求.md](需求/需求.md) | **做什么**（唯一事实源①） | F 编号功能清单（3.1~3.10）、D 编号决策记录、R 编号风险 |
| [需求/代办.md](需求/代办.md) | **接下来做什么** | P0/P1/P2 分级待办 + 完成归档（带提交号）+ 会话交接备忘 |
| [方案/概要设计.md](方案/概要设计.md) | **为什么这样设计**（唯一事实源②） | 模块设计（2.1~2.12）、ent/legal 表模型、FastGPT 桥接、决策对照 |
| [方案/接口方案.md](方案/接口方案.md) | 全部对外 HTTP API 契约 | 地址/出入参/报文样例/坑；接口编号 I-xx，**先改本文再写码** |
| [方案/Mongo数据模型.md](方案/Mongo数据模型.md) | 数据库与跨机同步设计 | FTP 中转批量同步链路、文件第一事实源原则、幂等导入 |
| [方案/流程图.md](方案/流程图.md) | 每日运行时数据流 | pipeline 全链路 mermaid（v0.9） |
| [维护/操作手册.md](维护/操作手册.md) | 日常运维一站式手册 | 部署/测试验证清单/日常操作/排障速查（Windows 主力 · Mac 验证） |
| [fetchers/SPEC.md](fetchers/SPEC.md) | 采集插件接口规范 | fetch(cfg)/selftest() 契约，新源零侵入 |
| [tools/qcc-mcp-batch/README.md](tools/qcc-mcp-batch/README.md) | 企查查批量工具 | 67 字段清单、Token 池配置、积分模型、断点续爬 |

## 使用

```bash
cd stock-news-finder
scripts/run.sh                          # 全流程：采集 → 词典 → LLM分类 → 打分 → 推荐 → 推送 → 日历 → 复盘
python3 scripts/recommend.py            # 单跑推荐层（读最新 signals）
python3 scripts/review.py               # 单跑复盘（拉东财行情回看最近一份推荐）
python3 scripts/import_sz.py            # 深市词典导入（已导入过则幂等跳过）
python3 scripts/lookup.py 立讯精密       # 公司名查代码
python3 scripts/legal_check.py          # 法人风险：TOP30 画像拉取 + 待核清单生成
python3 scripts/legal_check.py --result output/legal_pending_日期.md   # 人工核查结果入库 + 附录表
python3 scripts/ent_mine.py             # 实体累积：今日新闻→ent_company_news（每日跑）
python3 scripts/ent_mine.py --backfill  # 历史归档一次性回填
python3 scripts/ent_mine.py --seed-person  # F10法人→ent_person_company 官方种子
```

## 法人司法风险层（三级防线）

| 级别 | 通道 | 方式 | 状态 |
|---|---|---|---|
| **P0.5 自动** | 巨潮 searchkey 司法风险公告（`cninfo-legal`，2026-09-15 上线）：诉讼/冻结/破产重整/司法拍卖全文搜索，30 天窗口 | 公司自披露 → 负面事件（诉讼仲裁-2.5/资产风险-3.0）→ 推荐回避区 | ✅ 91条/30天，78 只股自动预警 |
| **P0 半自动** | legal_check.py（2026-09-15 上线）：`signals` TOP30 → 东财 F10 拿法人/信用代码（7 天缓存）→ `output/legal_pending_日期.md` 待核清单 → **人工查执行网**（失信/被执行/限高，验证码人点，结果按 `代码|法人|类型|案号|标的|立案日|原因` 格式回填）→ `--result` 导入 → Mongo `stock` 库 + 4 列附录表 `output/legal_risk_日期.md` | 补查「无披露」公司（未达披露标准的被执行） | ✅ |
| **P1 企查查MCP** | qcc_legal_check.py（2026-09-15 上线，Windows 运行）：recommend TOP20 → F10画像 → 15天缓存过滤 → 企查查 MCP 精查 4 字段（工商信息/失信/被执行人/限高，4 积分/家×20=80 积分/天 < 每日赠送100）→ 风险报告 `output/qcc_legal_日期.md` + legal_risks 回写（source: qcc-mcp） | token 配置：tools/qcc-mcp-batch/config.json（登录 agent.qcc.com 领取，gitignore）；依赖 `pip install requests`；运行 `python scripts\qcc_legal_check.py [--date yyyymmdd] [--dry-run]` | ✅ 待 token |
| **P1'' 执行网全自动** | zxgk_check.py（2026-09-17 立项，方案 A）：playwright 真浏览器过瑞数 + GLM-4v-flash 单图识别滑块缺口（⚠️双图并发触发 16K 限制 400）+ 拟人轨迹（easeOut+y抖动）→ searchSX 会话复用批量查询 → legal_risks(source: zxgk-auto) + 15天缓存 | Windows：`pip install playwright && playwright install chromium`；运行 `python scripts\zxgk_check.py [--one 名字|--names a,b]`；滑块3次失败自动提示转人工 | 🔨 Mac 审计通过待 Windows 实测 |

- P0 Mongo 表模型：`legal_companies`（画像，_id=股票代码）、`legal_risks`
  （唯一键 code+risk_type+case_no）、`legal_checks`（运行日志）；
  连接读 `MONGODB_URI`，不可用自动降级 `data/legal_fallback.jsonl`
- 「无风险」记录写进画像的 last_checked（7 天内免重查），风险记录永久累积
- **v0.8.1 关键改动**：signals 顺产改为「正分 TOP100 + 负分 TOP20」——
  纯负面股（司法风险）此前进不了正序 TOP100，回避区永远看不到它们；
  另 `SKIP_PRODUCTS=1` 跳过产品传导通道（网络差时全流程几分钟→30秒）
- 巨潮诉讼类 category 参数无效（回退默认流），必须 searchkey（实测）

## 互动易 / 机构调研通道（2026-09-14 上线，批次二）

- **互动易**（`irm-qa`）：深交所互动平台董秘问答（irm.cninfo.com.cn 公开
  接口，空关键词=全量时间流）。只收已回复的（attachedContent），强信号
  关键词过滤（订单/产能/AI/回购等，防"股价为什么不涨"类垃圾提问刷屏）。
  事件兜底 1.0「互动易回复」——内容判断交给 LLM 层。
  ⚠️ 回复有延迟+周末积压，时间边界必须回看 lookback_days（默认3天）。
  上证e互动（sns.sseinfo.com）接口已改版全挂，沪市口径暂缺
- **机构调研**（`org-survey`）：东财 RPT_ORG_SURVEYNEW 一手披露，
  ≥3 家机构才收，同股同日多条去重保最大值；董事长/总经理接待打标。
  事件 `机构调研`（1.8）入推荐层强事件——机构关注先行指标
- 两者均享一手源 ×1.5 权威加成；信号源 7 → 9
- 上线效果：★★★ 榜单从单一新闻驱动 → 并购/订单 × 新闻、机构调研热度、
  龙虎榜资金三路交叉验证（广汽集团 3源×6强事件、赛分科技 机构调研×11）

## 新浪7x24 / 龙虎榜通道（2026-09-14 上线，批次一）

- **新浪 7x24**（`sina-live`）：实时快讯，替代财联社电报（其免费接口
  2026 年已全关 404，签名版也不可用）。zhibo.sina.com.cn 公开 JSON 无签名，
  【】内标题自动拆分，page 翻页默认 20 页≈1000 条
- **龙虎榜**（`longhubang`）：资金面验证通道，东财 datacenter 接口拉最近
  交易日榜单（自动回退找交易日，84 只/日），每只一条：净买方向+金额+机构
  参与在标题（供正则分级），榜后 1 日涨幅在 body。事件规则：净买入→
  `资金异动`(2.0) / 净卖出→`资金流出`(-2.0)，均享一手源 ×1.5 权威加成；
  `资金异动` 在推荐层算强事件（可与新闻事件交叉验证升 ★★★）
- 信号源从 4 → 7：东财快讯 / 巨潮公告 / 龙虎榜 / 新浪7x24 / 华尔街见闻 /
  东财宏观搜索 / 知乎想法

## 巨潮公告通道（cninfo-announce）

一手信息源（新闻是二手转述），2026-09-14 上线：

- **双通道**：watchlist 自选股近 3 天全量公告 + 全市场高价值类别
  （业绩预告/权益分派/股权激励/增发）标题关键词过滤（防 2000+条/天刷屏）
- **权威性加成**：match_score 对公告源事件权重 ×1.5（官方确认实施 vs 新闻传闻）
- **词典外发现**：官方标注代码不要求在词典内（A股代码段白名单 60/68/00/30，
  排除 ETF），公司名从公告 body「名称（代码）」自动提取
- PDF 直链可点击；踩坑：巨潮 WAF 必须带 Referer，seDate 必须紧凑格式
  `2026-09-12~2026-09-14`，stock 参数必须 `代码,orgId`（topSearch 现查）
- 维护：watchlist 就是 data/watchlist.json（财报日历共用）；类别/关键词在
  sources.json 的该源配置里改



## 推荐层说明（recommend.py）

信号漏斗之上的最后一层，回答「今天真正值得研究哪几只」：

- **信号提纯**：仅靠产品传导（板块联动蹭热点）命中的股票不进推荐，
  单独列「板块联动池」——解决旧日报 TOP30 被同分板块股刷屏的噪声问题
- **事件分级**：强事件（订单/政策/业绩/并购/回购/产品进展）才作推荐依据，
  弱事件（一般资讯/机构评级）只作热度
- **交叉验证**：≥2 个独立新闻源的正面信号加成（单一来源易是软文）
- **连续性加成**：近 3 个信号文件反复出现 → 热度持续标记
- **三档输出**：★★★ 强推（强事件≥2 + 交叉验证）/ ★★ 关注（有强事件）/
  ★ 观察（其余正分）；负面主导进「回避区」
- 产物：`output/recommend_yyyymmdd.json` + `daily/recommend_yyyymmdd.md`

## 验证层说明（review.py）

- 次日拉东财 push2 批量行情（curl 子进程 + 代理/直连 + 多节点重试），
  回看昨日各档推荐的实际涨跌
- 命中口径：涨幅 > 0 计命中；分档统计当日 + 累计命中率/平均涨幅
  （`output/review_stats.json`），用于后续调推荐阈值
- 产物：`daily/review_yyyymmdd.md`

## LLM 分类层说明

- 用 glm-4v-flash（免费），key 读环境变量 `GLM_VISION_API_KEY`（本机在 ~/.zshrc）
- 只送「预匹配到词典股票」的新闻（56/200 条），7 个批次跑完，零成本
- 每条新闻输出：涉及股票 / 事件类型（9 类枚举）/ 影响分 -5~5 / 置信度 / 理由
- 无 key 或调用失败自动降级回正则规则，主流程不中断
- 打分公式：`LLM影响分 × 置信度 × 命中强度 × 3天时效衰减`

## 产品传导通道（data/products.txt）

- 新闻中出现产品词（如"固态电池"）→ 自动查东财对应板块 → 全部成分股关联
- 传导命中权重 0.6（低于直接命中 1.0），报告标注 `[经产品传导:产品名]`
- 成分股当日缓存（data/board_cache.json）；维护产品词：products.txt 一行一个
- 板块成分含深市股票，当前仅沪市词典内公司会被关联（深市词典待补）

## 已知网络坑

- 东财 push2 CDN 对本机不稳定：product_lookup.py 用 curl 子进程 + 代理/直连
  + 80/90 双节点全排列重试（urllib 直连常瞬断，勿改回）
- 公司 TLS 拦截（Windows）：部分域名 curl(schannel) 握手直接失败（rc=35），
  统一兜底策略 = curl 失败后降级 Python urllib + unverified + SECLEVEL=1
  （zhihu_pins.py、eastmoney_search.py 已内置，新插件照抄 `_get_json`/`_http_get`）
- 知乎：关注流/回答/文章接口匿名返回空或 401，仅「想法 pins」接口匿名可用（D17）

## companies.txt 格式

```
# 股票代码 股票名 别名1,别名2（别名可选，# 开头为注释）
300750 宁德时代 宁德,CATL
600941 中国移动 移动,中移动
```

## sources.json 格式

type 支持：
- `eastmoney-fast`：东财财经快讯（内置解析）
- `zhihu-pins`：知乎关注人「想法」（清单 `data/zhihu_people.txt`，一行一人：`url_token 显示名`；匿名接口，回答/文章需登录暂不支持）
- `http-json`：任意返回 JSON 数组的 HTTP 接口，`fields` 指定标题/正文/时间字段映射
- `file`：本地 JSON/JSONL 文件（调试或离线数据用）

```json
[
  {"name": "东财快讯", "type": "eastmoney-fast", "enabled": true},
  {"name": "自定义接口", "type": "http-json", "url": "https://...", "fields": {"title": "t", "body": "c", "time": "ts"}, "enabled": false}
]
```
