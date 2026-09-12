"""存档/读档（JSON）"""
import json
from constants import *
from entities import Hero, Town, UNITS, ARTIFACTS
from world import World

SAVE_PATH = "save.json"


def _army_to_json(army):
    return {ut.key: n for ut, n in army.items() if n > 0}


def _army_from_json(d):
    return {UNITS[k]: n for k, n in d.items() if n > 0}


def _hero_to_json(h):
    return {
        "name": h.name, "pos": list(h.pos), "mp": h.mp, "level": h.level,
        "xp": h.xp, "atk_bonus": h.atk_bonus, "dfn_bonus": h.dfn_bonus,
        "mana": h.mana, "mana_max": h.mana_max, "spell_power": h.spell_power,
        "artifacts": list(h.artifacts), "army": _army_to_json(h.army),
    }


def _hero_from_json(d):
    h = Hero(d["name"], tuple(d["pos"]))
    h.mp, h.level, h.xp = d["mp"], d["level"], d["xp"]
    h.atk_bonus, h.dfn_bonus = d["atk_bonus"], d["dfn_bonus"]
    h.mana, h.mana_max, h.spell_power = d["mana"], d["mana_max"], d["spell_power"]
    h.artifacts = list(d["artifacts"])
    h.army = _army_from_json(d["army"])
    return h


def save(game, path=SAVE_PATH):
    w = game.world
    towns = []
    for t in w.towns:
        towns.append({
            "name": t.name, "pos": list(t.pos), "owner": t.owner,
            "buildings": sorted(t.buildings),
            "available": dict(t.available),
        })
    objects = {}
    for pos, obj in w.objects.items():
        o = dict(obj)
        if o["type"] == OBJ_TOWN:
            o = {"type": OBJ_TOWN, "ref": o["ref"].name}
            gar = obj.get("garrison")
            if gar:
                o["garrison"] = _army_to_json(gar)
        objects["%d,%d" % pos] = o
    data = {
        "version": 1,
        "day": w.day,
        "player_res": dict(w.player_res),
        "mines_owned": ["%d,%d" % p for p in w.mines_owned],
        "roads": ["%d,%d" % p for p in w.roads],
        "terrain": w.terrain,
        "objects": objects,
        "towns": towns,
        "enemy_hero": _hero_to_json(w.enemy_hero) if w.enemy_hero else None,
        "heroes": [_hero_to_json(h) for h in game.heroes],
        "active_idx": game.active_idx,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return path


def load(path=SAVE_PATH):
    import main as M
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    w = World.blank()
    w.day = data["day"]
    w.player_res = dict(data["player_res"])
    w.mines_owned = {tuple(int(x) for x in s.split(",")) for s in data["mines_owned"]}
    w.roads = {tuple(int(x) for x in s.split(",")) for s in data.get("roads", [])}
    w.terrain = data["terrain"]
    w.towns = []
    for td in data["towns"]:
        t = Town(td["name"], tuple(td["pos"]), owner=td["owner"])
        t.buildings = set(td["buildings"])
        t.available = {k: n for k, n in td["available"].items()}
        w.towns.append(t)
    w.objects = {}
    for k, o in data["objects"].items():
        pos = tuple(int(x) for x in k.split(","))
        obj = dict(o)
        if obj["type"] == OBJ_TOWN:
            name = obj["ref"]
            obj["ref"] = next(t for t in w.towns if t.name == name)
            if "garrison" in obj:
                obj["garrison"] = _army_from_json(obj["garrison"])
        w.objects[pos] = obj
    w.enemy_hero = _hero_from_json(data["enemy_hero"]) if data["enemy_hero"] else None
    game = M.Game.__new__(M.Game)
    game.world = w
    game.heroes = [_hero_from_json(hd) for hd in data["heroes"]]
    game.active_idx = min(data["active_idx"], len(game.heroes) - 1)
    game.scene = M.AdventureScene(game)
    game.running = True
    game.enemy_attacks = False
    game.msg = ["读档成功：第 %d 天" % w.day]
    w.hero = game.heroes[0]
    return game
