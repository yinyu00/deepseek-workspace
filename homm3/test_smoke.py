"""无头冒烟测试：地图生成/寻路/战斗/魔法/AI/敌方回合"""
import random, sys
sys.path.insert(0, ".")
from constants import *
from entities import UNITS, Hero
from combat import Battle, auto_resolve, SPELLS, SPELL_KEYS
from world import World

# 1. 世界生成 x5（含敌方英雄与敌城）
for seed in range(5):
    w = World(seed)
    assert w.monsters_alive() >= 8
    assert w.enemy_hero is not None
    assert any(t.owner == "enemy" for t in w.towns)
    ep = w.enemy_hero.pos
    assert ep not in w.objects or w.objects[ep]["type"] != OBJ_MONSTER, "敌将出生点不应有野怪"
print("world ok, monsters:", w.monsters_alive())

# 2. 战斗：双方 AI 自动打完
def player_ai(b):
    b.ai_act()  # ai_act 已支持双方向

army = {UNITS["pikeman"]: 15, UNITS["archer"]: 8}
b = Battle(army, {UNITS["skeleton"]: 10}, hero=Hero("t"))
steps = 0
while b.result is None and steps < 2000:
    steps += 1
    if b.cur is None:
        break
    b.ai_act()
    if b.result is None:
        b.next_unit()
print("battle ok:", b.result, "rounds:", b.round)

# 3. 全部魔法
h = Hero("m", mana=40)
b3 = Battle({UNITS["archer"]: 10}, {UNITS["ogre"]: 4, UNITS["wolf"]: 3}, hero=h)
t_ogre = next(u for u in b3.alive(1) if u.utype.key == "ogre")
ally = b3.alive(0)[0]
ok, _ = b3.cast("arrow", t_ogre); assert ok
ok, _ = b3.cast("lightning", t_ogre); assert not ok, "每轮只能施一次"
b3.new_round()
s_before = t_ogre.eff_speed
ok, _ = b3.cast("slow", t_ogre); assert ok and t_ogre.eff_speed == s_before - 2
b3.new_round()
s_a = ally.eff_speed
ok, _ = b3.cast("haste", ally); assert ok and ally.eff_speed == s_a + 2
b3.new_round()
ok, _ = b3.cast("lightning", t_ogre); assert ok
ok, _ = b3.cast("arrow", ally); assert not ok, "arrow 只能打敌方"
assert h.mana == 40 - 5 - 4 - 4 - 8
print("spells ok, mana:", h.mana)

# 4. 自动战斗（AI vs AI）
res, surv_a, surv_b = auto_resolve({UNITS["pikeman"]: 20}, {UNITS["skeleton"]: 15})
assert res in ("win", "lose")
print("auto_resolve ok:", res, surv_a, surv_b)

# 5. 敌方 AI 回合（端到端：模拟 Game 不含渲染）
import pygame
import main as M
pygame.init()
screen = pygame.display.set_mode((M.W, M.H))
fonts = {s: M.get_font(s, bold=(s >= 40)) for s in (16, 18, 19, 20, 22, 24, 40, 42, 48)}
game = M.Game()
for day in range(10):
    game.end_day()
    game.scene.update(1 / 60)
    game.scene.draw(screen, fonts)
    if game.enemy_attacks:  # 敌将追上玩家
        game.enemy_attacks = False
        break
print("enemy turn ok, day:", game.world.day, "enemy at:", game.world.enemy_hero.pos if game.world.enemy_hero else None)

# 6. 场景渲染
game.scene.draw(screen, fonts)
game.hero.pos = game.world.towns[0].pos
ts = M.TownScene(game)
ts.draw(screen, fonts)
from entities import UNITS as U
mpos = next(p for p, o in game.world.objects.items() if o["type"] == OBJ_MONSTER)
game.hero.pos = (max(0, mpos[0] - 1), mpos[1])
cs = M.CombatScene(game, {U[mpos and game.world.objects[mpos]["unit"]]: game.world.objects[mpos]["count"]})
for i in range(30):
    cs.update(1 / 60)
    cs.draw(screen, fonts)
print("ALL SMOKE TESTS PASSED")

# 7. 宝物装备与属性加成
from entities import Hero as H2, ARTIFACTS
h2 = H2("测试", army={UNITS["pikeman"]: 10})
assert h2.morale() == 0 and h2.luck() == 0
h2.equip("sword"); h2.equip("medal"); h2.equip("clover"); h2.equip("orb")
assert h2.atk_total() == 3 and h2.morale() == 1 and h2.luck() == 1
assert h2.power_total() == 4 and h2.mana_max == 20 + 10
print("artifacts ok:", [ARTIFACTS[a]["name"] for a in h2.artifacts])

# 8. 士气/运气触发（统计验证，固定种子）
import random as R
mor_hits = 0
for t in range(60):
    hh = H2("m", army={UNITS["pikeman"]: 30})
    hh.equip("medal"); hh.equip("boots")  # 士气+2 → 10%/次
    bb = Battle(hh.army, {UNITS["skeleton"]: 25}, hero=hh, rng=R.Random(1000 + t))
    while bb.result is None:
        if bb.cur is None: break
        bb.ai_act()
        if bb.result is None: bb.next_unit()
    mor_hits += sum(1 for l in bb.log if "士气高涨" in l)
assert mor_hits > 0, "士气应至少触发一次"
print("morale triggered:", mor_hits, "times in 60 battles")

luck_hits = 0
for t in range(60):
    hh = H2("l", army={UNITS["archer"]: 20})
    for _ in range(4): hh.equip("clover")  # 运气+4 → 20%
    bb = Battle(hh.army, {UNITS["golem"]: 15}, hero=hh, rng=R.Random(2000 + t))
    while bb.result is None:
        if bb.cur is None: break
        bb.ai_act()
        if bb.result is None: bb.next_unit()
    luck_hits += sum(1 for l in bb.log if "幸运一击" in l)
assert luck_hits > 0, "运气应至少触发一次"
print("luck triggered:", luck_hits, "times in 60 battles")

# 9. 世界里的宝物对象含 art 键
w9 = World(7)
arts = [o for o in w9.objects.values() if o["type"] == OBJ_ARTIFACT]
assert len(arts) >= 4 and all("art" in o and o["art"] in ARTIFACTS for o in arts)
print("map artifacts:", len(arts))
print("ROUND3 TESTS PASSED")

# 10. 多英雄：雇佣/切换/转兵
import pygame
import main as M2
pygame.init()
screen = pygame.display.set_mode((M2.W, M2.H))
fonts = {s: M2.get_font(s, bold=(s >= 40)) for s in (16,18,19,20,22,24,40,42,48)}
g = M2.Game()
g.world.player_res["gold"] = 99999
tp = g.world.towns[0].pos
assert g.hire_hero(tp) and len(g.heroes) == 2
assert g.hero.pos == tp and g.hero.name == "艾拉"
g.active_idx = 0
h0 = g.heroes[0]
n0 = h0.total_units()
g.heroes[1].army = {}  # 清空方便接收
# 转移：do give5（把英雄0的兵转给英雄1）
h0.pos = tp
ts = M2.TownScene(g)
ts.do("give5", 1)
assert h0.total_units() < n0 and g.heroes[1].total_units() > 0, "转兵失败"
print("transfer ok:", h0.total_units(), "->", g.heroes[1].total_units())
# 多英雄回合并渲染
g.active_idx = 0
g.hero.pos = (4, 8); g.heroes[1].pos = (6, 9)
g.end_day()
for h in g.heroes:
    assert h.mp == HERO_DAILY_MP
g.scene.draw(screen, fonts)
g.active_idx = 1
g.heroes[1].pos = tp
ts2 = M2.TownScene(g)  # 英雄1站在城里
ts2.draw(screen, fonts)
g.active_idx = 0
g.hero.pos = tp
ts3 = M2.TownScene(g)
ts3.draw(screen, fonts)
print("ROUND4 TESTS PASSED")

# 11. 存档/读档往返
import savegame as SV
g = M2.Game()
g.world.player_res["gold"] = 12345
g.world.day = 9
g.hero.equip("sword"); g.hero.equip("medal")
g.hero.gain_xp(1500)
g.heroes_at = g.heroes_at  # keep
g.hire_hero(g.world.towns[0].pos) if False else None
g.world.mines_owned.add((5, 5))
before = {
    "gold": g.world.player_res["gold"], "day": g.world.day,
    "atk": g.hero.atk_total(), "morale": g.hero.morale(),
    "mines": len(g.world.mines_owned),
    "monsters": g.world.monsters_alive(),
    "army0": sorted((ut.key, n) for ut, n in g.hero.army.items()),
    "enemy_pos": g.world.enemy_hero.pos if g.world.enemy_hero else None,
}
p = SV.save(g, "/tmp/homm3_save_test.json")
g2 = SV.load(p)
after = {
    "gold": g2.world.player_res["gold"], "day": g2.world.day,
    "atk": g2.hero.atk_total(), "morale": g2.hero.morale(),
    "mines": len(g2.world.mines_owned),
    "monsters": g2.world.monsters_alive(),
    "army0": sorted((ut.key, n) for ut, n in g2.hero.army.items()),
    "enemy_pos": g2.world.enemy_hero.pos if g2.world.enemy_hero else None,
}
assert before == after, (before, after)
assert len(g2.world.towns) == len(g.world.towns)
assert g2.world.towns[1].owner == "enemy"
# 敌城 garrison 回链
tp = g2.world.towns[1].pos
assert tp in g2.world.objects and g2.world.objects[tp]["ref"] is g2.world.towns[1]
assert sum(g2.world.objects[tp]["garrison"].values()) > 0
# 读档后可以继续战斗
cs = M2.CombatScene(g2, {UNITS["skeleton"]: 5})
cs.draw(screen, fonts)
print("ROUND5 SAVE/LOAD PASSED")

# 12. 六边形战场：邻接/距离/可达/渲染拾取
from combat import hex_neighbors, hex_dist, in_field, BW as CBW, BH as CBH
assert sorted(hex_neighbors(0, 0)) == sorted([(-1, 0), (1, 0), (-1, -1), (0, -1), (-1, 1), (0, 1)])
assert sorted(hex_neighbors(0, 1)) == sorted([(-1, 1), (1, 1), (0, 0), (1, 0), (0, 2), (1, 2)])
assert hex_dist((0, 0), (1, 0)) == 1 and hex_dist((0, 0), (0, 1)) == 1
assert hex_dist((0, 0), (2, 1)) == 3 and hex_dist((3, 4), (3, 4)) == 0
assert hex_dist((0, 0), (3, 0)) == 3 and hex_dist((0, 0), (1, 1)) == 2
# 每个邻居互为邻居
for p in [(c, r) for c in range(CBW) for r in range(CBH)]:
    for nb in hex_neighbors(*p):
        if in_field(nb):
            assert p in hex_neighbors(*nb)
# BFS 可达遵守六边形邻接
bb = Battle({UNITS["griffin"]: 5}, {UNITS["skeleton"]: 8})
u0 = bb.alive(0)[0]
reach = bb.move_reachable(u0)
assert all(hex_dist(u0.pos, p) <= u0.eff_speed for p in reach)
assert in_field(u0.pos)
# 完整战斗（六边形）跑通
while bb.result is None:
    if bb.cur is None: break
    bb.ai_act()
    if bb.result is None: bb.next_unit()
print("hex battle ok:", bb.result)
# 渲染 + 鼠标拾取往返
import main as M3
g = M3.Game()
cs = M3.CombatScene(g, {UNITS["wolf"]: 4})
cs.draw(screen, fonts)
for c in range(CBW):
    for r in range(CBH):
        cx, cy = M3.CombatScene.hex_center(c, r)
        assert cs.tile_at((cx, cy)) == (c, r), (c, r)
assert cs.tile_at((10, 10)) is None
colors = len({screen.get_at((x, y))[:3] for x in range(0, M3.W, 11) for y in range(0, M3.H, 11)})
assert colors > 30
print("ROUND6 HEX TESTS PASSED, colors:", colors)

# 13. 市场：买卖汇率与边界
from entities import MARKET_SELL, MARKET_BUY
g = M2.Game()
tp = g.world.towns[0].pos
g.hero.pos = tp
g.world.towns[0].buildings.add("market")
ts = M2.TownScene(g)
g.world.player_res.update({"gold": 1000, "wood": 3, "ore": 0, "crystal": 0})
ts.do("sell", ("wood", 5))          # 只能卖 3
assert g.world.player_res["wood"] == 0 and g.world.player_res["gold"] == 1000 + 3 * MARKET_SELL["wood"]
ts.do("buy", ("crystal", 5))        # 金币只够买 1 个水晶? 1750//1000=1
assert g.world.player_res["crystal"] == 1
assert g.world.player_res["gold"] == 1000 + 3 * MARKET_SELL["wood"] - MARKET_BUY["crystal"]
g.world.player_res["gold"] = 0
before = g.world.player_res["gold"]
ts.do("buy", ("ore", 1))            # 没钱
assert g.world.player_res["gold"] == before and g.world.player_res["ore"] == 0
ts.draw(screen, fonts)
print("market ok, gold:", g.world.player_res["gold"])

# 14. 新魔法：治疗 / 火球溅射
h4 = H2("圣骑士", mana=60, army={UNITS["swordsman"]: 10})
b4 = Battle(h4.army, {UNITS["skeleton"]: 20, UNITS["wolf"]: 6}, hero=h4)
ally = b4.alive(0)[0]
enemy = b4.alive(1)[0]
# 先打掉自己一些兵再治疗
ally.count = 4
b4.new_round()
ok, _ = b4.cast("heal", ally)
assert ok and ally.count > 4, "治疗应恢复数量"
assert ally.count <= ally.start_count
print("heal ok: 4 ->", ally.count)
# 火球：让两个敌方单位相邻
enemies = b4.alive(1)
enemies[0].pos = (6, 3)
enemies[1].pos = (6, 4)  # 相邻六边形
b4.new_round()
c1, c2 = enemies[0].count, enemies[1].count
ok, _ = b4.cast("fireball", enemies[0])
assert ok and enemies[0].count < c1 and enemies[1].count < c2, "溅射应伤及邻格"
assert h4.mana == 60 - 6 - 9
print("fireball ok:", c1, "->", enemies[0].count, ";", c2, "->", enemies[1].count)
# 渲染法术栏（6 法术）
g.scene.draw(screen, fonts)
print("ROUND7 TESTS PASSED")

# 15. 亡灵阵营：混编士气 / 吸血 / 敌军构成
from entities import UNDEAD_POOL
assert all(UNITS[k].faction == "undead" for k in UNDEAD_POOL)
assert UNITS["vampire"].lifesteal and UNITS["pikeman"].faction == "castle"
# 混编士气惩罚
h5 = H2("混合")
h5.army = {UNITS["pikeman"]: 10, UNITS["skeleton"]: 5}
assert h5.morale() == -1, "混编应 -1 士气"
h5.army = {UNITS["pikeman"]: 10, UNITS["archer"]: 5}
assert h5.morale() == 0, "同阵营无惩罚"
h5.equip("medal")
h5.army = {UNITS["pikeman"]: 10, UNITS["skeleton"]: 5}
assert h5.morale() == 0, "勋章抵消混编"
print("morale mixing ok")
# 吸血：吸血鬼受损后攻击回血
b5 = Battle({UNITS["vampire"]: 10}, {UNITS["zombie"]: 15})
v = b5.alive(0)[0]
v.count = 5  # 先受损
z = b5.alive(1)[0]
n_before = v.count
b5.do_attack(v, z)
assert v.count >= n_before, "吸血鬼攻击后数量不应减少（吸血）"
print("lifesteal ok:", n_before, "->", v.count)
# 敌军初始为亡灵
g6 = M2.Game()
eh = g6.world.enemy_hero
assert all(ut.faction == "undead" for ut in eh.army), "敌将应全亡灵"
gar = g6.world.objects[g6.world.towns[1].pos]["garrison"]
assert all(ut.faction == "undead" for ut in gar)
print("enemy undead ok:", {ut.name: n for ut, n in eh.army.items()})
# 亡灵战斗渲染
cs = M2.CombatScene(g6, dict(eh.army), enemy_hero=eh)
cs.draw(screen, fonts)
print("ROUND8 TESTS PASSED")

# 16. 亡灵祭坛：每周一次
g = M2.Game()
shrine_pos = next(p for p, o in g.world.objects.items() if o["type"] == OBJ_SHRINE)
g.hero.pos = shrine_pos
n0 = g.hero.total_units()
g.scene.interact(shrine_pos)
assert g.hero.total_units() > n0, "祭坛应给兵"
n1 = g.hero.total_units()
g.scene.interact(shrine_pos)
assert g.hero.total_units() == n1, "同周第二次不应给兵"
g.world.day = 8  # 下周
g.scene.interact(shrine_pos)
assert g.hero.total_units() > n1, "新一周应再给"
print("shrine ok:", n0, "->", n1, "->", g.hero.total_units())

# 17. 端到端通关模拟（用真实游戏逻辑组件）
g = M2.Game()
g.hero.army = {UNITS["cavalier"]: 50, UNITS["monk"]: 30}  # 强力军
# 扫清所有野怪
for pos in [p for p, o in list(g.world.objects.items()) if o["type"] == OBJ_MONSTER]:
    m = g.world.objects[pos]
    res, surv, _ = auto_resolve(g.hero.army, {UNITS[m["unit"]]: m["count"]}, hero_a=g.hero)
    g.hero.army = surv
    if res == "win":
        del g.world.objects[pos]
assert g.world.monsters_alive() == 0
# 击败敌将
eh = g.world.enemy_hero
res, surv, _ = auto_resolve(g.hero.army, eh.army, hero_a=g.hero, hero_b=eh)
g.hero.army = surv
assert res == "win"
g.world.enemy_hero = None
assert not g.victory(), "还差攻城"
# 攻占敌城
et = next(t for t in g.world.towns if t.owner == "enemy")
gar = g.world.objects[et.pos]["garrison"]
res, surv, _ = auto_resolve(g.hero.army, gar, hero_a=g.hero)
et.owner = "player"
g.world.objects[et.pos].pop("garrison", None)
assert g.victory(), "应已胜利"
g.scene.draw(screen, fonts)  # 胜利画面渲染
print("E2E VICTORY OK, army left:", g.hero.total_units())
print("ROUND10 TESTS PASSED")
