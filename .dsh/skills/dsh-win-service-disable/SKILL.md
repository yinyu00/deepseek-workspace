# dsh-win-service-disable：禁用/停止 Windows 服务的正确姿势

在 jinwei 的 Windows 11 主力机（普通权限账户 `jinwei`）上禁用 Windows 服务。
适用场景：用户说"禁用某个服务"、"这个服务停不掉/拒绝访问"、批量清理驻留服务。

## 背景知识（为什么经常报"拒绝访问"）

| 层级 | 现象 | 原因 |
|---|---|---|
| 普通权限 shell 直接改 | 错误 5 | 本机是普通账户，服务操作必须管理员 |
| 管理员用 `sc config` 改部分服务（DoSvc、SharedAccess 等） | 仍错误 5 | **SCM API 层保护**，较新 Win11 拦截对特定服务的配置调用 |
| 管理员直接写注册表 `Start` 值 | **成功** | 注册表 ACL 并未限制 Administrators，绕过 SCM 即可 |

关键结论：**`sc config` / `Set-Service` 被拒时，直接 `Set-ItemProperty` 写
`HKLM:\SYSTEM\CurrentControlSet\Services\<服务名>` 的 `Start` 值**。
停止运行中的进程仍可能被 SCM 拒（残影进程重启后自然消失，别强杀共享 svchost）。

`Start` 值对照：`2`=自动 `3`=手动（按需） `4`=禁用。

## 标准流程

1. **本会话 shell 是普通权限**，先查状态（查询不需要管理员）：
   `Get-Service <名> | fl Name,Status,StartType` 和 `sc.exe qc <名>`
2. **写一个纯 ASCII 的 PowerShell 脚本**放到 workspace（如 `stop_bloat_services.ps1`），
   内容 = 逐服务 `Stop-Service -Force` + `Set-ItemProperty Start=4`（失败再退回 `sc config`）
3. **让用户在管理员终端执行**（提权必须本人过 UAC，会话内无法自动完成）：
   `powershell -ExecutionPolicy Bypass -File D:\ai\deepseek-harness\workspace\<脚本>.ps1`
   —— 提示用户在 cmd 里粘命令要带 `powershell -Command "..."/-File` 前缀，
   且不要连提示符前缀一起复制
4. 从会话 shell 里 `Get-Service` 核对最终状态

## 必须遵守的坑

- **脚本必须纯 ASCII**：DSH 写文件是 UTF-8 无 BOM，Windows PowerShell 5.1
  按 GBK 读会把中文注释/字符串读乱导致语法错误（实测踩过）。
  注释、输出全部用英文
- **Start-Process -Verb RunAs 从会话内提权不可靠**：UAC 弹了用户点了"是"，
  提权子进程也可能不执行（连日志都不写），别浪费时间重试，直接走用户手动管理员终端
- **禁用 ≠ 停止**：注册表直写管"下次不启动"；运行中残影进程只能重启清除
- **别碰的服务**：vmcompute/hns/HvHost（WSL 命根子）、BFE/mpssvc（防火墙）、
  Tailscale/WSLService、显卡/声卡/Fn 键驱动栈、WinDefend（TrustedInstaller 保护，
  想停也停不掉）、RPC/EventLog/Schedule 等系统底座
- **大版本 Windows 更新可能重置服务**，工具脚本保留在 workspace 供重跑：
  `disable_dosvc.ps1`（单服务版）、`stop_bloat_services.ps1`（批量版）

## 已处理记录

- 2026-09-14 DoSvc（Delivery Optimization）：禁用+停止 ✅
- 2026-09-14 批量 12 个（MuMuRemoteService/NahimicService/lfsvc/TrkWks/lmhosts/
  InstallService/PcaSvc/whesvc/InventorySvc/DusmSvc/WSAIFabricSvc 全停+禁；
  SharedAccess 禁用成功、进程残影待重启）
