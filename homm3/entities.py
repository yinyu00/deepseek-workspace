"""兵种 / 英雄 / 城镇 数据模型"""
from dataclasses import dataclass, field
from constants import *


@dataclass(frozen=True)
class UnitType:
    key: str
    name: str
    tier: int
    hp: int
    atk: int
    dfn: int
    dmin: int
    dmax: int
    speed: int
    ranged: bool = False
    gold_cost: int = 0
    color: tuple = (200, 200, 200)
    faction: str = "neutral"     # castle / undead / neutral
    lifesteal: bool = False      # 吸血：按伤害恢复自身数量


# 阵营兵种（人类城堡风）
UNITS = {
    "pikeman": UnitType("pikeman", "枪兵", 1, 10, 4, 5, 1, 3, 4, gold_cost=60, color=(70, 110, 190), faction="castle"),
    "archer": UnitType("archer", "弓箭手", 2, 10, 6, 3, 2, 3, 4, ranged=True, gold_cost=100, color=(200, 170, 60), faction="castle"),
    "griffin": UnitType("griffin", "狮鹫", 3, 25, 8, 8, 3, 6, 6, gold_cost=200, color=(170, 140, 210), faction="castle"),
    "swordsman": UnitType("swordsman", "剑士", 4, 35, 10, 12, 6, 9, 5, gold_cost=300, color=(90, 160, 90), faction="castle"),
    "monk": UnitType("monk", "僧侣", 5, 30, 12, 7, 10, 12, 5, ranged=True, gold_cost=400, color=(230, 230, 230), faction="castle"),
    "cavalier": UnitType("cavalier", "骑士", 6, 100, 15, 15, 15, 25, 7, gold_cost=1000, color=(220, 120, 60), faction="castle"),
    # 亡灵阵营
    "skeleton": UnitType("skeleton", "骷髅兵", 1, 6, 5, 4, 1, 3, 4, gold_cost=60, color=(220, 220, 200), faction="undead"),
    "zombie": UnitType("zombie", "僵尸", 2, 20, 5, 5, 2, 3, 3, gold_cost=100, color=(120, 160, 110), faction="undead"),
    "wraith": UnitType("wraith", "幽灵", 3, 18, 7, 7, 3, 5, 6, gold_cost=200, color=(180, 200, 230), faction="undead"),
    "vampire": UnitType("vampire", "吸血鬼", 4, 30, 10, 9, 5, 8, 6, gold_cost=400, color=(160, 60, 140), faction="undead", lifesteal=True),
    "lich": UnitType("lich", "巫妖", 5, 30, 13, 10, 11, 13, 5, ranged=True, gold_cost=600, color=(80, 90, 200), faction="undead"),
    "bone_dragon": UnitType("bone_dragon", "骨龙", 7, 150, 17, 15, 25, 50, 6, gold_cost=1800, color=(230, 230, 210), faction="undead"),
    # 中立野怪
    "wolf": UnitType("wolf", "野狼", 2, 20, 8, 4, 3, 5, 6, color=(140, 140, 150)),
    "golem": UnitType("golem", "石人", 3, 30, 7, 10, 4, 5, 3, color=(160, 160, 170)),
    "ogre": UnitType("ogre", "食人魔", 4, 40, 13, 7, 6, 12, 4, color=(180, 120, 90)),
    "troll": UnitType("troll", "巨魔", 5, 40, 14, 7, 10, 15, 5, ranged=True, color=(90, 170, 120)),
    "dragon": UnitType("dragon", "绿龙", 7, 200, 18, 18, 40, 50, 6, color=(60, 180, 80)),
}
NEUTRAL_POOL = ["wolf", "skeleton", "golem", "ogre", "troll", "dragon"]
UNDEAD_POOL = ["skeleton", "zombie", "wraith", "vampire", "lich", "bone_dragon"]

# 宝物: key -> dict(name 名称, slot 槽位, bonus 加成)
ARTIFACTS = {
    "sword":   {"name": "烈焰之剑", "slot": "weapon", "bonus": {"atk": 3}, "color": (230, 80, 60)},
    "armor":   {"name": "守护铠甲", "slot": "armor", "bonus": {"dfn": 3}, "color": (120, 140, 220)},
    "orb":     {"name": "魔力宝珠", "slot": "misc", "bonus": {"spell_power": 2, "mana": 10}, "color": (190, 90, 220)},
    "medal":   {"name": "勇气勋章", "slot": "misc", "bonus": {"morale": 1}, "color": (240, 200, 70)},
    "clover":  {"name": "幸运四叶草", "slot": "misc", "bonus": {"luck": 1}, "color": (90, 200, 100)},
    "crown":   {"name": "王者之冠", "slot": "head", "bonus": {"atk": 1, "dfn": 1, "mana": 15}, "color": (250, 220, 120)},
    "boots":   {"name": "疾风之靴", "slot": "misc", "bonus": {"morale": 1, "mana": 5}, "color": (150, 220, 230)},
}


@dataclass
class Hero:
    name: str
    pos: tuple = (0, 0)
    mp: int = HERO_DAILY_MP
    level: int = 1
    xp: int = 0
    atk_bonus: int = 0
    dfn_bonus: int = 0
    mana: int = 20
    mana_max: int = 20
    spell_power: int = 2
    army: dict = field(default_factory=dict)  # UnitType -> count
    artifacts: list = field(default_factory=list)  # 宝物 key 列表（自动装备）

    def equip(self, art_key):
        """装备宝物，返回提示文本"""
        self.artifacts.append(art_key)
        b = ARTIFACTS[art_key]["bonus"]
        if "mana" in b:
            self.mana_max += b["mana"]
            self.mana += b["mana"]
        return ARTIFACTS[art_key]["name"]

    def _bonus_sum(self, kind):
        return sum(ARTIFACTS[a]["bonus"].get(kind, 0) for a in self.artifacts)

    def atk_total(self):
        return self.atk_bonus + self._bonus_sum("atk")

    def dfn_total(self):
        return self.dfn_bonus + self._bonus_sum("dfn")

    def morale(self):
        m = self._bonus_sum("morale")
        # 混编阵营（如人类+亡灵）士气 -1
        if len({ut.faction for ut in self.army}) > 1:
            m -= 1
        return m

    def luck(self):
        return self._bonus_sum("luck")

    def power_total(self):
        return self.spell_power + self._bonus_sum("spell_power")

    def total_units(self):
        return sum(self.army.values())

    def add_units(self, utype, count):
        self.army[utype] = self.army.get(utype, 0) + count

    def gain_xp(self, xp):
        self.xp += xp
        while self.xp >= self.level * 1000:
            self.xp -= self.level * 1000
            self.level += 1
            if self.level % 2 == 0:
                self.atk_bonus += 1
            else:
                self.dfn_bonus += 1
            self.mana_max += 5
            self.mana = self.mana_max


# 建筑定义
BUILDINGS = {
    "hall": {"name": "议会", "cost": {"gold": 2500}, "income": 1000, "desc": "每日金币收入 +1000"},
    "fort": {"name": "堡垒", "cost": {"gold": 2000, "wood": 10, "ore": 10}, "income": 0, "desc": "防御加成(预留)"},
    "dw1": {"name": "枪兵营", "cost": {"gold": 500}, "unit": "pikeman", "growth": 8, "desc": "每周招募枪兵 +8"},
    "dw2": {"name": "靶场", "cost": {"gold": 1000, "wood": 5}, "unit": "archer", "growth": 6, "desc": "每周招募弓箭手 +6"},
    "dw3": {"name": "狮鹫塔", "cost": {"gold": 1500, "ore": 5}, "unit": "griffin", "growth": 4, "desc": "每周招募狮鹫 +4"},
    "dw4": {"name": "修道院", "cost": {"gold": 2500, "wood": 5, "crystal": 3}, "unit": "swordsman", "growth": 3, "desc": "每周招募剑士 +3"},
    "market": {"name": "市场", "cost": {"gold": 1000, "wood": 5}, "desc": "资源买卖交易"},
}

# 市场汇率：1 单位资源 <-> 金币
MARKET_SELL = {"wood": 250, "ore": 250, "crystal": 500}
MARKET_BUY = {"wood": 500, "ore": 500, "crystal": 1000}


@dataclass
class Town:
    name: str
    pos: tuple
    owner: str = "player"
    buildings: set = field(default_factory=set)
    available: dict = field(default_factory=dict)  # unit key -> 可招募数量

    def weekly_growth(self):
        for b in self.buildings:
            info = BUILDINGS.get(b)
            if info and "unit" in info:
                self.available[info["unit"]] = self.available.get(info["unit"], 0) + info["growth"]

    def daily_income(self):
        inc = 500
        for b in self.buildings:
            info = BUILDINGS.get(b)
            if info and info.get("income"):
                inc += info["income"]
        return inc
