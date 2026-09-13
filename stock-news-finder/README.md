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
scripts/run.sh                          # 全流程：采集 → 词典 → LLM分类 → 打分报告
python3 scripts/import_sz.py            # 深市词典导入（已导入过则幂等跳过）
python3 scripts/lookup.py 立讯精密       # 公司名查代码
```

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
