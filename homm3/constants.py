"""全局常量"""
TILE = 44
MAP_W, MAP_H = 26, 16

# 资源类型
RES_LIST = ["gold", "wood", "ore", "crystal"]
RES_CN = {"gold": "金币", "wood": "木材", "ore": "矿石", "crystal": "水晶"}

# 地形
T_GRASS, T_DIRT, T_WATER, T_ROCK = 0, 1, 2, 3
TERRAIN_COLOR = {
    T_GRASS: (74, 122, 62),
    T_DIRT: (128, 100, 66),
    T_WATER: (48, 84, 140),
    T_ROCK: (110, 110, 118),
}
PASSABLE = {T_GRASS, T_DIRT}

# 对象类型
OBJ_RESOURCE, OBJ_MINE, OBJ_CHEST, OBJ_MONSTER, OBJ_TOWN, OBJ_ARTIFACT, OBJ_SHRINE = \
    "resource", "mine", "chest", "monster", "town", "artifact", "shrine"

MINE_RES = {"sawmill": "wood", "orepit": "ore", "crystalcave": "crystal", "goldmine": "gold"}
MINE_CN = {"sawmill": "锯木场", "orepit": "矿石场", "crystalcave": "水晶洞", "goldmine": "金矿"}
MINE_WEEK = {"wood": 2, "ore": 2, "crystal": 1, "gold": 500}

OBJ_COLOR = {
    "gold": (250, 210, 60), "wood": (150, 100, 55), "ore": (130, 130, 140), "crystal": (140, 220, 230),
}

HERO_MP_PER_TILE = 100
HERO_DAILY_MP = 1800
