#!/usr/bin/env python3
"""从 Dungeon Crawl Stone Soup rltiles（公有领域式授权）拉取素材到 assets/。
用法: .venv/bin/python fetch_assets.py
每个 key 给多个候选路径，取第一个 200 的。"""
import subprocess
import os
import sys

BASE = "https://raw.githubusercontent.com/crawl/crawl/master/crawl-ref/source/rltiles"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
os.makedirs(OUT, exist_ok=True)

WANT = {
    # ---- 城堡兵种 ----
    "pikeman":   ["mon/humanoids/humans/imperial_myrmidon.png", "mon/humanoids/humans/human.png"],
    "archer":    ["mon/humanoids/humans/arcanist.png", "mon/humanoids/humans/occultist.png"],
    "griffin":   ["mon/animals/hippogriff.png", "mon/animals/bennu.png"],
    "swordsman": ["mon/humanoids/humans/vault_guard.png", "mon/humanoids/humans/vault_sentinel.png"],
    "monk":      ["mon/humanoids/humans/burial_acolyte.png", "mon/humanoids/humans/servant_of_whispers.png"],
    "cavalier":  ["mon/humanoids/humans/hell_knight.png", "mon/humanoids/humans/human3.png"],
    # ---- 亡灵 ----
    "skeleton":    ["mon/undead/zombies/zombie_skeleton.png", "mon/undead/laughing_skull.png"],
    "zombie":      ["mon/undead/zombies/zombie_gnoll.png", "mon/undead/zombies/zombie_elf.png"],
    "wraith":      ["mon/undead/ghost.png", "mon/undead/flayed_ghost.png"],
    "vampire":     ["mon/undead/vampire.png", "mon/undead/halazid_warlock.png"],
    "lich":        ["mon/undead/ancient_lich.png", "mon/undead/dread_lich.png"],
    "bone_dragon": ["mon/undead/bone_dragon.png"],
    # ---- 中立 ----
    "wolf":   ["mon/animals/wolf.png", "mon/animals/warg.png"],
    "golem":  ["mon/humanoids/ironbound_thunderhulk.png", "mon/animals/mountainshell.png"],
    "ogre":   ["mon/humanoids/giants/hill_giant.png", "mon/humanoids/giants/stone_giant.png",
               "mon/humanoids/deep_troll.png"],
    "troll":  ["mon/humanoids/deep_troll.png"],
    "dragon": ["mon/dragons/swamp_dragon.png", "mon/dragons/fire_dragon.png"],
    # ---- 英雄 ----
    "hero":       ["mon/humanoids/humans/human.png", "mon/humanoids/humans/human2.png"],
    "hero2":      ["mon/humanoids/humans/human3.png", "mon/humanoids/humans/human2.png"],
    "necromancer": ["mon/humanoids/humans/necromancer.png", "mon/undead/necromancer.png"],
    # ---- 物件 ----
    "gold":    ["item/gold/16.png", "item/gold/25.png"],
    "crystal": ["item/gem/depths_found_whole.png", "item/potion/white.png"],
}


def fetch(key, cands):
    for c in cands:
        url = "%s/%s" % (BASE, c)
        dst = os.path.join(OUT, key + ".png")
        r = subprocess.run(["curl", "-sL", "--max-time", "30", "-o", dst, "-w", "%{http_code}", url],
                           capture_output=True, text=True)
        if r.stdout.strip() == "200" and os.path.getsize(dst) > 100:
            print("OK  %-14s <- %s" % (key, c))
            return True
    print("MISS", key)
    return False


ok = miss = 0
for k, cands in WANT.items():
    if fetch(k, cands):
        ok += 1
    else:
        miss += 1
print("done: %d ok, %d miss" % (ok, miss))

CREDITS = """本目录素材来自 Dungeon Crawl Stone Soup 的 rltiles 美术集。
授权: CC0 1.0 Universal（部分早期作者条款亦允许任意使用与改编，
详见 https://opengameart.org/content/dungeon-crawl-32x32-tiles 与
DCSS 源码 tree crawl-ref/source/rltiles/CREDITS）。
本项目按"接近英雄无敌3玩法复刻"用途做了缩放使用，未做修改性重绘。
"""
with open(os.path.join(OUT, "CREDITS.txt"), "w", encoding="utf-8") as f:
    f.write(CREDITS)
