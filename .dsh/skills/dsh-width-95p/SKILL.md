---
name: dsh-width-95p
description: 把 DSH Web GUI 对话框/消息展示区宽度设置为父容器的 95%（百分比自适应，任意分辨率生效）。适用于 dsh web 前端界面加宽、界面展示区宽度调整。
---

# dsh-width-95p：DSH 对话框展示区宽度设为 95%

## 背景

DSH Web GUI 的消息内容区宽度由 CSS 变量 `--dsh-chat-content-width` 控制，
默认值为 `748px`，定义在预构建包 `dsh-client-ui-conversation` 的
`lib/client.js` 中（css$6 的 `.wSkVaW_root` 规则内）。

本 skill 将该值改为 **95%**（相对父容器的百分比），比固定 1500px 的旧方案
（dsh-width-1500）更优：任意分辨率屏幕自动适配，无需按屏幕手调数值。

**关键经验（0.1.1-rc.2 实测）**：
1. 只改变量定义**可能不生效**——变量虽已加载，消息流容器另有约束。
   必须同时对消息列类追加显式 `max-width` 约束（见步骤 2）。
2. `max-width:95%` 语义是相对父容器宽度，实测可用（消息列父容器为全宽布局）。

## 操作步骤

1. 定位目标文件。机器上可能同时存在**多份** dlx 缓存副本（每次
   `pnpm dlx` / 升级产生一个），必须**全部修改**：

   ```bash
   FILES=$(find ~/.pnpm /Users/jinwei/Library/Caches/pnpm/dlx \
        -path "*dsh-client-ui-conversation/lib/client.js" \
        -not -name "*.bak" 2>/dev/null)
   echo "$FILES"
   ```

   注意：此路径在工作区外，需 danger-full-access 权限执行。

2. 替换宽度变量为 95% 并注入容器约束（幂等，兼容 748px/1500px 旧值）：

   ```bash
   for F in $FILES; do
     [ -f "$F.bak" ] || cp "$F" "$F.bak"
     sed -i '' -E 's/--dsh-chat-content-width:[0-9]+px|--dsh-chat-content-width:95%/' "$F"
     python3 - "$F" <<'EOF'
   import sys
   f = sys.argv[1]
   s = open(f).read()
   # 0.1.1-rc.2 的类名：.Md3f7G_column .FJxK0a_root .bqrRRG_card（哈希随版本变）
   anchor = "--dsh-composer-card-max-width:calc(var(--dsh-chat-content-width) + 32px)"
   extra = anchor + ";.Md3f7G_column,.FJxK0a_root,.bqrRRG_card{max-width:var(--dsh-chat-content-width)}"
   if anchor in s and "Md3f7G_column,.FJxK0a_root" not in s:
       s = s.replace(anchor, extra, 1)
       open(f, "w").write(s)
       print("container rule injected")
   elif "Md3f7G_column,.FJxK0a_root" in s:
       print("container rule already present")
   else:
       print("skip (missing anchor)")
   EOF
   done
   ```

   若类名在新版中变化：先 grep `max-width:var\(--dsh-chat-content-width\)`
   找到消费该变量的类名，替换 extra 中的三个类名。

3. 验证：

   ```bash
   curl -s "http://127.0.0.1:3080/plugins/@deepseek-ai/dsh-client-ui-conversation/client.js" \
     | grep -o -- "--dsh-chat-content-width:[^;}]*"   # 应输出 95%
   curl -s "http://127.0.0.1:3080/plugins/@deepseek-ai/dsh-client-ui-conversation/client.js" \
     | grep -c "Md3f7G_column"                          # 应 ≥1
   ```

4. 让用户在浏览器**硬刷新**（Cmd+Shift+R）。

## 诊断手法（改了不生效时）

1. **注入红框**：给 `max-width:var(--dsh-chat-content-width)` 的规则加
   `outline:2px dashed red;`，用户刷新后看到红框 = 代码已加载
2. **强制宽度**：注入 `max-width:95% !important`，变宽 = 找到真容器；
   不变 = 容器另有其类，用 DevTools 检查器点消息文本找真实 class
3. 确认后移除调试标记，收敛为干净的变量引用

## 回滚

```bash
for B in $(find ~/.pnpm /Users/jinwei/Library/Caches/pnpm/dlx \
     -path "*dsh-client-ui-conversation/lib/client.js.bak" 2>/dev/null); do
  mv "$B" "${B%.bak}"
done
```

## 注意事项

- 95% 相对父容器：窗口缩小时内容照常自适应收缩，不影响小屏；调大屏幕
  分辨率后自动铺满 95%，无需再改。
- dsh 升级 / 重装依赖后改动会被覆盖，需重新执行一次（本 skill 幂等可重跑）。
- 该变量只存在于 `dsh-client-ui-conversation` 包；`dsh-client-ui-user-questions`
  也引用它但不在自己包内定义，无需改动。
- 前身 skill 为 dsh-width-1500（固定 1500px 方案），已被本 skill 取代，
  但保留未删以防需要回退到固定宽度方案。
