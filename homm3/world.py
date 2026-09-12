"""地图生成 + 寻路"""
import random
from constants import *
from entities import UNITS, NEUTRAL_POOL


def in_bounds(x, y):
    return 0 <= x < MAP_W and 0 <= y < MAP_H


class World:
    def __init__(self, seed=None, do_gen=True):
        self.rng = random.Random(seed)
        self.terrain = [[T_GRASS] * MAP_H for _ in range(MAP_W)]
        self.objects = {}  # (x,y) -> dict(type=..., ...)
        self.hero = None
        self.enemy_hero = None  # 敌方 AI 英雄
        self.towns = []
        self.day = 1
        self.player_res = {"gold": 3000, "wood": 10, "ore": 10, "crystal": 2}
        self.mines_owned = set()
        self.roads = set()  # (x,y) 道路格
        if do_gen:
            self.gen()

    @classmethod
    def blank(cls):
        return cls(do_gen=False)

    # ---------- 生成 ----------
    def gen(self):
        rng = self.rng
        # 随机障碍：水与山
        for _ in range(26):
            x, y = rng.randrange(2, MAP_W - 2), rng.randrange(1, MAP_H - 1)
            t = T_WATER if rng.random() < 0.45 else T_ROCK
            for dx in range(rng.randint(1, 3)):
                for dy in range(rng.randint(1, 2)):
                    if in_bounds(x + dx, y + dy):
                        self.terrain[x + dx][y + dy] = t
        # 泥土路点缀
        for _ in range(30):
            x, y = rng.randrange(MAP_W), rng.randrange(MAP_H)
            if self.terrain[x][y] == T_GRASS:
                self.terrain[x][y] = T_DIRT

        def free(pos):
            x, y = pos
            return in_bounds(x, y) and self.terrain[x][y] in PASSABLE and pos not in self.objects

        def place(kind, count, maker):
            placed = 0
            tries = 0
            while placed < count and tries < 800:
                tries += 1
                pos = (rng.randrange(MAP_W), rng.randrange(MAP_H))
                if pos == (2, MAP_H // 2) or not free(pos):
                    continue
                self.objects[pos] = maker(pos)
                placed += 1

        from entities import Town
        # 玩家城镇（左中）与英雄
        self.towns_clear((2, MAP_H // 2))
        town = Town("光辉城", (2, MAP_H // 2))
        town.buildings.add("dw1")
        town.available["pikeman"] = 8
        self.towns.append(town)
        self.objects[(2, MAP_H // 2)] = {"type": OBJ_TOWN, "ref": town}

        place(OBJ_RESOURCE, 14, lambda p: {
            "type": OBJ_RESOURCE, "res": self.rng.choice(RES_LIST),
            "amount": {"gold": (500, 1000, 1500), "wood": (4, 6), "ore": (4, 6), "crystal": (2, 3)} and self.rng.choice(
                {"gold": [500, 1000, 1500], "wood": [4, 6], "ore": [4, 6], "crystal": [2, 3]}[
                    self.rng.choice(RES_LIST)])})
        # 修正：上面 amount 与 res 可能不一致，重写
        for pos, obj in list(self.objects.items()):
            if obj["type"] == OBJ_RESOURCE:
                tbl = {"gold": [500, 1000, 1500], "wood": [4, 6], "ore": [4, 6], "crystal": [2, 3]}
                obj["amount"] = rng.choice(tbl[obj["res"]])

        mines = ["sawmill", "orepit", "crystalcave", "goldmine", "sawmill", "orepit"]
        place(OBJ_MINE, len(mines), lambda p: {"type": OBJ_MINE, "mine": mines.pop(0) if mines else "sawmill"})
        place(OBJ_CHEST, 5, lambda p: {"type": OBJ_CHEST})
        from entities import ARTIFACTS
        art_keys = list(ARTIFACTS.keys())
        place(OBJ_ARTIFACT, 6, lambda p: {"type": OBJ_ARTIFACT,
                                          "art": rng.choice(art_keys),
                                          "atk": 0})
        # 亡灵祭坛：每周可招募一批免费亡灵
        place(OBJ_SHRINE, 3, lambda p: {"type": OBJ_SHRINE, "week_used": 0})

        # 野怪：强度随与城镇的距离增加
        def monster_maker(p):
            d = abs(p[0] - 2) / MAP_W
            if d > 0.75 and rng.random() < 0.35:
                key, cnt = "dragon", rng.randint(1, 2)
            else:
                key = rng.choice(NEUTRAL_POOL[:-1])
                cnt = rng.randint(4, 8 + int(d * 20))
            return {"type": OBJ_MONSTER, "unit": key, "count": cnt}

        place(OBJ_MONSTER, 12, monster_maker)

        # 道路网络：主城→敌城、主城→矿（A* 会自动绕开水/山）
        roads = set()
        ptown = (2, MAP_H // 2)
        targets = [next((p for p, o in self.objects.items()
                         if o["type"] == OBJ_MINE and MINE_RES[o["mine"]] != "gold"), None)]
        etown0 = (MAP_W - 3, MAP_H // 2)
        for tgt in [t for t in targets if t] + [etown0]:
            pth = self.astar(ptown, tgt)
            if pth:
                roads.update(pth)
        roads.discard(etown0)
        self.roads = roads

        # 敌方城镇（右中）与敌方英雄
        from entities import Town as Town2, Hero as Hero2, UNITS as U2
        et_pos = (MAP_W - 3, MAP_H // 2)
        self.towns_clear(et_pos)
        etown = Town2("暗影堡", et_pos, owner="enemy")
        etown.buildings.update({"dw1", "dw2", "dw3"})
        etown.available = {}
        self.towns.append(etown)
        self.objects[et_pos] = {"type": OBJ_TOWN, "ref": etown,
                                "garrison": {U2["skeleton"]: 10, U2["zombie"]: 6, U2["wraith"]: 3}}
        self.enemy_hero = Hero2("莫甘娜", (et_pos[0] - 1, et_pos[1]),
                                army={U2["skeleton"]: 15, U2["zombie"]: 8, U2["wraith"]: 4})
        self.enemy_hero.atk_bonus = 2

    def towns_clear(self, pos):
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                x, y = pos[0] + dx, pos[1] + dy
                if in_bounds(x, y):
                    self.terrain[x][y] = T_GRASS
                    self.objects.pop((x, y), None)

    # ---------- 查询 ----------
    def passable(self, pos):
        x, y = pos
        if not in_bounds(x, y) or self.terrain[x][y] not in PASSABLE:
            return False
        obj = self.objects.get(pos)
        if obj:
            if obj["type"] in (OBJ_TOWN, OBJ_MINE, OBJ_RESOURCE, OBJ_CHEST, OBJ_ARTIFACT):
                return True  # 可走上去交互
            if obj["type"] == OBJ_MONSTER:
                return True  # 可攻击（走近触发战斗）
        return True

    def monsters_alive(self):
        return sum(1 for o in self.objects.values() if o["type"] == OBJ_MONSTER)

    # ---------- 可达范围（BFS，供移动高亮） ----------
    def reachable(self, start, max_steps):
        from collections import deque
        if max_steps <= 0:
            return {start}
        dist = {start: 0}
        dq = deque([start])
        while dq:
            p = dq.popleft()
            if dist[p] >= max_steps:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                np = (p[0] + dx, p[1] + dy)
                if np in dist or not self.passable(np):
                    continue
                dist[np] = dist[p] + 1
                dq.append(np)
        return set(dist)

    # ---------- A* 寻路 ----------
    def astar(self, start, goal):
        if start == goal:
            return [start]
        import heapq
        openq = [(0, start)]
        came = {start: None}
        cost = {start: 0}

        def h(p):
            return abs(p[0] - goal[0]) + abs(p[1] - goal[1])

        while openq:
            _, cur = heapq.heappop(openq)
            if cur == goal:
                break
            x, y = cur
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                np = (x + dx, y + dy)
                if not self.passable(np) and np != goal:
                    continue
                if not self.passable(np):
                    continue
                nc = cost[cur] + 1
                if np not in cost or nc < cost[np]:
                    cost[np] = nc
                    came[np] = cur
                    heapq.heappush(openq, (nc + h(np), np))
        if goal not in came:
            return None
        path = []
        cur = goal
        while cur:
            path.append(cur)
            cur = came[cur]
        return path[::-1]
