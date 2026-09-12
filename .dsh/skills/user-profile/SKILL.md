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

## 机器环境

- macOS（Apple Silicon），shell 是 zsh（`~/.zshrc`）
- 包管理：pnpm / pnpx（dsh 通过 `pnpx @deepseek-ai/dsh web` 启动，端口 3080）
- 系统开了全局代理（`ALL_PROXY` / `HTTP_PROXY` / `HTTPS_PROXY`），网络排查时记得这层
- 工作区：`/Users/jinwei/ai/deepseek/harness/workspace`
- DSH 源码 checkout（只读参考）：`/Users/jinwei/git/github/deepseek-ai/deepseek-harness/`
- `~/.npm` 曾有 root 属主权限问题（已修复，若 npx 报 EPERM 再查）

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
