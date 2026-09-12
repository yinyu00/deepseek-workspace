# FastGPT 知识库搭建实录（Windows Docker 部署）

> 记录日期：2026-08-28
> 环境：Windows 22H2 + WSL2 + Docker Desktop
> 模型：GLM-5.3 / GLM-5.3-flash（智谱订阅）+ text-embedding-v3（阿里百炼）
> 最终状态：✅ 全链路跑通（文档上传 → 向量化 → 语义检索 → 应用问答带引用）

---

## 一、背景与选型

**需求**：个人知识库（文档问答），Mac/Pad/Windows 多设备访问。

**选型结论**：FastGPT（中文生态好、Docker 一键部署、知识库可视化调试强、可接自有 API key）。

**架构**：

```
Windows (Docker)
├── fastgpt       :3000  ← Web UI
├── aiproxy       :3001  ← 模型网关（渠道管理）
├── sandbox              ← 文件解析（PDF/Word）
├── mongo (副本集)        ← 应用/会话数据
├── pg + pgvector        ← 知识库向量存储
└── redis                ← 登录会话
```

---

## 二、踩坑实录（按时间顺序，共 9 坑）

### 坑 1：Windows 版本太老（build 18363 = 1909）
- **症状**：`wsl --install` 报「命令行选项无效」
- **原因**：WSL2 要求 build 19041+，新版 Docker 要求 21H2+
- **解决**：下载官方 Win10 22H2 ISO 挂载安装升级（保留文件）或「不保留任何文件」重装

### 坑 2：阿里云镜像缺 mongo
- **症状**：`registry.cn-hangzhou.aliyuncs.com/fastgpt/mongo:7.0: not found`
- **解决**：三镜像改官方源
  - fastgpt → `ghcr.io/labring/fastgpt:v4.9.13`
  - mongo → `mongo:7.0`（Docker Hub）
  - pg → `pgvector/pgvector:0.8.0-pg15`

### 坑 3：config 配置文件格式过时
- **症状**：PG 报 `ECONNREFUSED`（实际连了默认 localhost）
- **原因**：v4.9.x 配置已从 `config.yaml` 改为 `config.json`（JSON5），且旧格式文件挂载后覆盖默认配置导致回退
- **解决**：从官方仓库 tag v4.9.13 下载 `projects/app/data/config.json`（约 1.1KB），放入 `config/config.json` 挂载
- **教训**：⚠️ 网上教程给的 GitHub raw 链接可能已 404（main 分支目录变更），要按 **tag** 拉

### 坑 4：环境变量名不匹配
- **症状**：Mongo 连接 `buffering timed out after 10000ms`
- **原因**：v4.9.13 官方变量名**无 FASTGPT_ 前缀**：`MONGODB_URI` / `PG_URL`（新分支才有前缀版）
- **解决**：双保险——两个名字都配上（`MONGODB_URI` + `FASTGPT_MONGODB_URI`）
- **同类坑**：登录密码变量是 `DEFAULT_ROOT_PSW`（没有结尾 D！）

### 坑 5：Mongo 需要副本集（事务支持）
- **症状**：`Transaction numbers are only allowed on a replica set member or mongos`
- **原因**：FastGPT 初始化要用事务，单机 mongod 默认不开副本集
- **解决**：`command: mongod --keyFile /data/mongodb.key --replSet rs0` + entrypoint 自动生成 keyFile 和 `rs.initiate`
- **附带坑 5b**：认证+副本集必须 keyFile（`security.keyFile is required when authorization is enabled with replica sets`）
- **附带坑 5c**：mongo:7.0 的 mongosh 中 `rs.status()` 无配置时会**抛异常**（旧版 mongo shell 只返回错误对象），官方初始化脚本要加 try/catch 才能兼容

### 坑 6：缺 Redis（会话存储）
- **症状**：登录报 `ECONNREFUSED 127.0.0.1:6379`
- **解决**：加 redis 服务（`redis:7-alpine` + `--requirepass`），fastgpt 环境变量加 `REDIS_URL=redis://default:密码@redis:6379`

### 坑 7：模型管理入口找不到 GLM
- **原因**：v4.9.x 模型管理拆分到 aiproxy，但配置入口在 **FastGPT 自己的页面**（账号 → 模型提供商），不在 aiproxy 的 web 界面
- **解决**：补 aiproxy + aiproxy_pg 两个容器，然后全部在 FastGPT 页面里配

### 坑 8：文件上传缺 sandbox
- **症状**：上传只有「文本数据集/空白数据集」，无文件选项
- **解决**：补 `fastgpt-sandbox` 容器 + fastgpt 环境变量 `SANDBOX_URL=http://sandbox:3000`

### 坑 9：上传报 `System unset FILE_TOKEN_KEY`
- **解决**：fastgpt 环境变量补齐三密钥：`TOKEN_KEY` / `ROOT_KEY` / `FILE_TOKEN_KEY`（各一串随机字符），改后必须 `docker compose up -d` 重建（restart 不生效）

---

## 三、最终 docker-compose.yml（完整可用版）

```yaml
name: fastgpt

services:
  fastgpt:
    image: ghcr.io/labring/fastgpt:v4.9.13
    container_name: fastgpt
    restart: always
    ports:
      - "3000:3000"
    networks: [fastgpt]
    depends_on:
      mongo: { condition: service_healthy }
      pg: { condition: service_healthy }
      sandbox: { condition: service_started }
    environment:
      - FASTGPT_MODE=production
      - PORT=3000
      - MONGODB_URI=mongodb://root:密码@mongo:27017/fastgpt?authSource=admin
      - FASTGPT_MONGODB_URI=mongodb://root:密码@mongo:27017/fastgpt?authSource=admin
      - PG_URL=postgresql://postgres:密码@pg:5432/fastgpt
      - FASTGPT_PG_URL=postgresql://postgres:密码@pg:5432/fastgpt
      - REDIS_URL=redis://default:密码@redis:6379
      - SANDBOX_URL=http://sandbox:3000
      - AIPROXY_API_ENDPOINT=http://aiproxy:3000
      - AIPROXY_API_TOKEN=aiproxy
      - TOKEN_KEY=随机串1
      - ROOT_KEY=随机串2
      - FILE_TOKEN_KEY=随机串3
      - DEFAULT_ROOT_PSW=网页登录密码    # 注意：无结尾 D
      - FASTGPT_LOCAL_STORE_PATH=/app/data
    volumes:
      - fastgpt_data:/app/data
      - ./config:/app/data/config:ro

  mongo:
    image: mongo:7.0
    container_name: fastgpt_mongo
    restart: always
    networks: [fastgpt]
    command: mongod --keyFile /data/mongodb.key --replSet rs0
    environment:
      - MONGO_INITDB_ROOT_USERNAME=root
      - MONGO_INITDB_ROOT_PASSWORD=密码
    volumes: [mongo_data:/data/db]
    entrypoint:
      - bash
      - -c
      - |
        openssl rand -base64 128 > /data/mongodb.key
        chmod 400 /data/mongodb.key
        chown 999:999 /data/mongodb.key
        echo 'let isInited = 0
        try { isInited = rs.status().ok } catch(e) { isInited = 0 }
        if(!isInited){
          rs.initiate({
            _id: "rs0",
            members: [ { _id: 0, host: "mongo:27017" } ]
          })
        }' > /data/initReplicaSet.js
        exec docker-entrypoint.sh "$$@" &
        until mongosh -u root -p 密码 --authenticationDatabase admin --eval "print('waited')" &>/dev/null; do
          sleep 2
        done
        mongosh -u root -p 密码 --authenticationDatabase admin /data/initReplicaSet.js || true
        wait $$!
    healthcheck:
      test: ["CMD", "mongosh", "--eval", "db.adminCommand('ping')"]
      interval: 10s
      timeout: 5s
      retries: 5

  pg:
    image: pgvector/pgvector:0.8.0-pg15
    container_name: fastgpt_pg
    restart: always
    networks: [fastgpt]
    environment:
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=密码
      - POSTGRES_DB=fastgpt
    volumes: [pg_data:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    container_name: fastgpt_redis
    restart: always
    networks: [fastgpt]
    command: --requirepass 密码
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "密码", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  sandbox:
    container_name: sandbox
    image: ghcr.io/labring/fastgpt-sandbox:v4.9.11
    networks: [fastgpt]
    restart: always

  aiproxy:
    image: ghcr.io/labring/aiproxy:v0.1.7
    container_name: aiproxy
    restart: unless-stopped
    depends_on:
      aiproxy_pg: { condition: service_healthy }
    networks: [fastgpt]
    ports: ["3001:3000"]
    environment:
      - ADMIN_KEY=aiproxy
      - LOG_DETAIL_STORAGE_HOURS=1
      - SQL_DSN=postgres://postgres:aiproxy@aiproxy_pg:5432/aiproxy
      - RETRY_TIMES=3
      - BILLING_ENABLED=false
      - DISABLE_MODEL_CONFIG=true
    healthcheck:
      test: ['CMD', 'curl', '-f', 'http://localhost:3000/api/status']
      interval: 5s
      timeout: 5s
      retries: 10

  aiproxy_pg:
    image: pgvector/pgvector:0.8.0-pg15
    container_name: aiproxy_pg
    restart: unless-stopped
    networks: [fastgpt]
    volumes: [aiproxy_pg_data:/var/lib/postgresql/data]
    environment:
      TZ: Asia/Shanghai
      POSTGRES_USER: postgres
      POSTGRES_DB: aiproxy
      POSTGRES_PASSWORD: aiproxy
    healthcheck:
      test: ['CMD', 'pg_isready', '-U', 'postgres', '-d', 'aiproxy']
      interval: 5s
      timeout: 5s
      retries: 10

networks:
  fastgpt: { driver: bridge }

volumes:
  fastgpt_data:
  mongo_data:
  pg_data:
  aiproxy_pg_data:
```

**config/config.json**（放同目录 config 文件夹，内容取自官方 v4.9.13 tag 的 `projects/app/data/config.json`）。

---

## 四、模型配置（FastGPT 页面内）

入口：登录 → 右上角头像 → 账号 → **模型提供商**（不是 aiproxy 的 web 界面！）

### 第 1 步：模型配置（定义模型身份）

| 模型 | 类型（FastGPT 叫法） | 关键开关 |
|---|---|---|
| glm-5.3 | 语言模型 | 启用 |
| glm-5.3-flash | 语言模型 | **支持视觉=开**（图片理解用） |
| text-embedding-v3 | **索引模型**（=embedding） | — |

> 注意：FastGPT 把 embedding 叫「**索引模型**」；图片模型下拉框只显示开了「支持视觉」的语言模型。

### 第 2 步：模型渠道（怎么调上游）

| 渠道 | 协议 | 地址 | Key |
|---|---|---|---|
| 智谱 GLM | OpenAI | `https://open.bigmodel.cn/api/paas/v4` | 智谱 key（订阅同款） |
| 阿里百炼 | OpenAI | 百炼 MaaS 专属地址或 `https://dashscope.aliyuncs.com/compatible-mode/v1` | 百炼 key |

### 第 3 步：启用 + 测试

- 模型配置里逐个点「启用」（**不启用不会出现在各处下拉框！**）
- 渠道 → 模型测试 → 全绿

---

## 五、知识库建库与调参

### 建库参数

| 项 | 值 | 说明 |
|---|---|---|
| 向量模型 | text-embedding-v3 | 建库后不可换 |
| 上传方式 | 文件数据集 | 需要 sandbox 容器 |
| 处理方式 | **分块储存** | 保真、省钱；QA 提取适合 FAQ 场景 |
| 分块上限 | **1000** | 默认 512~800 均可；20000 太大会导致语义稀释 |

### 搜索测试调参（踩过的坑）

| 参数 | 推荐值 | 坑 |
|---|---|---|
| 搜索方式 | 语义检索 | 诊断时单独测；混合检索需重排模型 |
| 最低相关度 | **0.4** 左右 | 相关块分数 ~0.57 时 0.4 合适；设 0 会召回一大堆 |
| 引用上限 | 最低 UI 限制 100 | 实际靠相关度阈值过滤，无碍 |
| 问题优化 | 关 | 每次搜索多跑一次 LLM，慢 4 秒+烧 token |

**诊断口诀（检索层出问题时）**：
1. 看分块内容 → 空的 = 解析问题
2. 语义 vs 全文对比 → 语义空全文有 = 向量化失败；都空 = 内容没入库
3. 模型提供商 → 调用日志 → 看实时请求报错

### 应用层报错速查

| 报错 | 原因 |
|---|---|
| `max_tokens参数非法：限制数值范围[1,131072]` | 应用/模型配置里最大回复填了 0 或超大值，改 4096 |
| `(aiproxy: xxx)` 开头的 400 | 请求参数被上游拒绝，对照报错范围改配置 |

---

## 六、常用运维命令（PowerShell）

```powershell
docker compose ps                    # 容器状态
docker compose logs -f fastgpt       # 看日志
docker compose up -d                 # 改配置后重建（restart 不会应用新环境变量！）
docker compose down                  # 停止（数据保留）
docker compose down -v               # 停止+删卷（危险：数据全没，初始化失败时救急用）
docker compose pull; docker compose up -d   # 升级
```

**改环境变量三步曲**：改 yml → `up -d` 重建 → `docker compose exec fastgpt env | findstr "XXX"` 验证。

---

## 七、多设备访问

- 局域网：`http://Windows内网IP:3000`（防火墙放行 3000）
- 异地：Tailscale 组网后访问 `http://100.x.x.x:3000`（本机部署 IP：100.123.144.30）
- Mac 上的 DSH 会话远程访问：SSH 隧道 `ssh -N -L 3080:127.0.0.1:3080 jinwei@<Mac的TS IP>`

---

## 八、已入库文档

| 文档 | 类型 | 说明 |
|---|---|---|
| 特药流程.pdf | 文件数据集 | 人保癌症院外特药保险服务手册（20页），报销比例/审核时效等问题验证通过 |
| 小冰冰泰坦图鉴.md | 文件数据集 | 泰坦英雄培养指南（含FAQ节提升口语化检索命中） |

### 验收测试题（升级/换模型时做回归测试）

| # | 测试题 | 类型 | 验收标准 |
|---|---|---|---|
| 1 | 特药报销比例是多少？ | 单跳检索 | 答出 100%/60%/100% 三种情形，带引用 |
| 2 | 用药合理性审核多长时间完成？ | 单跳检索 | 答出「1 个工作日」（不与 CAR-T 的 20-30 天混淆） |
| 3 | 申请特药需要准备哪些材料？ | 单跳检索 | 列出理赔申请书、身份证复印件等 6 项 |
| 4 | 领药二维码有效期多久？ | 单跳检索 | 答出「30 日内」 |
| 5 | CAR-T 治疗后需要注意什么？这些注意事项分别是因为什么风险？ | **多跳推理** | 5 条注意事项全出 + 因果串联（监测10天←CRS+神经毒性、禁驾8周←神经毒性突发、居住2小时车程←及时救治）。glm-5.3 实测通过：模型自行补全了文档未明说的因果链 |
| 6 | 泰坦里哪个最值得先练？ | 跨库检索 | 答出德鲁伊/繁星公主 + 星级建议 |

**多跳题（第 5 题）评分要点**：文档只写了注意事项清单，「注意事项→对应风险」的关联需要模型把「不良反应类型」段落交叉推理补全——这是检验「检索+思考模型」组合多跳能力的标尺。2026-08-28 实测 glm-5.3 得分 9/10。 |

## 九、后续规划

- [ ] 混合检索 + 重排模型（硅基流动免费 `BAAI/bge-reranker-v2-m3`）
- [ ] Neo4j 图数据库预留位（多跳推理需求出现时启用）
- [ ] 定期备份 mongo_data / pg_data 卷
- [ ] 百炼 key 轮换（聊天记录暴露过明文）
