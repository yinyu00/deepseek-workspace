---
name: glm4v-image-compress
description: 在用 glm-4v-flash 识别图片前，先把图片压缩/缩放到适配其 16K 上下文的安全尺寸（宽 ≤900px），避免 400 报错（inputs tokens 超 16384）。凡是用 glm-4v-flash 做图片识别、且图片较大（宽 >900px 或为长截图）时必须先执行本 skill。
---

# glm4v-image-compress：glm-4v-flash 识图前压缩图片

## 背景

glm-4v-flash 上下文只有 **16K tokens**，且免费、无放大配置。大图（尤其长截图）
编码后动辄数万 tokens，直接发送会报错：

```
400: `inputs` tokens + `max_new_tokens` must be <= 16384
```

经验值：最长边缩到 **900px** 的 JPEG，视觉 token 约 700~2000，安全；
1200px 以上长图开始逼近上限。

## 判断是否需要压缩

```bash
sips -g pixelWidth -g pixelHeight "<图片路径>"
```

- 最长边 ≤ 900px → 无需压缩，直接识别
- 最长边 > 900px 或为长截图 → 先压缩

## 压缩步骤（macOS，用系统自带 sips，无依赖）

```bash
# 缩放到最长边 900px，输出 JPEG（质量 80）
sips -Z 900 -s format jpeg -s formatOptions 80 \
  "<原图路径>" --out /tmp/dsh-compressed-$(basename "<原图路径>" | sed 's/\.[^.]*$//').jpg
```

- `-Z 900` 表示**最长边**缩到 900px（横图竖图都适用）
- 极长的聊天截图即使 -Z 900 仍可能超宽高比异常，可再降为 `-Z 700`
- 需要保留透明背景时改 `-s format png`

## 验证压缩结果

```bash
sips -g pixelWidth -g pixelHeight /tmp/dsh-compressed-*.jpg
ls -lh /tmp/dsh-compressed-*.jpg
```

## 后续

用压缩后的 `/tmp/dsh-compressed-*.jpg` 作为 read_image / 识别输入，
识别完成后可删除临时文件：`rm /tmp/dsh-compressed-*.jpg`

## DSH 附件路径提示

用户在 GUI 贴的图片持久化在 `~/.dsh/attachments/v1/objects/<前两位>/<sha256>`，
文件名即内容哈希、无扩展名，sips 仍能处理（JPEG/PNG/WebP/GIF 自动识别），
但输出时务必显式 `--out xxx.jpg` 指定格式。

## 注意事项

- glm-4v-flash 的 settings.yaml 已标注 `contextWindow: 16384 / maxTokens: 1024`，
  DSH 会在超限时前置拦截；本 skill 是让图片真正"能被识别"，而非绕过拦截。
- 若压缩后仍报 tokens 超限，继续降尺寸（900 → 700 → 512）。
- Linux 无 sips 时可用 `convert <in> -resize 900x900\> -quality 80 <out>`（ImageMagick）。
