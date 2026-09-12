# 采集器插件接口规范 v1

## 目录与命名

- 位置：`fetchers/<type>.py`，文件名 = sources.json 里的 `type` 字段值（下划线命名）
- 例：`type: "eastmoney-fast"` → `fetchers/eastmoney_fast.py`

## 统一接口

```python
def fetch(cfg: dict) -> list:
    """
    cfg: sources.json 中该源的完整配置项（含 type/name/enabled 及私有参数）。
         loader 可能注入 "_stop_date"（"YYYY-MM-DD"）：抓到该日 00:00 为止（历史回补用）。
    返回: list[dict]，每条新闻固定字段：
      {
        "title":  str,                     # 标题（无标题取正文前40字）
        "body":   str,                     # 正文
        "time":   "YYYY-MM-DD HH:MM:SS",   # 统一格式（本地时区）
        "source": str,                     # 与 SOURCE_NAMES 映射键一致（用 type 值）
        "url":    str,                     # 原文链接，无则空串
        "stocks": [str],                   # 官方标注股票代码（6位数字），无则 []
      }
    """

def selftest() -> bool:
    """自测：真实调用接口抓 1 页，校验字段格式，成功返回 True。"""
```

## 约束

1. 网络请求失败要捕获并打印 `[warn]` 到 stderr，返回已抓到的部分（不抛异常中断）
2. 不修改 fetchers/ 之外的任何文件
3. 无第三方依赖（urllib/curl 子进程均可；push2 域名必须用 curl 子进程+多节点重试，参考 product_lookup.py 的 _get_json）
4. 幂等安全：重复运行不产生副作用（无状态写入）
5. 翻页必须有安全上限（防死循环）

## loader 行为（参考，无需实现）

fetch_news.py 扫描 sources.json → 对 enabled 源 `import fetchers.<type>` → 调 `fetch(cfg)` →
汇总去重 → output/raw_news.json + raw/yyyymmdd.json 归档。
