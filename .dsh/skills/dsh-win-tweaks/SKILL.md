# dsh-win-tweaks：Windows 系统调优方法论

在 jinwei 的 Windows 11 主力机（普通权限账户 `jinwei`，无管理员）上做系统级
调优：去快捷方式箭头、停止/禁用服务、清理开机自启、Explorer 图标异常处理。
触发场景：用户说"去掉小箭头"、"禁用某服务/清理驻留"、"删自启"、"图标显示不对"。

## 权限模型（先读这个）

| 操作 | 需要什么 | 会话内能否完成 |
|---|---|---|
| 查询服务/进程/读注册表 | 普通权限 | ✅ 直接做 |
| 停止/禁用服务、写 HKLM | 管理员 | ❌ 写 ASCII 脚本让用户在管理员终端跑 |
| 删 HKCU Run 自启键 | 当前用户 | ⚠️ 沙箱连 `reg.exe` 都拒注册表写入，走提权通道 |

三条铁律：
1. **提权必须用户本人过 UAC**。会话内 `Start-Process -Verb RunAs` 不可靠
   （UAC 点了"是"子进程也可能不执行，连日志都不写）——直接给用户一行命令
   在管理员终端跑，别浪费轮次重试
2. **给用户粘贴的命令要完整**：cmd 里要带 `powershell -File ...` 前缀；
   提醒不要把提示符前缀一起复制进去
3. **写 .ps1 脚本必须纯 ASCII**：DSH 写文件是 UTF-8 无 BOM，Windows
   PowerShell 5.1 按 GBK 读，中文注释会乱码炸语法（实测踩过）

## 方法一：去快捷方式箭头

**终版方案（Win11 26100 实测有效）**：

```powershell
# 管理员执行；工具脚本 windows-tweaks\fix_arrow_overlay_v4.ps1 是全套自动化
$si = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Icons'
New-ItemProperty -Path $si -Name '29' -Value 'C:\Windows\System32\shell32.dll,-50' -PropertyType String -Force
Stop-Process -Name explorer -Force   # 清缓存重启 explorer 见脚本
```

原理：箭头是"覆盖层图标"，系统画箭头前查 Shell Icons 表 29 号槽，填系统
自带空白资源（shell32.dll,-50）箭头就画不出来。恢复=删 29 键值。

**失败路线存档（勿再走）**：
- ❌ 删/改名 `HKCR\lnkfile\IsShortcut`：箭头会没，但**任务栏固定项报
  "该文件没有与之关联的应用"打不开**（桌面双击不受影响）——Win11 26100
  实测，老教程没提这坑
- ❌ 自制透明 .ico 指给 29：AND 掩码全 0 = 不透明（白块）；改全 1 全透明
  = Explorer 判"无效/空"回退默认箭头。别跟它较劲，直接用系统资源
- ❌ 29 设空字符串：无效回退

大版本更新可能重置，重跑 v4 脚本即可。

## 方法二：服务停止与禁用

**核心**：`sc config`/`Set-Service` 对部分服务（DoSvc、SharedAccess 等）
即使管理员也报错误 5（SCM API 层保护，非注册表 ACL）——绕过 =
管理员 PowerShell 直接写注册表：

```powershell
Set-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Services\<名>" -Name Start -Value 4   # 4=禁用 3=手动 2=自动
```

- **禁用 ≠ 停止**：注册表管"下次不启动"，运行中残影进程重启清除，
  别强杀共享 svchost
- 系统会自愈重置个别服务（SharedAccess 被改回 Manual），对抗成本 > 收益，
  放行
- **别碰清单**：vmcompute/hns/HvHost（WSL 命根子）、BFE/mpssvc（防火墙）、
  Tailscale/WSLService、显卡/声卡/Fn 键驱动栈、WinDefend（TrustedInstaller
  保护想停也停不掉）、RPC/EventLog/Schedule 系统底座
- **清理候选思路**：遥测类（whesvc/InventorySvc/DusmSvc）、厂商驻留
  （MuMuRemoteService/NahimicService）、用不上的系统件（lfsvc 定位/
  TrkWks/lmhosts/SharedAccess ICS/InstallService Store/PcaSvc 兼容助手/
  WSAIFabricSvc Copilot）——先列档给用户拍板再动手
- 已禁清单以 `windows-tweaks\stop_bloat_services.ps1` 脚本内数组为准（机器态
  信息不写死在 skill 里，防过期）

## 方法三：开机自启清理

```powershell
# 查询（HKCU，无需管理员）
reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Run"
# 删除（沙箱内 PowerShell/reg.exe 均被拒注册表写入，直接走提权通道）
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v <名称> /f
```

已清：GogGalaxy（游戏平台 838MB 驻留）、MuMuPlayerService、GalaxyClient 空键。
保留：Docker Desktop。

## 通用坑速查

- PS 5.1 GBK 读 UTF-8 脚本乱码 → 脚本纯 ASCII
- 图标改了不生效 → 清 `%LOCALAPPDATA%\IconCache.db` + `Explorer\iconcache*` 再重启 explorer
- 服务禁了又复活 → 系统自愈（SharedAccess 类），评估后放行或重跑脚本
- Explorer 意外停止日志（EventId 1002）若与我们重启 explorer 时间吻合，是正常操作痕迹勿慌

## 工具脚本索引（windows-tweaks/）

| 脚本 | 用途 |
|---|---|
| disable_dosvc.ps1 | 单服务禁用（DoSvc，含 SCM 保护说明） |
| stop_bloat_services.ps1 | 批量停+禁（服务清单在脚本内数组） |
| fix_arrow_overlay_v4.ps1 | 去箭头终版（shell32.dll,-50 + 清缓存） |
| fix_arrow_overlay_v2/v3.ps1 | 失败路线存档（白块/回退），留作避雷 |
| fix_shortcuts_and_arrow.ps1 | 修复 IsShortcut 副作用 + 双尺寸图标（过渡版） |
| remove_shortcut_arrow.ps1 | 最早的 IsShortcut 改名版（勿用，副作用） |
