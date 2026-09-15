# stock-news-finder

新闻 → 股票候选 的选股漏斗原型。

## 设计原则（两条硬约束）

1. **数据源可动态添加**：`sources.json` 配置驱动，加一个源 = 加一段 JSON，不改代码。
2. **公司词典文本化维护**：`data/companies.txt` 一行一只股票，手动增删改后重新运行即生效。

## 目录结构

```
stock-news-finder/
├── scripts/              # 全部可执行脚本
│   ├── run.sh            # 一键全流程（4 步）
│   ├── cron_run.sh       # 备用入口（带日志）
│   ├── fetch_news.py     # 采集层 loader（动态加载插件）
│   ├── build_dict.py     # 词典构建
│   ├── import_excel.py   # Excel 公司清单导入
│   ├── import_sz.py      # 深市公司全量导入
│   ├── llm_classify.py   # LLM 事件分类
│   ├── match_score.py    # 匹配打分 + 日报生成
│   ├── recommend.py      # 推荐层：信号提纯 + 三档推荐（★强推/★关注/★观察）
│   ├── review.py         # 验证层：次日行情复盘 + 分档命中率累计统计
│   ├── lookup.py         # 公司名→代码查询工具
│   └── product_lookup.py # 产品词→板块成分股工具
├── fetchers/             # 采集器插件（SPEC.md 为接口规范）
│   ├── eastmoney_fast.py
│   ├── wallstreetcn_live.py
│   ├── http_json.py      # 通用模板
│   └── file.py           # 本地文件模板
├── sources.json          # 新闻源配置（动态添加）
├── data/                 # 词典与缓存
├── raw/                  # 新闻历史归档（按日）
├── output/               # 当次运行产物
├── daily/                # 信号日报归档（按日）
├── 需求/需求.md          # 需求文档
└── 方案/概要设计.md      # 概要设计文档
```

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
```

## 法人司法风险层（P0 · 半自动）

- 数据链路：`signals` TOP30 → 东财 F10 拿法人/信用代码（7 天缓存）→
  `output/legal_pending_日期.md` 待核清单 → **人工查执行网**（失信/被执行/限高，
  验证码人点，结果按 `代码|法人|类型|案号|标的|立案日|原因` 格式回填）→
  `--result` 导入 → Mongo `stock` 库 + 4 列附录表 `output/legal_risk_日期.md`
- Mongo 表模型：`legal_companies`（画像，_id=股票代码）、`legal_risks`
  （唯一键 code+risk_type+case_no）、`legal_checks`（运行日志）；
  连接读 `MONGODB_URI`，不可用自动降级 `data/legal_fallback.jsonl`
- 「无风险」记录写进画像的 last_checked（7 天内免重查），风险记录永久累积

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
