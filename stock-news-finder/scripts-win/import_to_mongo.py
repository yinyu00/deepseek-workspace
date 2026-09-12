#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mongo 导入脚本（Windows 侧，DB 同步第 2 跳）。

读取 sync/<yyyymmdd>/*.jsonl（FTP 落盘目录），幂等 upsert 进 Mongo。
依赖：pip install pymongo
连接：环境变量 MONGODB_URI，或 --uri 参数
   推荐（独立库 stock，勿与 fastgpt 库混用）：
   set MONGODB_URI=mongodb://root:<pwd>@localhost:27017/stock?authSource=admin

用法：
    python import_to_mongo.py D:\ftp\stock-sync\20260826      # 导入指定日期目录
    python import_to_mongo.py D:\ftp\stock-sync               # 导入目录下全部日期
    python import_to_mongo.py --uri mongodb://... D:\ftp\stock-sync
"""
import json
import os
import sys
from datetime import datetime

try:
    from pymongo import MongoClient, UpdateOne
except ImportError:
    sys.exit("请先安装 pymongo:  pip install pymongo")


def read_jsonl(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def parse_time(s):
    try:
        return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def import_news(db, rows):
    ops = []
    for r in rows:
        doc = dict(r)
        doc["time"] = parse_time(r.get("time", ""))
        doc["created_at"] = datetime.now()
        key = {"title_hash": r["title_hash"]}
        ops.append(UpdateOne(key, {"$set": doc}, upsert=True))
    if ops:
        db.news.bulk_write(ops, ordered=False)
    db.news.create_index("title_hash", unique=True)
    db.news.create_index([("trade_date", 1), ("source", 1)])
    db.news.create_index("stocks")
    db.news.create_index([("time", -1)])
    return len(ops)


def import_signals(db, rows):
    ops = []
    for r in rows:
        doc = dict(r)
        doc["generated_at"] = parse_time(r.get("generated_at", "")) or datetime.now()
        key = {"trade_date": r["trade_date"], "code": r["code"]}
        ops.append(UpdateOne(key, {"$set": doc}, upsert=True))
    if ops:
        db.signals.bulk_write(ops, ordered=False)
    db.signals.create_index([("trade_date", 1), ("code", 1)], unique=True)
    db.signals.create_index([("trade_date", 1), ("score", -1)])
    return len(ops)


def import_llm(db, rows):
    ops = []
    for r in rows:
        doc = dict(r)
        _id = f"{r.get('trade_date')}:{r.get('id')}"
        ops.append(UpdateOne({"_id": _id}, {"$set": doc}, upsert=True))
    if ops:
        db.llm_events.bulk_write(ops, ordered=False)
    db.llm_events.create_index([("trade_date", 1), ("event", 1)])
    return len(ops)


def import_stocks(db, rows):
    ops = []
    for r in rows:
        doc = dict(r)
        doc["updated_at"] = datetime.now()
        ops.append(UpdateOne({"code": r["code"]}, {"$set": doc}, upsert=True))
    if ops:
        db.stocks.bulk_write(ops, ordered=False)
    db.stocks.create_index("code", unique=True)
    return len(ops)


def import_boards(db, rows):
    ops = []
    for r in rows:
        doc = dict(r)
        key = {"word": r["word"], "date": r["date"]}
        ops.append(UpdateOne(key, {"$set": doc}, upsert=True))
    if ops:
        db.boards.bulk_write(ops, ordered=False)
    db.boards.create_index([("word", 1), ("date", -1)])
    return len(ops)


IMPORTERS = {
    "news.jsonl": import_news,
    "signals.jsonl": import_signals,
    "llm_events.jsonl": import_llm,
    "stocks.jsonl": import_stocks,
    "boards.jsonl": import_boards,
}


def import_day_dir(db, day_dir):
    total = {}
    for fn, fn_impl in IMPORTERS.items():
        path = os.path.join(day_dir, fn)
        if not os.path.exists(path):
            continue
        rows = read_jsonl(path)
        total[fn] = fn_impl(db, rows)
    db.runs.insert_one({"ts": datetime.now(), "host": os.environ.get("COMPUTERNAME", "?"),
                        "type": "import", "dir": day_dir, "counts": total})
    return total


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    uri = os.environ.get("MONGODB_URI") or (
        sys.argv[sys.argv.index("--uri") + 1] if "--uri" in sys.argv else None)
    if not uri:
        sys.exit("缺少连接：设置 MONGODB_URI 或 --uri（参考脚本头部注释，用独立库 stock）")
    if not args:
        sys.exit("用法: python import_to_mongo.py <sync目录或日期目录>")
    target = args[0]
    client = MongoClient(uri, serverSelectionTimeoutMS=8000)
    db = client.get_default_database() or client["stock"]

    # 目标是日期目录（含 manifest.json）还是父目录
    if os.path.exists(os.path.join(target, "manifest.json")):
        print(target, "→", import_day_dir(db, target))
    else:
        for name in sorted(os.listdir(target)):
            day_dir = os.path.join(target, name)
            if os.path.isdir(day_dir) and os.path.exists(os.path.join(day_dir, "manifest.json")):
                print(day_dir, "→", import_day_dir(db, day_dir))
    print("完成。库:", db.name)


if __name__ == "__main__":
    main()
