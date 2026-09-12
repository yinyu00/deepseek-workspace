# FastGPT 部署速查（Windows）

## 目录结构（放 D:\fastgpt\）

```
D:\fastgpt\
├── docker-compose.yml
└── config\
    └── config.yaml
```

## 部署步骤

```powershell
cd D:\fastgpt
docker compose up -d        # 首次拉镜像 5-20 分钟
docker compose ps           # 三个容器都应 Up (healthy)
```

访问：http://localhost:3000 （账号 root / 你设的 DEFAULT_ROOT_PSWD）

## 模型接入（网页后台 → 账号 → 模型配置）

### 对话模型（GLM）
- 类型: chat | 模型ID: glm-5.3（或 glm-5.3-flash）
- Base URL: https://open.bigmodel.cn/api/paas/v4
- Key: 智谱 API Key（ZAI_CODING_CN_API_KEY 同一个）
- 上下文: 1000000 | 最大输出: 131072

### 向量模型（阿里云百炼）
- 类型: embedding | 模型ID: text-embedding-v3
- Base URL: https://dashscope.aliyuncs.com/compatible-mode/v1
- Key: 百炼 API Key（modlens 同一个）
- 维度: 1024

## 常用命令

```powershell
docker compose ps            # 状态
docker compose logs -f fastgpt   # 看日志
docker compose down          # 停止（数据保留在卷里）
docker compose pull && docker compose up -d   # 升级
```

## 局域网/远程访问

- Mac/Pad 浏览器: http://100.87.235.73:3000 （Windows 的 Tailscale IP）
- 首次需在 Windows 防火墙放行 3000 端口（专用网络）
- 出门在外：两端都在尾网即可直连，无需公网

## 数据备份

数据都在 docker 卷：mongo_data / pg_data / fastgpt_data
```powershell
docker compose down
# 直接压缩 D:\fastgpt 整个目录 + 卷数据（wsl --export 或 Docker Desktop 图形界面备份）
docker compose up -d
```

## Neo4j 预留位（暂不启用，需要时加）

见 docker-compose.yml 注释；或新建 neo4j 服务（2C4G 限额），
浏览器管理: http://localhost:7474
