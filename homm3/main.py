"""英雄无敌3 复刻 —— 主程序
运行: .venv/bin/python main.py
"""
import sys
import random
import pygame
from constants import *
from entities import Hero, Town, UNITS, BUILDINGS
from world import World
from combat import Battle, auto_resolve, BW, BH, BTILE, SPELLS, SPELL_KEYS
import sounds
import assets

W, H = 1480, 860
MAP_OX, MAP_OY = 10, 90
SIDE_X = MAP_OX + MAP_W * TILE + 12

FONT_NAMES = "pingfangsc,stheiti,hiraginosansgb,arialunicodems,microsoftyahei,heiti,simsun"


def get_font(size, bold=False):
    try:
        return pygame.font.SysFont(FONT_NAMES, size, bold=bold)
    except Exception:
        return pygame.font.Font(None, size)


class Game:
    HERO_HIRE_COST = 2500
    MAX_HEROES = 3

    def __init__(self):
        self.world = World(seed=random.randrange(1 << 30))
        hero_army = {UNITS["pikeman"]: 12, UNITS["archer"]: 6}
        self.heroes = [Hero("克里斯蒂安", (2, MAP_H // 2 + 1), army=hero_army)]
        self.active_idx = 0
        self.scene = AdventureScene(self)
        self.running = True
        self.msg = ["欢迎来到魔法门之英雄无敌3（复刻版）",
                    "目标：击败敌方英雄莫甘娜并攻占暗影堡！",
                    "TAB 切换英雄 | 城内可雇佣英雄/调度部队",
                    "小心：敌人每天都会向你的英雄逼近……"]
        self.enemy_attacks = False

    @property
    def hero(self):
        return self.heroes[self.active_idx]

    def heroes_at(self, pos):
        return [h for h in self.heroes if h.pos == pos]

    def hire_hero(self, town_pos):
        names = ["罗兰德", "艾拉", "桑德罗"]
        if len(self.heroes) >= self.MAX_HEROES:
            self.notify("英雄数量已达上限（%d）" % self.MAX_HEROES)
            return False
        if self.world.player_res["gold"] < self.HERO_HIRE_COST:
            self.notify("金币不足（雇佣英雄需 %d）" % self.HERO_HIRE_COST)
            return False
        self.world.player_res["gold"] -= self.HERO_HIRE_COST
        name = names[len(self.heroes) % len(names)]
        h = Hero(name, town_pos, army={UNITS["pikeman"]: 5})
        self.heroes.append(h)
        self.active_idx = len(self.heroes) - 1
        self.notify("雇佣了英雄 %s！" % name)
        return True

    def set_scene(self, scene):
        self.scene = scene

    def notify(self, text):
        self.msg.append(text)
        self.msg = self.msg[-6:]

    # ---------- 胜利判定 ----------
    def victory(self):
        w = self.world
        return (w.enemy_hero is None and
                all(t.owner == "player" for t in w.towns))

    def end_day(self):
        w = self.world
        w.day += 1
        res = w.player_res
        for town in w.towns:
            if town.owner == "player":
                res["gold"] += town.daily_income()
        for pos in w.mines_owned:
            obj = w.objects[pos]
            r = MINE_RES[obj["mine"]]
            res[r] += MINE_WEEK[r]
        for h in self.heroes:
            h.mp = HERO_DAILY_MP
            h.mana = min(h.mana + 3, h.mana_max)
        if (w.day - 1) % 7 == 0:  # 周一
            for town in w.towns:
                town.weekly_growth()
            self.notify("新的一周！城镇兵源刷新。")
        self.notify("第 %d 天开始。" % w.day)
        self.enemy_turn()

    # ---------- 敌方 AI 回合 ----------
    def enemy_turn(self):
        w = self.world
        eh = w.enemy_hero
        if eh is None:
            return
        # 周一增援（亡灵阵营）
        if (w.day - 1) % 7 == 0:
            eh.add_units(UNITS["skeleton"], 6 + w.day // 7)
            eh.add_units(UNITS["zombie"], 3 + w.day // 14)
            if w.day >= 14:
                eh.add_units(UNITS["vampire"], 1 + w.day // 21)
            if w.day >= 28:
                eh.add_units(UNITS["lich"], 1)
            self.notify("敌军亡灵大军获得了增援！")
        eh.mp = 10000  # AI 每天固定步数
        target = min(self.heroes, key=lambda h: abs(h.pos[0] - eh.pos[0]) + abs(h.pos[1] - eh.pos[1])).pos
        path = w.astar(eh.pos, target)
        if not path or len(path) < 2:
            return
        steps = min(10, len(path) - 1)
        for i in range(steps):
            nxt = path[i + 1]
            hit = [h for h in self.heroes if h.pos == nxt]
            if hit:  # 追上玩家英雄 → 进攻该英雄
                self.active_idx = self.heroes.index(hit[0])
                self.notify("敌将莫甘娜向 %s 发起进攻！" % hit[0].name)
                self.enemy_attacks = True
                return
            obj = w.objects.get(nxt)
            if obj and obj["type"] == OBJ_MONSTER:
                marmy = {UNITS[obj["unit"]]: obj["count"]}
                result, surv_e, surv_m = auto_resolve(eh.army, marmy, hero_b=eh)
                eh.army = surv_e
                if result != "win":
                    w.enemy_hero = None
                    self.notify("敌将被野怪消灭了！")
                    return
                # 野怪被削弱或消灭
                remain = sum(surv_m.values())
                if remain <= 0:
                    del w.objects[nxt]
                else:
                    uk = list(surv_m)[0]
                    obj["unit"], obj["count"] = uk.key, remain
            eh.pos = nxt


# ---------------- 冒险地图场景 ----------------
class AdventureScene:
    def __init__(self, game):
        self.g = game
        self.path = None
        self.move_timer = 0

    def tile_at(self, mpos):
        x = (mpos[0] - MAP_OX) // TILE
        y = (mpos[1] - MAP_OY) // TILE
        if 0 <= x < MAP_W and 0 <= y < MAP_H:
            return (int(x), int(y))
        return None

    def start_battle(self, enemy_army, enemy_hero=None, on_win=None):
        g = self.g

        def ow(b):
            g.hero.army = b.survivors(0)
            if on_win:
                on_win(b)

        g.set_scene(CombatScene(g, enemy_army, enemy_hero=enemy_hero, on_win=ow))

    def handle_event(self, ev):
        g = self.g
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            t = self.tile_at(ev.pos)
            if t and t != g.hero.pos:
                self.path = g.world.astar(g.hero.pos, t)
                if self.path and len(self.path) > 1:
                    self.path = self.path[1:]
        elif ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_e:
                g.end_day()
            elif ev.key == pygame.K_m:
                on = sounds.toggle()
                g.notify("音效: %s" % ("开" if on else "关"))
            elif ev.key == pygame.K_F5:
                import savegame
                savegame.save(g)
                g.notify("已存档 → %s" % savegame.SAVE_PATH)
            elif ev.key == pygame.K_F9:
                import savegame
                try:
                    return savegame.load()  # 由 main 循环接管
                except FileNotFoundError:
                    g.notify("没有找到存档文件")
                except Exception as ex:
                    g.notify("读档失败: %s" % ex)
            elif ev.key == pygame.K_TAB:
                g.active_idx = (g.active_idx + 1) % len(g.heroes)
                self.path = None
                g.notify("切换英雄 → %s" % g.hero.name)
            elif ev.key == pygame.K_t:
                for town in g.world.towns:
                    if town.pos == g.hero.pos and town.owner == "player":
                        g.set_scene(TownScene(g))

    def update(self, dt):
        g = self.g
        # 敌方主动进攻
        if g.enemy_attacks:
            g.enemy_attacks = False
            eh = g.world.enemy_hero
            if eh:
                self.start_battle(eh.army, enemy_hero=eh, on_win=lambda b: self.kill_enemy_hero())
            return
        if self.path:
            self.move_timer -= dt
            if self.move_timer <= 0:
                nxt = self.path[0]
                if g.hero.mp < HERO_MP_PER_TILE:
                    self.path = None
                    g.notify("移动力不足，按 E 结束回合。")
                    return
                obj = g.world.objects.get(nxt)
                eh = g.world.enemy_hero
                if obj and obj["type"] == OBJ_MONSTER:
                    self.path = None
                    self.start_battle({UNITS[obj["unit"]]: obj["count"]},
                                      on_win=lambda b, p=nxt: g.world.objects.pop(p, None))
                    return
                if eh and nxt == eh.pos:
                    self.path = None
                    self.start_battle(eh.army, enemy_hero=eh, on_win=lambda b: self.kill_enemy_hero())
                    return
                if any(h.pos == nxt for h in g.heroes if h is not g.hero):
                    self.path = None
                    g.notify("该格有己方英雄。")
                    return
                if obj and obj["type"] == OBJ_TOWN and obj["ref"].owner == "enemy":
                    self.path = None
                    gar = obj["garrison"]

                    def capture(b, o=obj):
                        o["ref"].owner = "player"
                        o.pop("garrison", None)
                        o["ref"].available = {"pikeman": 5, "archer": 3}
                        g.notify("攻占暗影堡！城镇归你。")
                    self.start_battle(dict(gar), on_win=capture)
                    return
                g.hero.pos = nxt
                g.hero.mp -= HERO_MP_PER_TILE
                self.path.pop(0)
                if not self.path:
                    self.path = None
                self.interact(nxt)
                sounds.play("step")
                self.move_timer = 0.13

    def kill_enemy_hero(self):
        self.g.world.enemy_hero = None
        self.g.notify("敌将莫甘娜被击败！")

    def interact(self, pos):
        g = self.g
        obj = g.world.objects.get(pos)
        if not obj:
            return
        t = obj["type"]
        if t == OBJ_RESOURCE:
            r = obj["res"]
            g.world.player_res[r] += obj["amount"]
            sounds.play("pickup")
            g.notify("拾取 %s x%d" % (RES_CN[r], obj["amount"]))
            del g.world.objects[pos]
        elif t == OBJ_MINE:
            if pos not in g.world.mines_owned:
                g.world.mines_owned.add(pos)
                sounds.play("pickup")
                g.notify("占领 %s（每周产出）" % MINE_CN[obj["mine"]])
        elif t == OBJ_CHEST:
            gold = random.choice([1000, 1500, 2000])
            g.world.player_res["gold"] += gold
            sounds.play("coin")
            g.notify("打开宝箱，获得金币 %d" % gold)
            del g.world.objects[pos]
        elif t == OBJ_ARTIFACT:
            name = g.hero.equip(obj["art"])
            sounds.play("pickup")
            g.notify("获得宝物【%s】并装备！" % name)
            del g.world.objects[pos]
        elif t == OBJ_TOWN:
            if obj["ref"].owner == "player":
                g.notify("按 T 进入城镇 %s" % obj["ref"].name)
        elif t == OBJ_SHRINE:
            week = (g.world.day - 1) // 7 + 1
            if obj.get("week_used", 0) >= week:
                g.notify("祭坛寂静无声（本周已使用）")
                return
            obj["week_used"] = week
            roll = random.random()
            if roll < 0.5:
                ut, n = UNITS["skeleton"], random.randint(6, 10)
            elif roll < 0.8:
                ut, n = UNITS["zombie"], random.randint(3, 5)
            elif g.world.day >= 14:
                ut, n = UNITS["wraith"], random.randint(2, 3)
            else:
                ut, n = UNITS["skeleton"], random.randint(8, 12)
            g.hero.add_units(ut, n)
            sounds.play("spell")
            g.notify("祭坛授予你 %s x%d！（注意混编士气）" % (ut.name, n))

    def draw(self, screen, fonts):
        g = self.g
        w = g.world
        screen.fill((28, 30, 38))
        from constants import T_GRASS, T_DIRT, T_WATER, T_ROCK
        ck = (g.hero.pos, g.hero.mp)
        if getattr(self, "_reach_ck", None) != ck:
            self._reach_ck = ck
            self._reach_set = w.reachable(g.hero.pos, g.hero.mp // HERO_MP_PER_TILE)
        reach_set = self._reach_set
        terr_key = {T_GRASS: "terrain_grass", T_DIRT: "terrain_grass",
                    T_WATER: "terrain_water", T_ROCK: "terrain_rock"}
        grass_vars = ["terrain_grass", "terrain_grass2", "terrain_grass3"]
        for x in range(MAP_W):
            for y in range(MAP_H):
                tx, ty = MAP_OX + x * TILE, MAP_OY + y * TILE
                key = terr_key[w.terrain[x][y]]
                if w.terrain[x][y] in (T_GRASS, T_DIRT):
                    key = grass_vars[(x * 7 + y * 13) % 3]  # 变体轮换破平铺感
                spr = assets.get(key, TILE)
                if spr:
                    screen.blit(spr, (tx, ty))
                else:
                    pygame.draw.rect(screen, TERRAIN_COLOR[w.terrain[x][y]],
                                     (tx, ty, TILE - 1, TILE - 1))
        # 道路：连续圆角带（深色路肩 + 浅米色路面），按相邻道路格连接
        def road_neighbors(p):
            return [(p[0] + dx, p[1] + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                    if (p[0] + dx, p[1] + dy) in w.roads]
        for (x, y) in w.roads:
            cx, cy = MAP_OX + x * TILE + TILE // 2, MAP_OY + y * TILE + TILE // 2
            nbs = road_neighbors((x, y))
            if not nbs:
                nbs = [(x, y)]
            for width, color in ((24, (120, 100, 70)), (16, (216, 198, 162))):
                for nx, ny in nbs:
                    ex = MAP_OX + nx * TILE + TILE // 2
                    ey = MAP_OY + ny * TILE + TILE // 2
                    pygame.draw.line(screen, color, (cx, cy), (ex, ey), width)
                pygame.draw.circle(screen, color, (cx, cy), width // 2)
        for x in range(MAP_W):
            for y in range(MAP_H):
                tx, ty = MAP_OX + x * TILE, MAP_OY + y * TILE
                # 本回合可达格微高亮
                if (x, y) in reach_set:
                    ov = pygame.Surface((TILE, TILE), pygame.SRCALPHA)
                    ov.fill((255, 255, 220, 26))
                    screen.blit(ov, (tx, ty))
                # 草地随机长树（~6%，带脚部阴影）
                if w.terrain[x][y] == T_GRASS and (x * 31 + y * 17) % 17 == 0 \
                        and (x, y) not in w.objects and (x, y) not in w.roads:
                    tree = assets.get("terrain_tree", 38)
                    if tree:
                        sh = pygame.Surface((30, 12), pygame.SRCALPHA)
                        sh.fill((20, 30, 15, 110))
                        sh = pygame.transform.smoothscale(sh, (34, 14))
                        screen.blit(sh, (tx + 6, ty + 30))
                        screen.blit(tree, (tx + 3, ty + 1))
        f_small = fonts[20]
        for pos, obj in w.objects.items():
            r = pygame.Rect(MAP_OX + pos[0] * TILE, MAP_OY + pos[1] * TILE, TILE - 1, TILE - 1)
            cx, cy = r.center
            t = obj["type"]
            if t == OBJ_RESOURCE:
                spr = assets.get(obj["res"], 26)
                if spr:
                    screen.blit(spr, spr.get_rect(center=(cx, cy)))
                else:
                    pygame.draw.circle(screen, OBJ_COLOR[obj["res"]], (cx, cy), 12)
            elif t == OBJ_MINE:
                pygame.draw.rect(screen, (60, 60, 70), r.inflate(-10, -14))
                pygame.draw.polygon(screen, OBJ_COLOR[MINE_RES[obj["mine"]]],
                                    [(r.x + 4, r.y + 16), (r.x + r.w // 2, r.y + 4), (r.x + r.w - 4, r.y + 16)])
                if pos in w.mines_owned:
                    pygame.draw.circle(screen, (80, 200, 80), (r.x + 8, r.y + 8), 5)
            elif t == OBJ_CHEST:
                pygame.draw.rect(screen, (160, 110, 40), r.inflate(-12, -14))
            elif t == OBJ_ARTIFACT:
                from entities import ARTIFACTS
                color = ARTIFACTS.get(obj.get("art", ""), {}).get("color", (240, 210, 70))
                pygame.draw.polygon(screen, color,
                                    [(cx, cy - 13), (cx + 12, cy + 9), (cx - 12, cy + 9)])
            elif t == OBJ_SHRINE:
                pygame.draw.circle(screen, (40, 30, 55), (cx, cy), 14)
                pygame.draw.circle(screen, (150, 90, 220), (cx, cy), 14, 2)
                pygame.draw.circle(screen, (190, 130, 250), (cx, cy - 4), 4)
            elif t == OBJ_MONSTER:
                ut = UNITS[obj["unit"]]
                spr = assets.get(obj["unit"], 36)
                if spr:
                    screen.blit(spr, spr.get_rect(center=(cx, cy)))
                    pygame.draw.circle(screen, (240, 90, 90), (cx, cy), 18, 2)
                else:
                    pygame.draw.circle(screen, ut.color, (cx, cy), 15)
                    pygame.draw.circle(screen, (240, 90, 90), (cx, cy), 15, 2)
                lab = f_small.render(str(obj["count"]), True, (255, 255, 255), (60, 0, 0))
                screen.blit(lab, lab.get_rect(midbottom=(cx, cy + 16)))
            elif t == OBJ_TOWN:
                owner = obj["ref"].owner
                pygame.draw.rect(screen, (170, 150, 130) if owner == "player" else (120, 90, 110),
                                 r.inflate(-8, -18))
                pygame.draw.polygon(screen, (150, 40, 40) if owner == "player" else (90, 30, 90),
                                    [(r.x + 2, r.y + 20), (cx, r.y + 2), (r.x + r.w - 2, r.y + 20)])
                if owner == "enemy":
                    lab = f_small.render("守", True, (255, 120, 120))
                    screen.blit(lab, lab.get_rect(center=(cx, cy)))
        if self.path:
            for p in self.path:
                cx = MAP_OX + p[0] * TILE + TILE // 2
                cy = MAP_OY + p[1] * TILE + TILE // 2
                pygame.draw.circle(screen, (255, 255, 120), (cx, cy), 4)
        # 敌方英雄
        eh = w.enemy_hero
        if eh:
            ex = MAP_OX + eh.pos[0] * TILE + TILE // 2
            ey = MAP_OY + eh.pos[1] * TILE + TILE // 2
            spr = assets.get("necromancer", 36)
            if spr:
                screen.blit(spr, spr.get_rect(center=(ex, ey)))
                pygame.draw.circle(screen, (220, 50, 50), (ex, ey), 19, 2)
            else:
                pygame.draw.circle(screen, (250, 200, 200), (ex, ey), 14)
                pygame.draw.polygon(screen, (200, 40, 40), [(ex - 8, ey + 2), (ex + 8, ey + 2), (ex, ey - 12)])
            lab = f_small.render("敌", True, (255, 255, 255), (120, 0, 0))
            screen.blit(lab, lab.get_rect(center=(ex, ey + 3)))
        # 玩家英雄们（当前激活的高亮）
        for h in g.heroes:
            hx = MAP_OX + h.pos[0] * TILE + TILE // 2
            hy = MAP_OY + h.pos[1] * TILE + TILE // 2
            spr = assets.get("hero" if g.heroes.index(h) == 0 else "hero2", 36)
            if spr:
                screen.blit(spr, spr.get_rect(center=(hx, hy)))
            else:
                pygame.draw.circle(screen, (250, 250, 250), (hx, hy), 14)
                pygame.draw.polygon(screen, (60, 90, 220), [(hx - 8, hy + 2), (hx + 8, hy + 2), (hx, hy - 12)])
            if h is g.hero:
                pygame.draw.circle(screen, (255, 255, 120), (hx, hy), 19, 2)
            lab = f_small.render(h.name[0], True, (255, 255, 255), (30, 60, 160))
            screen.blit(lab, lab.get_rect(center=(hx, hy + 3)))
        # 侧栏
        sx = SIDE_X
        f, fb = fonts[22], fonts[24]
        pygame.draw.rect(screen, (22, 24, 32), (sx, MAP_OY, W - sx - 10, MAP_H * TILE))
        y = MAP_OY + 14
        screen.blit(fb.render("第 %d 天（周%d 第%d天）" % (w.day, (w.day - 1) // 7 + 1, (w.day - 1) % 7 + 1),
                              True, (240, 240, 240)), (sx + 14, y))
        y += 40
        res = w.player_res
        for r in RES_LIST:
            pygame.draw.circle(screen, OBJ_COLOR[r], (sx + 24, y + 12), 9)
            screen.blit(f.render("%s: %d" % (RES_CN[r], res[r]), True, (220, 220, 220)), (sx + 44, y))
            y += 30
        y += 14
        for i, hh in enumerate(g.heroes):
            mark = "▶" if i == g.active_idx else " "
            screen.blit(f.render("%s[%d] %s" % (mark, i + 1, hh.name), True,
                                 (255, 230, 130) if i == g.active_idx else (190, 190, 190)),
                        (sx + 14, y))
            y += 26
        y += 8
        h = g.hero
        screen.blit(fb.render("英雄: " + h.name, True, (255, 220, 120)), (sx + 14, y))
        y += 34
        for line in ["等级 %d（经验 %d）" % (h.level, h.xp),
                     "攻击 +%d  防御 +%d" % (h.atk_total(), h.dfn_total()),
                     "移动力 %d/%d" % (h.mp, HERO_DAILY_MP),
                     "法力 %d/%d  魔力 %d" % (h.mana, h.mana_max, h.power_total()),
                     "士气 %+d  运气 %+d" % (h.morale(), h.luck())]:
            screen.blit(f.render(line, True, (200, 200, 200)), (sx + 14, y))
            y += 28
        if h.artifacts:
            screen.blit(f.render("宝物:", True, (250, 210, 100)), (sx + 14, y))
            y += 26
            from entities import ARTIFACTS
            for a in h.artifacts:
                screen.blit(f.render("· " + ARTIFACTS[a]["name"], True, (230, 200, 130)), (sx + 20, y))
                y += 24
        if eh:
            n = sum(eh.army.values())
            for line in ["—— 敌将: 莫甘娜 ——", "兵力约 %d 个" % n]:
                screen.blit(f.render(line, True, (240, 140, 140)), (sx + 14, y))
                y += 28
        et = next((t for t in w.towns if t.name == "暗影堡"), None)
        for line in ["剩余野怪: %d" % w.monsters_alive(),
                     "敌将: %s" % ("已击败" if eh is None else "存活"),
                     "暗影堡: %s" % ("已攻占" if et and et.owner == "player" else "敌占")]:
            screen.blit(f.render(line, True, (200, 200, 200)), (sx + 14, y))
            y += 28
        y += 10
        screen.blit(f.render("部队:", True, (180, 220, 180)), (sx + 14, y))
        y += 28
        for ut, n in h.army.items():
            if n > 0:
                pygame.draw.rect(screen, ut.color, (sx + 18, y + 2, 18, 18))
                screen.blit(f.render("%s x%d" % (ut.name, n), True, (220, 220, 220)), (sx + 46, y))
                y += 26
        my = MAP_OY + MAP_H * TILE + 8
        pygame.draw.rect(screen, (18, 20, 26), (MAP_OX, my, MAP_W * TILE, H - my - 6))
        fmsg = fonts[19]
        for i, m in enumerate(g.msg[-4:]):
            screen.blit(fmsg.render(m, True, (200, 200, 210)), (MAP_OX + 12, my + 6 + i * 22))
        screen.blit(fonts[22].render("点击移动 | 走上资源/矿自动拾取 | E=结束回合 T=进城 | 击败莫甘娜并攻占暗影堡获胜",
                                     True, (150, 160, 180)), (MAP_OX, 40))
        if g.victory():
            s = fonts[42].render("胜 利 ！", True, (255, 220, 80))
            screen.blit(s, s.get_rect(center=(W // 2, H // 2)))


# ---------------- 城镇场景 ----------------
class TownScene:
    def __init__(self, game):
        self.g = game
        self.town = next(t for t in game.world.towns if t.pos == game.hero.pos and t.owner == "player")
        self.buttons = []  # (rect, action, arg)

    def handle_event(self, ev):
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
            self.g.set_scene(AdventureScene(self.g))
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            for rect, act, arg in self.buttons:
                if rect.collidepoint(ev.pos):
                    self.do(act, arg)
                    return

    def do(self, act, arg):
        g, town = self.g, self.town
        if act == "build":
            b = arg
            cost = BUILDINGS[b]["cost"]
            res = g.world.player_res
            if b in town.buildings:
                g.notify("已建造")
                return
            if not all(res[r] >= c for r, c in cost.items()):
                g.notify("资源不足")
                return
            for r, c in cost.items():
                res[r] -= c
            town.buildings.add(b)
            if "unit" in BUILDINGS[b]:
                town.available[BUILDINGS[b]["unit"]] = town.available.get(BUILDINGS[b]["unit"], 0) + BUILDINGS[b]["growth"]
            sounds.play("build")
            g.notify("建造了 " + BUILDINGS[b]["name"])
        elif act in ("recruit", "recruit5"):
            ut = UNITS[arg]
            want = 1 if act == "recruit" else 5
            n = min(want, town.available.get(arg, 0),
                    g.world.player_res["gold"] // max(1, ut.gold_cost))
            if n <= 0:
                g.notify("无法招募（数量/金币不足）")
                return
            g.world.player_res["gold"] -= n * ut.gold_cost
            town.available[arg] -= n
            g.hero.add_units(ut, n)
            sounds.play("coin")
            g.notify("招募 %s x%d" % (ut.name, n))
        elif act == "hire":
            g.hire_hero(town.pos)
        elif act == "switch":
            g.active_idx = arg
            g.notify("切换英雄 → %s" % g.hero.name)
        elif act in ("buy", "sell"):
            from entities import MARKET_BUY, MARKET_SELL
            res = arg  # ("wood", n)
            r, n = res
            wres = g.world.player_res
            if act == "sell":
                price = MARKET_SELL[r]
                n = min(n, wres[r])
                if n <= 0:
                    g.notify("没有可卖出的 %s" % RES_CN[r])
                    return
                wres[r] -= n
                wres["gold"] += n * price
                g.notify("卖出 %s x%d，+金币 %d" % (RES_CN[r], n, n * price))
            else:
                price = MARKET_BUY[r]
                n = min(n, wres["gold"] // price)
                if n <= 0:
                    g.notify("金币不足")
                    return
                wres["gold"] -= n * price
                wres[r] += n
                g.notify("买入 %s x%d，-金币 %d" % (RES_CN[r], n, n * price))
        elif act in ("give1", "give5"):
            # 把当前英雄的兵转给城内另一英雄
            other = g.heroes[arg]
            n = 1 if act == "give1" else 5
            moved = 0
            for ut in list(g.hero.army.keys()):
                take = min(n, g.hero.army.get(ut, 0))
                if take > 0 and len(other.army) + (0 if ut in other.army else 1) <= 6:
                    g.hero.army[ut] -= take
                    if g.hero.army[ut] <= 0:
                        del g.hero.army[ut]
                    other.add_units(ut, take)
                    moved += take
            if moved:
                g.notify("转移 %d 个单位给 %s" % (moved, other.name))
            else:
                g.notify("无可转移单位或对方兵栏已满")

    def update(self, dt):
        pass

    def draw(self, screen, fonts):
        g, town = self.g, self.town
        screen.fill((34, 30, 26))
        f, fb, fbig = fonts[22], fonts[24], fonts[40]
        screen.blit(fbig.render("城 镇：%s" % town.name, True, (255, 220, 120)), (40, 30))
        screen.blit(f.render("ESC 返回地图", True, (180, 180, 180)), (40, 80))
        self.buttons = []
        y = 130
        screen.blit(fb.render("── 建造 ──", True, (240, 240, 240)), (40, y))
        y += 40
        for b, info in BUILDINGS.items():
            built = b in town.buildings
            cost_s = "  ".join("%s%d" % (RES_CN[r], c) for r, c in info["cost"].items())
            state = "已建造" if built else info["desc"] + "  [" + cost_s + "]"
            rect = pygame.Rect(40, y, 640, 40)
            pygame.draw.rect(screen, (60, 56, 50) if not built else (45, 60, 45), rect, border_radius=6)
            screen.blit(f.render("%s  %s" % (info["name"], state), True, (230, 230, 230)), (rect.x + 12, y + 8))
            if not built:
                btn = pygame.Rect(560, y + 6, 70, 28)
                pygame.draw.rect(screen, (90, 120, 200), btn, border_radius=5)
                screen.blit(fonts[19].render("建造", True, (255, 255, 255)), (btn.x + 14, y + 9))
                self.buttons.append((btn, "build", b))
            y += 50
        y += 20
        screen.blit(fb.render("── 招募 ──", True, (240, 240, 240)), (40, y))
        y += 40
        for uk, avail in town.available.items():
            if avail <= 0:
                continue
            ut = UNITS[uk]
            pygame.draw.rect(screen, ut.color, (44, y + 6, 26, 26), border_radius=4)
            screen.blit(f.render("%s  可招募 %d  单价 %d金  (攻%d 防%d 血%d 伤害%d-%d 速度%d%s)" %
                                 (ut.name, avail, ut.gold_cost, ut.atk, ut.dfn, ut.hp, ut.dmin, ut.dmax,
                                  ut.speed, " 远程" if ut.ranged else ""), True, (225, 225, 225)), (84, y + 8))
            b1 = pygame.Rect(660, y + 4, 60, 30)
            b2 = pygame.Rect(730, y + 4, 80, 30)
            pygame.draw.rect(screen, (90, 150, 90), b1, border_radius=5)
            pygame.draw.rect(screen, (90, 150, 90), b2, border_radius=5)
            screen.blit(fonts[19].render("+1", True, (255, 255, 255)), (b1.x + 18, y + 9))
            screen.blit(fonts[19].render("+5", True, (255, 255, 255)), (b2.x + 24, y + 9))
            self.buttons.append((b1, "recruit", uk))
            self.buttons.append((b2, "recruit5", uk))
            y += 42
        # 市场交易
        if "market" in town.buildings:
            from entities import MARKET_BUY, MARKET_SELL
            y += 14
            screen.blit(fb.render("── 市场 ──", True, (240, 220, 150)), (40, y))
            y += 38
            for r in ("wood", "ore", "crystal"):
                pygame.draw.circle(screen, OBJ_COLOR[r], (54, y + 14), 10)
                screen.blit(f.render("%s  持有 %d   卖%d金  买%d金" %
                                     (RES_CN[r], g.world.player_res[r], MARKET_SELL[r], MARKET_BUY[r]),
                                     True, (225, 225, 225)), (78, y + 6))
                bx = 470
                for lab, act, n in (("卖1", "sell", 1), ("卖5", "sell", 5), ("买1", "buy", 1), ("买5", "buy", 5)):
                    btn = pygame.Rect(bx, y + 2, 56, 28)
                    pygame.draw.rect(screen, (100, 110, 140) if act == "buy" else (140, 110, 80),
                                     btn, border_radius=5)
                    screen.blit(fonts[18].render(lab, True, (255, 255, 255)), (bx + 12, y + 6))
                    self.buttons.append((btn, act, (r, n)))
                    bx += 62
                y += 34
        hx = 900
        # 雇佣英雄
        hire = pygame.Rect(hx, 80, 220, 34)
        can_hire = len(g.heroes) < Game.MAX_HEROES
        pygame.draw.rect(screen, (110, 110, 170) if can_hire else (70, 70, 80), hire, border_radius=6)
        screen.blit(fonts[19].render("雇佣英雄 %d金" % Game.HERO_HIRE_COST, True, (255, 255, 255)),
                    (hire.x + 30, 86))
        if can_hire:
            self.buttons.append((hire, "hire", None))
        # 城内英雄切换 + 部队转移
        here = g.heroes_at(town.pos)
        y0 = 130
        screen.blit(fb.render("城内英雄", True, (255, 220, 120)), (hx, y0 - 40))
        for j, hh in enumerate(here):
            rect = pygame.Rect(hx, y0, 260, 32)
            active = hh is g.hero
            pygame.draw.rect(screen, (80, 90, 60) if active else (55, 58, 50), rect, border_radius=5)
            screen.blit(fonts[20].render("%s  兵力%d" % (hh.name, hh.total_units()), True,
                                         (255, 235, 150) if active else (200, 200, 200)), (hx + 12, y0 + 5))
            if not active:
                self.buttons.append((rect, "switch", g.heroes.index(hh)))
            if len(here) > 1:
                g1 = pygame.Rect(hx + 270, y0, 60, 30)
                g5 = pygame.Rect(hx + 338, y0, 60, 30)
                idx_other = g.heroes.index(next(o for o in here if o is not g.hero))
                if active:
                    for btn, act in ((g1, "give1"), (g5, "give5")):
                        pygame.draw.rect(screen, (120, 110, 60), btn, border_radius=5)
                        self.buttons.append((btn, act, idx_other))
                else:
                    idx_self = g.heroes.index(hh)
                    for btn, act in ((g1, "give1"), (g5, "give5")):
                        pygame.draw.rect(screen, (120, 110, 60), btn, border_radius=5)
                        self.buttons.append((btn, act, idx_self))
                screen.blit(fonts[18].render("转1", True, (255, 255, 255)), (g1.x + 14, y0 + 5))
                screen.blit(fonts[18].render("转5", True, (255, 255, 255)), (g5.x + 14, y0 + 5))
            y0 += 40
        screen.blit(fb.render("当前英雄部队", True, (255, 220, 120)), (hx, y0 + 6))
        yy = y0 + 48
        for ut, n in g.hero.army.items():
            if n > 0:
                pygame.draw.rect(screen, ut.color, (hx + 4, yy + 4, 26, 26), border_radius=4)
                screen.blit(f.render("%s x%d" % (ut.name, n), True, (230, 230, 230)), (hx + 44, yy + 6))
                yy += 40


# ---------------- 战斗场景 ----------------
class CombatScene:
    OX, OY = 330, 150

    @staticmethod
    def hex_center(c, r):
        from combat import HEX_W_STEP, HEX_V_STEP
        x = CombatScene.OX + (c + 0.5 * (r & 1)) * HEX_W_STEP + HEX_W_STEP // 2
        y = CombatScene.OY + r * HEX_V_STEP + 34
        return int(x), int(y)

    @classmethod
    def hex_points(cls, c, r, shrink=1.0):
        import math
        cx, cy = cls.hex_center(c, r)
        s = 32 * shrink
        w2 = s * math.sqrt(3) / 2
        return [(cx, cy - s), (cx + w2, cy - s / 2), (cx + w2, cy + s / 2),
                (cx, cy + s), (cx - w2, cy + s / 2), (cx - w2, cy - s / 2)]

    def __init__(self, game, enemy_army, enemy_hero=None, on_win=None):
        self.g = game
        sounds.play("battle")
        self.battle = Battle(game.hero.army, enemy_army, hero=game.hero, enemy_hero=enemy_hero)
        self.enemy_hero = enemy_hero
        self.on_win = on_win
        self.mode = None  # None=普通 / spell key
        self.over_timer = 1.6
        self.done = False
        self.run_ai()

    def tile_at(self, mpos):
        """最近六边形中心且距离在阈值内"""
        best, bd = None, 34
        for r in range(BH):
            for c in range(BW):
                cx, cy = self.hex_center(c, r)
                d = ((cx - mpos[0]) ** 2 + (cy - mpos[1]) ** 2) ** 0.5
                if d < bd:
                    best, bd = (c, r), d
        return best

    def unit_at(self, pos):
        for u in self.battle.alive():
            if u.pos == pos:
                return u
        return None

    def handle_event(self, ev):
        b = self.battle
        if b.result:
            return
        cur = b.cur
        if cur is None or cur.side != 0:
            return
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_d:
                b.log.append("%s 原地防御" % cur.utype.name)
                self.advance()
            elif ev.key == pygame.K_w:
                b.queue.append(cur)
                b.log.append("%s 等待" % cur.utype.name)
                self.advance()
            elif ev.key in tuple(pygame.K_1 + i for i in range(9)):  # 数字键选法术
                idx = ev.key - pygame.K_1
                if idx < len(SPELL_KEYS):
                    key = SPELL_KEYS[idx]
                    _, cost, side, _ = SPELLS[key]
                    if self.g.hero.mana < cost:
                        b.log.append("法力不足（%s 需 %d）" % (SPELLS[key][0], cost))
                    else:
                        self.mode = None if self.mode == key else key
                        b.log.append("选择法术: %s（点击%s目标）" %
                                     (SPELLS[key][0], "敌方" if side == "enemy" else "我方"))
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            t = self.tile_at(ev.pos)
            if not t:
                return
            target = self.unit_at(t)
            if self.mode:
                if target:
                    ok, msg = b.cast(self.mode, target)
                    b.log.append(msg)
                    if ok:
                        self.mode = None
                        if not b.result:
                            self.advance()
                return
            if target and target.side == 1:
                if cur.utype.ranged:
                    b.do_attack(cur, target, ranged=True)
                elif b.adjacent(cur, target):
                    b.do_attack(cur, target)
                else:
                    b.log.append("距离太远，无法近战")
                    return
                if not b.result:
                    self.advance()
            elif t not in [u.pos for u in b.alive()]:
                reach = b.move_reachable(cur)
                if t in reach:
                    cur.pos = t
                    self.advance()
                else:
                    b.log.append("超出移动范围")

    def advance(self):
        b = self.battle
        if b.result:
            return
        if not b.next_unit():
            return
        self.run_ai()

    def run_ai(self):
        b = self.battle
        while b.cur and b.cur.side == 1 and not b.result:
            b.ai_act()
            if b.result:
                return
            if not b.next_unit():
                return

    def update(self, dt):
        if self.battle.result and not self.done:
            self.over_timer -= dt
            if self.over_timer <= 0:
                self.finish()

    def finish(self):
        self.done = True
        g = self.g
        if self.battle.result == "win":
            g.hero.gain_xp(self.battle.xp_gain())
            if self.on_win:
                self.on_win(self.battle)
            sounds.play("win")
            g.notify("战斗胜利！获得经验")
            g.set_scene(AdventureScene(g))
        else:
            sounds.play("lose")
            g.notify("战斗失败……游戏结束。")
            g.set_scene(GameOverScene(g))

    def draw(self, screen, fonts):
        b = self.battle
        screen.fill((20, 24, 20))
        f, fb, fbig = fonts[20], fonts[24], fonts[40]
        screen.blit(fbig.render("战 斗", True, (240, 90, 90)), (40, 24))
        screen.blit(f.render("第 %d 轮" % b.round, True, (220, 220, 220)), (220, 42))
        cur = b.cur
        if cur:
            screen.blit(f.render(("我方" if cur.side == 0 else "敌方") + "行动: " + cur.utype.name,
                                  True, (140, 220, 140) if cur.side == 0 else (240, 140, 140)), (340, 42))
        # 魔法栏（6 个法术）
        mx = 470
        for i, key in enumerate(SPELL_KEYS):
            name, cost, side, _ = SPELLS[key]
            rect = pygame.Rect(mx + i * 162, 30, 156, 34)
            color = (70, 100, 60) if self.mode != key else (120, 160, 70)
            pygame.draw.rect(screen, color, rect, border_radius=6)
            mark = "[%d]" % (i + 1)
            screen.blit(fonts[18].render("%s%s %dMP" % (mark, name, cost), True, (235, 235, 235)),
                        (rect.x + 8, 36))
        for y in range(BH):
            for x in range(BW):
                pygame.draw.polygon(screen, (46, 58, 44) if (x + y) % 2 == 0 else (40, 50, 38),
                                    self.hex_points(x, y))
        if cur and cur.side == 0 and not b.result:
            for p in b.move_reachable(cur):
                pygame.draw.polygon(screen, (100, 125, 85), self.hex_points(p[0], p[1], 0.82))
        for u in b.alive():
            cx, cy = self.hex_center(*u.pos)
            r = pygame.Rect(cx - 26, cy - 16, 52, 32)
            pygame.draw.rect(screen, u.utype.color, r, border_radius=10)
            pygame.draw.rect(screen, (250, 250, 250) if u.side == 0 else (250, 80, 80), r, 3, border_radius=10)
            spr = assets.get(u.utype.key, 44)
            if spr:
                screen.blit(spr, spr.get_rect(center=(cx, cy)))
            speed_s = "%d%s" % (u.eff_speed, "*" if u.speed_mod else "")
            lab = fonts[18].render("%d|%s" % (u.count, speed_s), True, (255, 255, 255))
            screen.blit(lab, lab.get_rect(midbottom=(cx, cy + 32)))
            name = fonts[16].render(u.utype.name, True, (255, 255, 255))
            screen.blit(name, name.get_rect(midbottom=(cx, cy - 20)))
            if cur is u and not b.result:
                pygame.draw.circle(screen, (255, 255, 0), (cx, cy - 38), 5)
        ly = self.OY + BH * 46 + 70
        for i, line in enumerate(b.log[-5:]):
            screen.blit(fonts[19].render(line, True, (200, 210, 200)), (self.OX, ly + i * 24))
        if b.result:
            s = fbig.render("胜利！" if b.result == "win" else "战败", True, (255, 220, 80))
            screen.blit(s, s.get_rect(center=(1480 // 2, 860 // 2)))


class GameOverScene:
    def __init__(self, game):
        self.g = game

    def handle_event(self, ev):
        pass

    def update(self, dt):
        pass

    def draw(self, screen, fonts):
        screen.fill((10, 10, 12))
        s = fonts[48].render("游戏结束 —— 英雄全军覆没", True, (240, 80, 80))
        screen.blit(s, s.get_rect(center=(W // 2, H // 2)))


def main():
    pygame.init()
    sounds.init()
    screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption("英雄无敌3 复刻版")
    clock = pygame.time.Clock()
    game = Game()
    fonts = {s: get_font(s, bold=(s >= 40)) for s in (16, 18, 19, 20, 22, 24, 40, 42, 48)}
    while game.running:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                game.running = False
            else:
                result = game.scene.handle_event(ev)
                if result is not None:  # 读档返回新 Game
                    game = result
        dt = clock.tick(60) / 1000.0
        game.scene.update(dt)
        game.scene.draw(screen, fonts)
        pygame.display.flip()
    pygame.quit()


if __name__ == "__main__":
    main()
