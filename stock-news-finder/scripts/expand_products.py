#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""产品词表批量扩充（F2.7）：候选概念词 → suggest 验证是否有对应板块 → 生成 products.txt。

候选词来自人工整理的主流概念清单（可不断补充）；只收录 suggest 能匹配到
板块（Classify==BK）的词，作为产品传导通道的词表。
用法：
    python3 expand_products.py           # 验证并生成 data/products.new.txt（人工确认后替换）
    python3 expand_products.py --apply   # 直接合并进 products.txt
"""
import json
import os
import subprocess
import sys
import urllib.parse

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRODUCTS = os.path.join(BASE, "data", "products.txt")
NEW = os.path.join(BASE, "data", "products.new.txt")

# 候选概念词库（按主题分组；后续可持续补充——加词只改这里）
CANDIDATES = [
    # 科技/半导体
    "CPO", "光模块", "光通信", "Chiplet", "先进封装", "存储芯片", "GPU", "算力",
    "液冷", "数据中心", "AI服务器", "人工智能", "AIGC", "大模型", "智能驾驶",
    "自动驾驶", "激光雷达", "车联网", "卫星互联网", "低空经济", "无人机",
    "工业母机", "机器人", "人形机器人", "减速器", "传感器",
    # 新能源
    "固态电池", "钠离子电池", "麒麟电池", "储能", "氢能源", "燃料电池", "光伏",
    "TOPCon电池", "HJT电池", "钙钛矿", "风力发电", "海上风电", "核能", "可控核聚变",
    "特高压", "智能电网", "虚拟电厂", "充电桩", "换电",
    # 新能源车产业链
    "锂电池", "锂矿", "钴", "镍", "稀土永磁", "正极材料", "负极材料", "电解液",
    "隔膜", "铜箔", "一体化压铸", "汽车零部件", "智能座舱", "线控底盘",
    # 医药
    "创新药", "CXO", "疫苗", "HPV疫苗", "GLP-1", "减肥药", "医疗器械", "脑机接口",
    "基因测序", "中药创新药", "血制品", "眼科", "辅助生殖",
    # 消费
    "预制菜", "白酒", "啤酒", "乳制品", "宠物经济", "化妆品", "医美", "跨境电商",
    "免税", "网络游戏", "电竞", "短剧", "IP经济", "谷子经济",
    # 周期/材料
    "黄金", "白银", "铜", "铝", "稀土", "锗", "镓", "石墨烯", "碳纤维",
    "超导材料", "维生素", "猪肉", "鸡肉", "水产养殖", "磷化工", "氟化工",
    "钛白粉", "水泥", "玻璃", "钢铁", "煤炭", "石油", "天然气",
    # 高端制造/军工
    "大飞机", "商业航天", "火箭", "卫星导航", "北斗导航", "军工", "航母",
    "深海科技", "船舶制造", "工业软件", "国产操作系统", "信创", "网络安全",
    "量子计算", "量子通信", "6G", "鸿蒙", "数据要素", "数字经济", "区块链",
    # 金融地产基建
    "券商", "银行", "保险", "互联网金融", "数字货币", "跨境支付", "物业管理",
    "装配式建筑", "地下管网", "水利建设", "一带一路", "粤港澳大湾区",
]


def has_board(word):
    u = ("https://searchapi.eastmoney.com/api/suggest/get?input=" + urllib.parse.quote(word)
         + "&type=14&token=D43BF722C8E33BDC906FB84D85E326E8&count=8")
    r = subprocess.run(["curl", "-s", "-m", "10", "-A", "Mozilla/5.0",
                        "-H", "Referer: https://www.eastmoney.com/", u],
                       capture_output=True, text=True)
    try:
        d = json.loads(r.stdout)
    except Exception:
        return None
    for it in (d.get("QuotationCodeTable") or {}).get("Data") or []:
        if it and it.get("Classify") == "BK":
            if word in it.get("Name", "") or it.get("Name", "") in word:
                return it.get("Name")
    return None


def main():
    apply_mode = "--apply" in sys.argv
    ok_words, miss_words = [], []
    for i, w in enumerate(CANDIDATES):
        board = has_board(w)
        if board:
            ok_words.append(w)
            print(f"✓ [{i+1}/{len(CANDIDATES)}] {w} → {board}")
        else:
            miss_words.append(w)
    with open(NEW, "w", encoding="utf-8") as f:
        f.write("# 产品/概念词表（expand_products.py 生成于候选词库验证）\n")
        f.write("# 手动增删随时生效；解析不到板块的词自动忽略\n")
        f.write("\n".join(ok_words) + "\n")
    print(f"\n收录 {len(ok_words)} 词，无板块 {len(miss_words)} 词: {miss_words}")
    print(f"→ {NEW}" + ("（--apply 模式：已合并）" if apply_mode else "（人工确认后替换 products.txt，或加 --apply 重跑）"))
    if apply_mode:
        # 保留原手动词 + 新词去重合并
        old = [l.strip() for l in open(PRODUCTS, encoding="utf-8")
               if l.strip() and not l.startswith("#")]
        merged = sorted(set(old) | set(ok_words))
        with open(PRODUCTS, "w", encoding="utf-8") as f:
            f.write("# 产品/概念词表（手动 + expand_products.py 合并）\n")
            f.write("\n".join(merged) + "\n")
        print(f"已合并 → {PRODUCTS}（{len(merged)} 词）")


if __name__ == "__main__":
    main()
