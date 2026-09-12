#!/usr/bin/env python3
"""从 16x16 Puny World Tileset (CC0, by Shade / merchant-shade, opengameart.org)
切片野外地形图块到 assets/。可重复执行。

下载（若代理握手失败可用 --noproxy '*' 直连）:
curl -sL -o /tmp/punyworld.png \
  "https://opengameart.org/sites/default/files/punyworld-overworld-tileset_0.png"
"""
import os
import subprocess
import sys

SRC = "/tmp/punyworld.png"
URL = "https://opengameart.org/sites/default/files/punyworld-overworld-tileset_0.png"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

# 人工核对色块统计后选定的格子 (col, row)
TILES = {
    "terrain_grass": (0, 5),   # 浅平草 (131,153,72)
    "terrain_grass2": (5, 5),  # 草变体 (131,149,78)
    "terrain_grass3": (1, 8),  # 草变体-深 (78,123,65)
    "terrain_water": (5, 10),  # 海水 (14,159,172)
    "terrain_rock":  (16, 27), # 山岩 (151,160,134)
    "terrain_dirt":  (22, 27), # 道路 (167,113,46)
    "terrain_tree":  (12, 6),  # 树 (100,110,62)
}


def main():
    if not os.path.exists(SRC):
        r = subprocess.run(["curl", "-sL", "--max-time", "60", "-o", SRC, URL])
        if r.returncode != 0 or not os.path.exists(SRC):
            print("下载失败，请手动下载（可试 --noproxy '*'）:", URL)
            sys.exit(1)
    import pygame
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.init()
    pygame.display.set_mode((32, 32))
    img = pygame.image.load(SRC).convert_alpha()
    os.makedirs(OUT, exist_ok=True)
    for name, (c, r) in TILES.items():
        tile = pygame.Surface((16, 16)).convert_alpha()
        tile.fill((0, 0, 0, 0))
        tile.blit(img, (0, 0), (c * 16, r * 16, 16, 16))
        path = os.path.join(OUT, name + ".png")
        pygame.image.save(tile, path)
        print("saved", name, os.path.getsize(path), "bytes")
    with open(os.path.join(OUT, "CREDITS.txt"), "a", encoding="utf-8") as f:
        f.write("\nterrain_*.png / terrain 树木装饰: 16x16 Puny World Tileset\n"
                "作者 Shade (merchant-shade), 来源 opengameart.org, 授权 CC0。\n")
    pygame.quit()


if __name__ == "__main__":
    main()
