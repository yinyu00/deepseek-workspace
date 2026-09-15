---
name: user-profile
description: 当前用户（jinwei）的偏好与环境画像。任何新会话开始处理任务前应了解这些背景，避免反复询问已知信息。用户说"我的偏好/环境/背景"或任务涉及环境判断时加载本 skill。
---

# 用户画像：jinwei

## 职业背景（核心）

- **系统架构师，电信领域**
- 业务域 A —— **App 线上业务办理**：充值、缴费、套餐订购等电信 BSS 类交易链路
- 业务域 B —— **用户运行数据采集与分析**：用户订购了什么业务、消费水平、
  行为数据的采集建模与运营分析（偏 ODS/数仓/用户画像方向）
  - 功能版图**参考神策数据（Sensors Data）**的产品体系：埋点采集（全端
    SDK、可视化埋点）、事件模型（Event-User 模型）、用户分群/标签、
    行为分析（事件分析、漏斗、留存、路径、分布）、用户画像、A/B 实验、
    数据看板等
  - 讨论分析功能时可直接对标神策的概念体系（事件/用户模型、分群、漏斗留存等）
- 技术讨论可假设其熟悉：高并发交易系统、数据管道/数仓分层、BSS/OSS 概念、
  运营商业务术语（BOSS、CRM、账务、开通/变更流程等）
- 给方案时偏好**架构视角**：分层、链路、扩展性、数据流转，而非只看单点实现

## 沟通偏好

- 中文交流，喜欢**表格对比**的呈现方式（价格、方案对比等）
- 回答要**直接给结论**，再附原因和细节
- 动手类任务（改配置/装环境）直接做，操作涉及工作区外文件时先说明理由再执行
- 对成本敏感：偏好免费/包月方案，按量付费要给价格对照
- **git 推送需确认**（2026-09-14 起）：本地提交可自动完成，但 `git push`
  必须等用户明确说「推送/提交同步」后才执行，且**推送前必须先给用户确认
  待推送文件列表**（含改动摘要），不要连提交带推送一气呵成
- **文档先行**（2026-09-14 起）：项目迭代必须先输出/更新需求设计文档
  （增量章节），经用户确认后再写业务代码；禁止先实现后补文档。
  对话内头脑风暴不等于文档确认
- **文档即事实源**（2026-09-15 起）：需求文档 + 方案文档是项目唯一事实源，
  凭这两份文档要能完整重建项目所有脚本并运行。任何新增脚本/外部接口/
  表结构/环境依赖，必须同步写进方案文档再推送，否则视为工作未完成

## 机器环境

### 当前主力机（Windows，2026-09-13 起）

- Windows 11，用户 `jinwei`，普通权限（无管理员，服务操作/驱动安装需用户手动 UAC）
- 工作区：`D:\ai\deepseek-harness\workspace`（git 仓库，远程 git@github.com:yinyu00/deepseek-workspace.git，SSH 已配好可直推）
- Python 3.14（`python`，无 python3 命令；控制台需 `PYTHONIOENCODING=utf-8` 防 GBK 崩）
- dsh 启动：`pnpx @deepseek-ai/dsh web`（端口 3080）
- **网络有 TLS 拦截**（公司防火墙）：pip/curl/urllib 直连外网常失败；
  git 已切 `http.sslBackend openssl`；python 调 API 需 SSL 降级重试（llm_classify.py 已内置）
- 模型配置同步方式：**直接复制**（`Copy-Item dsh-config\settings.yaml $env:USERPROFILE\.dsh\settings.yaml`），
  不用软链（mklink 需管理员）；DSH 实时读取无需重启
- 已配置环境变量：`GLM_VISION_API_KEY`（setx 永久，2026-09-13 更新过新 Key）
- 装的办公软件：WPS（无 MS Office）；标签打印机佳博 GP-1324D（USB，80×60mm 标签纸）
- **yishan 箱单标签打印工具**：`yishan_print\箱单标签批量打印.exe`（C# WinForms 绿色单文件，
  原生GDI直打，源码 src\LabelPrinter.cs，README 有完整说明）

### 旧机（Mac Apple Silicon，备用参考）

- shell 是 zsh（`~/.zshrc`），包管理 pnpm / pnpx
- 系统开了全局代理（`ALL_PROXY` / `HTTP_PROXY` / `HTTPS_PROXY`）
- 工作区：`/Users/jinwei/ai/deepseek/harness/workspace`
- DSH 源码 checkout（只读参考）：`/Users/jinwei/git/github/deepseek-ai/deepseek-harness/`
- 环境恢复手册：workspace 根目录《环境切换.md》（Mac + Windows 双平台步骤）

## DSH 配置现状（~/.dsh/settings.yaml）

- `zai-coding-cn`（glm 包月 Coding Plan），**默认模型 glm-5.3**
- 2026-09-08 起 provider 配置了 `models` 白名单，下拉**只保留
  `glm-5.3` 和 `glm-5.3-flash`** 两个（旧记录"glm-5.3 不要了"已过时作废）
- `glm-vision`：open.bigmodel.cn 按量，目前只有 `glm-4v-flash`（免费识图，
  上下文 16K——大图必须先走 `glm4v-image-compress` skill 压缩）
- GLM 视觉 Key 在环境变量 `GLM_VISION_API_KEY`（launchctl + ~/.zshrc 双写）
- dsh 升级后 `~/.dsh` 曾被重置，旧会话备份在 `~/.dsh.backup`（2026-09-08
  已把其中 10 个历史会话拷回 `~/.dsh/sessions` 恢复）

## 已知工作习惯

- 界面已加宽到 1500px（skill `dsh-width-1500`），升级后需重跑
- 喜欢把重复性操作沉淀成 skill（宽度调整、图片压缩都是这么来的）
- 会贴图要求解析：大图走压缩流程；明确要求"不用插件"时指不要 modlens，改调 GLM API
- 用中文短指令驱动（如 "dsh-width-1500"），偶尔有笔误（dah→dsh）

## 修正记录

- 2026-08-22 首次创建（由会话总结生成）
- 2026-08-22 用户补充职业背景：系统架构师，电信领域（App 业务办理 +
  用户运行数据采集分析）
- 2026-08-22 补充：用户分析功能版图参考神策数据（埋点、事件模型、
  分群、漏斗/留存/路径分析、画像、A/B 实验等）
- 2026-09-08 模型配置调整：zai-coding-cn 只保留 glm-5.3 + glm-5.3-flash，
  默认模型 glm-5.3（作废旧记录"glm-5.3 不要"）；同时记录 ~/.dsh.backup
  会话恢复事件
- 2026-09-09 界面宽度：消息区改为 `列宽 × .85`（0.1.2-rc.1 起 CSS 变量是
  clamp 公式而非固定 748px，旧 dsh-width-95p skill 的步骤已过时）
- 2026-09-09 插件兼容性：`@linxin666/dsh-web-ui-all@0.3.6`（含
  dsh-better-sidebar 右侧文件面板）与 dsh 0.1.2-rc.1 **不兼容**（dsh-settings
  删除了 settingsNamespace/installSettingsSection 导出，启动即崩，已实测
  复现）。当前方案：base + web-app + dshmarket（可用）。用户选择等插件适配
  后手动检查：对比 npm 发布日期晚于 2026-09-03 再装
- 2026-09-13 机器切换：主力机改为 Windows 11（详见"机器环境"），Mac 成备用。
  当日完成：GitHub 仓库双向同步（SSH key 配好）、模型配置复制式同步、
  GLM_VISION_API_KEY 换新 Key（setx）、yishan 标签打印工具上线、
  stock-news-finder Windows 迁移跑通（file.py 跨平台修复、llm_classify.py
  SSL降级、output/ 改为不入库）。数据断档：raw/daily 缺 2026-08-29 ~ 09-12
  （游标只能回补约4个交易日）
- 2026-09-14 服务操作经验：本机 DoSvc（Delivery Optimization）用 `sc config`
  改配置即使管理员也报错误5（SCM 层保护，非注册表 ACL）；绕过方法=管理员
  PowerShell 直接 `Set-ItemProperty HKLM:\SYSTEM\CurrentControlSet\Services\DoSvc
  Start=4`，工具脚本 workspace\disable_dosvc.ps1（纯 ASCII——PS 5.1 按 GBK
  读无 BOM 的 UTF-8 脚本会乱码炸语法）。大版本更新可能重置，重跑即可
- 2026-09-14 桌面美化：快捷方式小箭头已去除，**最终成功方法**=
  管理员设置 `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Icons`
  的字符串值 `29` = `C:\Windows\System32\shell32.dll,-50`（系统自带空白图标资源），
  然后清 IconCache（%LOCALAPPDATA%\IconCache.db + Explorer\iconcache*）并重启
  explorer。工具脚本 workspace\fix_arrow_overlay_v4.ps1。**踩坑记录**：
  ① 重命名/删 `HKCR\lnkfile\IsShortcut` 在 Win11 26100 会让任务栏固定项报
  "没有关联的应用"（桌面不受影响），勿用；② 自定义透明 ico 会被 Explorer 判
  无效回退默认箭头（v2 白块=掩码写反，v3 全透明=回退），先试系统资源再考虑
  自制。恢复箭头=删 Shell Icons\29。功能更新可能重置，重跑 v4 脚本即可。
  另：git push 在沙箱内因 ssh 命名管道被禁需提权重试
- 2026-09-14 web_search 已可用（DEEPSEEK_API_KEY 已由用户在 Models 页配好并
  验证）。此前不可用期间离线答新版 Windows 玄学问题容易绕弯——同类问题以后
  先搜索再动手
- 2026-09-15 流程违规复盘：法人风险层先写码后补文档、git push 未等确认
  （profile 同步后未重新加载，旧版无此二规则）。修正：①规则入 profile；
  ②工作区同步消息出现后必须重读 profile；③文档先行流程即刻生效
