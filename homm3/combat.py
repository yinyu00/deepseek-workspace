"""回合制战棋战斗（六边形战场，odd-r 偏移坐标，尖顶六边形）"""
import random
from dataclasses import dataclass, field
from constants import *
from entities import UnitType, UNITS
import sounds
sounds.init()

BW, BH = 13, 9     # 列 x 行（六边形）
BTILE = 34         # 六边形外接圆半径（绘制用）
HEX_W_STEP = 60    # 水平步距（列间距）
HEX_V_STEP = 46    # 垂直步距（行间距）


def hex_neighbors(c, r):
    """odd-r 偏移：奇数行向右偏移半格"""
    if r % 2 == 0:
        return [(c - 1, r), (c + 1, r), (c - 1, r - 1), (c, r - 1), (c - 1, r + 1), (c, r + 1)]
    return [(c - 1, r), (c + 1, r), (c, r - 1), (c + 1, r - 1), (c, r + 1), (c + 1, r + 1)]


def _to_cube(c, r):
    x = c - (r - (r & 1)) // 2
    z = r
    y = -x - z
    return x, y, z


def hex_dist(a, b):
    ax, ay, az = _to_cube(*a)
    bx, by, bz = _to_cube(*b)
    return max(abs(ax - bx), abs(ay - by), abs(az - bz))


def in_field(pos):
    return 0 <= pos[0] < BW and 0 <= pos[1] < BH


# 魔法书: key -> (名称, 耗蓝, 目标方, 说明)
SPELLS = {
    "arrow": ("魔法箭", 5, "enemy", "单体伤害 10+12x魔力"),
    "lightning": ("闪电术", 8, "enemy", "强力伤害 25+25x魔力"),
    "slow": ("减速术", 4, "enemy", "目标速度 -2"),
    "haste": ("急行术", 4, "ally", "目标速度 +2"),
    "heal": ("治疗术", 6, "ally", "恢复我方 30+15x魔力 生命"),
    "fireball": ("火球术", 9, "enemy", "溅射：目标及相邻敌方"),
}
SPELL_KEYS = list(SPELLS.keys())


@dataclass
class BUnit:
    utype: UnitType
    count: int
    side: int  # 0=玩家 1=敌方
    pos: tuple
    retaliated: bool = False
    waited: bool = False
    speed_mod: int = 0
    uid: int = 0
    start_count: int = 0  # 用于治疗上限

    def __post_init__(self):
        if self.start_count == 0:
            self.start_count = self.count

    @property
    def eff_speed(self):
        return max(1, self.utype.speed + self.speed_mod)

    def heal(self, amount):
        """恢复生命（按血池折算数量，不超过初始数量），返回恢复个数"""
        total = self.count * self.utype.hp + amount
        new_count = min(self.start_count, total // self.utype.hp)
        gained = new_count - self.count
        self.count = new_count
        return gained

    def take_damage(self, dmg):
        """返回实际死亡数量（血池模型）"""
        alive = self.count
        per = self.utype.hp
        total = self.count * per - dmg
        if total <= 0:
            dead = self.count
            self.count = 0
        else:
            new_count = (total + per - 1) // per
            dead = alive - new_count
            self.count = new_count
        return dead


class Battle:
    def __init__(self, player_army, enemy_army, hero=None, enemy_hero=None, rng=None):
        self.rng = rng or random.Random()
        self.units = []
        uid = 1
        for i, (ut, n) in enumerate(player_army.items()):
            if n > 0:
                self.units.append(BUnit(ut, n, 0, (1 + i, 1 + (i % 5)), uid=uid))
                uid += 1
        for i, (ut, n) in enumerate(enemy_army.items()):
            if n > 0:
                self.units.append(BUnit(ut, n, 1, (BW - 2 - i, 1 + (i % 5)), uid=uid))
                uid += 1
        self.hero = hero            # 玩家英雄（施法者）
        self.enemy_hero = enemy_hero  # 敌方英雄（仅攻击加成）
        self.round = 0
        self.queue = []
        self.cur = None
        self.log = ["战斗开始！"]
        self.result = None  # None/"win"/"lose"
        self.spell_used_this_round = False
        self.new_round()

    # ---------- 流程 ----------
    def alive(self, side=None):
        if side is None:
            return [u for u in self.units if u.count > 0]
        return [u for u in self.units if u.count > 0 and u.side == side]

    def new_round(self):
        self.round += 1
        for u in self.units:
            u.retaliated = False
            u.waited = False
        self.queue = sorted(self.alive(), key=lambda u: (-u.eff_speed, u.side, u.uid))
        self.spell_used_this_round = False
        self.log.append("—— 第 %d 轮 ——" % self.round)
        self.next_unit()

    def next_unit(self):
        # 士气判定：刚行动完的单位有 5%*士气 概率立即再行动
        prev = self.cur
        if prev and prev.count > 0 and prev not in self.queue:
            mor = self.side_morale(prev.side)
            if mor > 0 and self.rng.random() < 0.05 * mor:
                self.queue.insert(0, prev)
                self.log.append("%s 士气高涨，再次行动！" % prev.utype.name)
        while self.queue:
            u = self.queue.pop(0)
            if u.count > 0:
                self.cur = u
                return True
        if not self.alive(1):
            self.result = "win"
            return False
        if not self.alive(0):
            self.result = "lose"
            return False
        self.new_round()
        return self.cur is not None

    def side_morale(self, side):
        if side == 0 and self.hero:
            return self.hero.morale()
        if side == 1 and self.enemy_hero:
            return getattr(self.enemy_hero, "_mor", 1)
        return 0

    def side_luck(self, side):
        if side == 0 and self.hero:
            return self.hero.luck()
        if side == 1 and self.enemy_hero:
            return getattr(self.enemy_hero, "_luck", 0)
        return 0

    # ---------- 移动 ----------
    def move_reachable(self, u):
        """BFS 可达格（速度上限，不能穿越任何单位）"""
        from collections import deque
        occupied = {x.pos for x in self.alive() if x is not u}
        dist = {u.pos: 0}
        dq = deque([u.pos])
        while dq:
            p = dq.popleft()
            if dist[p] >= u.eff_speed:
                continue
            for np in hex_neighbors(*p):
                if not in_field(np):
                    continue
                if np in occupied or np in dist:
                    continue
                dist[np] = dist[p] + 1
                dq.append(np)
        return dist

    def adjacent(self, a, b):
        return hex_dist(a.pos, b.pos) == 1

    # ---------- 伤害 ----------
    def calc_damage(self, att, dfn, u):
        base = u.count * self.rng.randint(u.utype.dmin, u.utype.dmax)
        diff = att - dfn
        if diff > 0:
            base *= min(1 + 0.05 * diff, 3.0)
        else:
            base *= max(1 + 0.025 * diff, 0.3)
        return max(1, int(base))

    def do_attack(self, att, dfn, ranged=False):
        if att.side == 0 and self.hero:
            a_atk = att.utype.atk + self.hero.atk_total()
        elif att.side == 1 and self.enemy_hero:
            a_atk = att.utype.atk + self.enemy_hero.atk_total()
        else:
            a_atk = att.utype.atk
        dmg = self.calc_damage(a_atk, dfn.utype.dfn, att)
        # 运气判定：5%*运气 概率双倍伤害
        luck = self.side_luck(att.side)
        if luck > 0 and self.rng.random() < 0.05 * luck:
            dmg *= 2
            self.log.append("🍀 %s 幸运一击！" % att.utype.name)
        dead = dfn.take_damage(dmg)
        sounds.play("arrow" if ranged else "hit")
        self.log.append("%s 攻击 %s，造成 %d 伤害，消灭 %d 个" %
                        (att.utype.name, dfn.utype.name, dmg, dead))
        if not ranged and dfn.count > 0 and not dfn.retaliated:
            dfn.retaliated = True
            dmg2 = self.calc_damage(dfn.utype.atk, att.utype.dfn, dfn)
            dead2 = att.take_damage(dmg2)
            self.log.append("%s 反击，造成 %d 伤害，消灭 %d 个" % (dfn.utype.name, dmg2, dead2))
        # 吸血（如吸血鬼）：按造成伤害恢复自身
        if att.utype.lifesteal and att.count > 0:
            gained = att.heal(dmg)
            if gained:
                self.log.append("🩸 %s 吸取生命，恢复 %d 个" % (att.utype.name, gained))
        self.check_end()

    # ---------- 魔法 ----------
    def cast(self, spell_key, target):
        """玩家英雄施法。返回 (成功, 消息)"""
        if self.result or self.spell_used_this_round:
            return False, "本轮已施法"
        name, cost, side, _ = SPELLS[spell_key]
        if not self.hero or self.hero.mana < cost:
            return False, "法力不足（需 %d）" % cost
        if target.count <= 0:
            return False, "目标无效"
        if side == "enemy" and target.side != 1:
            return False, "需要选择敌方目标"
        if side == "ally" and target.side != 0:
            return False, "需要选择我方目标"
        self.hero.mana -= cost
        self.spell_used_this_round = True
        sounds.play("heal" if spell_key == "heal" else "spell")
        if spell_key == "arrow":
            dmg = 10 + 12 * self.hero.power_total() + self.rng.randint(0, 8)
            dead = target.take_damage(dmg)
            self.log.append("【魔法箭】对 %s 造成 %d 伤害，消灭 %d" % (target.utype.name, dmg, dead))
            self.check_end()
        elif spell_key == "lightning":
            dmg = 25 + 25 * self.hero.power_total() + self.rng.randint(0, 15)
            dead = target.take_damage(dmg)
            self.log.append("【闪电术】对 %s 造成 %d 伤害，消灭 %d" % (target.utype.name, dmg, dead))
            self.check_end()
        elif spell_key == "slow":
            target.speed_mod -= 2
            self.log.append("【减速术】%s 速度 -2" % target.utype.name)
        elif spell_key == "haste":
            target.speed_mod += 2
            self.log.append("【急行术】%s 速度 +2" % target.utype.name)
        elif spell_key == "heal":
            amount = 30 + 15 * self.hero.power_total()
            gained = target.heal(amount)
            self.log.append("【治疗术】%s 恢复 %d 个单位" % (target.utype.name, gained))
        elif spell_key == "fireball":
            dmg = 20 + 10 * self.hero.power_total() + self.rng.randint(0, 10)
            dead = target.take_damage(dmg)
            self.log.append("【火球术】对 %s 造成 %d 伤害，消灭 %d" % (target.utype.name, dmg, dead))
            for nb in hex_neighbors(*target.pos):
                for v in self.alive(1):
                    if v.pos == nb and v is not target:
                        d2 = int(dmg * 0.6)
                        dd2 = v.take_damage(d2)
                        self.log.append("  溅射 %s：%d 伤害，消灭 %d" % (v.utype.name, d2, dd2))
            self.check_end()
        return True, "施放 " + name

    def check_end(self):
        if not self.alive(1):
            self.result = "win"
            self.log.append("胜利！")
        elif not self.alive(0):
            self.result = "lose"
            self.log.append("战败……")

    # ---------- 敌方 AI ----------
    def ai_act(self):
        u = self.cur
        if u is None or u.count <= 0:
            return
        enemies = self.alive(1 - u.side)
        if not enemies:
            return
        target = min(enemies, key=lambda e: (self._dist(u.pos, e.pos), e.count))
        if u.utype.ranged:
            self.do_attack(u, target, ranged=True)
            return
        reach = self.move_reachable(u)
        best = None
        for np in hex_neighbors(*target.pos):
            if in_field(np) and np in reach and (best is None or reach[np] < reach[best]):
                best = np
        if best:
            u.pos = best
            self.do_attack(u, target)
        else:
            step = min(reach.items(), key=lambda kv: hex_dist(kv[0], target.pos))[0]
            u.pos = step

    @staticmethod
    def _dist(a, b):
        return hex_dist(a, b)

    def xp_gain(self):
        return sum(u.count * u.utype.tier * 30 for u in self.units if u.side == 1)

    def survivors(self, side):
        return {u.utype: u.count for u in self.alive(side) if u.count > 0}


def auto_resolve(army_a, army_b, hero_a=None, hero_b=None, rng=None):
    """无头自动战斗（AI vs AI）。返回 (结果, A方幸存, B方幸存)"""
    b = Battle(dict(army_a), dict(army_b), hero=hero_a, enemy_hero=hero_b, rng=rng)
    steps = 0
    while b.result is None and steps < 5000:
        steps += 1
        if b.cur is None:
            break
        b.ai_act()
        if b.result is None:
            b.next_unit()
    result = b.result or ("win" if b.alive(0) else "lose")
    return result, b.survivors(0), b.survivors(1)
