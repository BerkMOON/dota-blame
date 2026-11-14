#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dota 2 分锅器
=============
输入一个对局 ID，从 OpenDota 拉数据，输出一篇「分锅判决书」。

用法:
    python3 dota_blame.py 9088291413 --user 181585714
    python3 dota_blame.py 9088291413 --user 181585714 --refresh   # 解析完成后强制重拉
    python3 dota_blame.py <id> --out report.md

数据说明:
  - 已解析对局：分钟经济曲线、死亡时间点/送金、逐场团战、眼位、野怪击杀、装备时间线；
  - 未解析对局：自动降级为官方聚合数据 + 同英雄基准百分位，并自动提交解析请求。
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta

API = "https://api.opendota.com/api"
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
os.makedirs(CACHE, exist_ok=True)
CST = timezone(timedelta(hours=8))

GAME_MODE = {1: "全英雄选择(旧)", 2: "队长模式", 3: "随机征召", 4: "单中模式",
             5: "全随机", 12: "最少使用", 16: "队长征召", 18: "技能征召",
             22: "全英雄选择", 23: "快速模式"}
LOBBY_TYPE = {0: "普通", 1: "练习", 2: "锦标赛", 4: "合作对抗", 5: "队伍匹配",
              6: "匹配", 7: "天梯", 12: "人机"}

# 位置权重：不同号位，背锅维度不同
WEIGHTS = {
    1: {"feed": 0.30, "farm": 0.30, "dmg": 0.20, "assist": 0.10, "obj": 0.10},
    2: {"feed": 0.25, "farm": 0.25, "dmg": 0.25, "assist": 0.15, "obj": 0.10},
    3: {"feed": 0.30, "farm": 0.20, "dmg": 0.25, "assist": 0.15, "obj": 0.10},
    4: {"feed": 0.28, "dmg": 0.17, "assist": 0.30, "vision": 0.25},
    5: {"feed": 0.28, "dmg": 0.12, "assist": 0.35, "vision": 0.25},
}

DIM_CN = {"feed": "送", "farm": "经济", "dmg": "输出", "assist": "参团",
          "obj": "推塔", "vision": "视野"}

KEY_ITEM_CN = {
    "bfury": "狂战斧", "manta": "幻影斧", "skadi": "斯嘉蒂之眼",
    "black_king_bar": "黑皇杖", "blink": "闪烁匕首", "sheepstick": "邪恶镰刀",
    "orchid": "紫怨", "bloodthorn": "血棘", "desolator": "黯灭", "radiance": "辉耀",
    "basher": "碎颅锤", "abyssal_blade": "深渊之刃", "butterfly": "蝴蝶",
    "satanic": "撒旦之邪力", "heart": "龙心", "assault": "强袭胸甲",
    "shivas_guard": "希瓦的守护", "pipe": "长笛", "mekansm": "梅肯斯姆",
    "guardian_greaves": "卫士胫甲", "glimmer_cape": "微光披风",
    "force_staff": "原力法杖", "ghost": "幽魂权杖", "aeon_disk": "永恒之盘",
    "lotus_orb": "清莲宝珠", "sphere": "林肯法球", "dagon": "达贡之神力",
    "necronomicon": "死灵书", "refresher": "刷新球",
    "ultimate_scepter": "阿哈利姆神杖", "nullifier": "否决之球",
    "diffusal_blade": "散失之刃", "sange_and_yasha": "双刀",
    "mjollnir": "雷神之锤", "maelstrom": "漩涡", "invis_sword": "隐身刀",
    "hand_of_midas": "点金手", "travel_boots": "远行鞋", "power_treads": "动力鞋",
    "phase_boots": "相位鞋", "arcane_boots": "秘法鞋", "vanguard": "先锋盾",
    "crimson_guard": "赤红甲", "dragon_lance": "长枪", "greater_crit": "大炮",
    "lesser_crit": "水晶剑", "bloodstone": "血精石", "octarine_core": "玲珑心",
    "rod_of_atos": "阿托斯之棍", "moon_shard": "月之碎片",
    "hurricane_pike": "飓风长戟", "silver_edge": "白银之锋",
    "ethereal_blade": "虚灵之刃", "witch_blade": "女巫之刃",
}


# ----------------------------------------------------------------------------
# 网络与缓存
# ----------------------------------------------------------------------------
def _get(url, tries=4, timeout=40):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "dota-blame/0.2"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):  # 不存在就别重试了
                raise
            last = e
            time.sleep(1.5 * (i + 1))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def cached_json(url, filename, force=False):
    path = os.path.join(CACHE, filename)
    if os.path.exists(path) and not force:
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            pass
    data = _get(url)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return data


def load_hero_names():
    heroes = cached_json(API + "/heroes", "heroes.json")
    en = {h["id"]: h["localized_name"] for h in heroes}
    cn = {}
    try:
        d = cached_json("https://www.dota2.com/datafeed/herolist?language=schinese", "hero_cn.json")
        cn = {h["id"]: h["name_loc"] for h in d["result"]["data"]["heroes"]}
    except Exception:  # noqa: BLE001
        pass
    return en, cn


def fetch_match(match_id, refresh=False):
    return cached_json(API + "/matches/%s" % match_id, "match_%s.json" % match_id, force=refresh)


def request_parse(match_id):
    try:
        req = urllib.request.Request(API + "/request/%s" % match_id, method="POST",
                                     headers={"User-Agent": "dota-blame/0.2"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None


# ----------------------------------------------------------------------------
# 基础工具
# ----------------------------------------------------------------------------
def popcount(x):
    return bin(x).count("1") if x is not None else 0


def bpct(player, key):
    """同英雄基准百分位（0-100，越高越好）"""
    v = (player.get("benchmarks") or {}).get(key)
    if not v or "pct" not in v:
        return None
    return v["pct"] * 100.0


def is_parsed(match):
    return bool(match.get("players")) and all("gold_t" in p for p in match["players"])


def blend(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return 0.5 * a + 0.5 * b


def team_rel_blame(team, values, slot, higher_is_better=True):
    """队内相对：有多少队友比你做得更好 → 0-100，100 = 全队最差"""
    n = len(team)
    if n <= 1:
        return 50.0
    v = values[slot]
    better = 0
    for p in team:
        s = p["player_slot"]
        if s == slot:
            continue
        v2 = values[s]
        if (higher_is_better and v2 > v) or ((not higher_is_better) and v2 < v):
            better += 1
    return better / (n - 1) * 100.0


def pct_in_team(values, slot):
    """0-100：该玩家在这项指标上的队内排名（100 = 最高）"""
    n = len(values)
    if n <= 1:
        return 50.0
    v = values[slot]
    lower = sum(1 for s2, v2 in values.items() if s2 != slot and v2 < v)
    return lower / (n - 1) * 100.0


def assign_roles(players, parsed):
    """返回 {player_slot: pos}。已解析时用 lane_role 判断分路，未解析时按补刀/经济近似。"""
    if parsed:
        safe = [p for p in players if p.get("lane_role") == 1]
        mid = [p for p in players if p.get("lane_role") == 2]
        off = [p for p in players if p.get("lane_role") == 3]
        roles = {}

        def rank_by_lh(lst, positions):
            lst = sorted(lst, key=lambda p: (p.get("last_hits") or 0), reverse=True)
            for p, pos in zip(lst, positions):
                roles[p["player_slot"]] = pos

        if len(safe) == 2:
            rank_by_lh(safe, [1, 5])
        elif len(safe) == 1:
            roles[safe[0]["player_slot"]] = 1
        if mid:
            roles[mid[0]["player_slot"]] = 2
        if len(off) == 2:
            rank_by_lh(off, [3, 4])
        elif len(off) == 1:
            roles[off[0]["player_slot"]] = 3
        # 兜底：剩下的按经济补进空位
        free = [p for p in players if p["player_slot"] not in roles]
        used = set(roles.values())
        free_pos = [x for x in (1, 2, 3, 4, 5) if x not in used]
        free = sorted(free, key=lambda p: (p.get("net_worth") or 0), reverse=True)
        for p, pos in zip(free, free_pos):
            roles[p["player_slot"]] = pos
        return roles

    cores = sorted(players,
                   key=lambda p: ((p.get("last_hits") or 0), (p.get("gold_per_min") or 0)),
                   reverse=True)[:3]
    core_slots = {p["player_slot"] for p in cores}
    sups = [p for p in players if p["player_slot"] not in core_slots]
    sups = sorted(sups, key=lambda p: (p.get("net_worth") or 0), reverse=True)
    roles = {}
    for i, p in enumerate(cores):
        roles[p["player_slot"]] = i + 1
    for i, p in enumerate(sups):
        roles[p["player_slot"]] = 4 + i
    return roles


# ----------------------------------------------------------------------------
# 已解析对局的额外事实
# ----------------------------------------------------------------------------
def parsed_extra(p, team, match):
    da = match.get("duration") or 1
    dl = p.get("deaths_log") or []
    times = [x.get("time") or 0 for x in dl]
    fed = sum(x.get("gold_fed") or 0 for x in dl)

    slots = [q["player_slot"] for q in match["players"]]
    idx = {s: i for i, s in enumerate(slots)}
    i = idx.get(p["player_slot"])
    tfs = match.get("teamfights") or []
    tf_dmg = 0
    tf_died = 0
    zero_farm = 0
    attended = 0
    for f in tfs:
        pp = f["players"][i]
        d = pp.get("damage") or 0
        tf_dmg += d
        if (pp.get("deaths") or 0) > 0:
            tf_died += 1
        involved = any(f["start"] - 20 <= t <= f["end"] + 40 for t in times)
        if d == 0 and not involved and (pp.get("gold_delta") or 0) > 0:
            zero_farm += 1
        if d > 0 or (pp.get("healing") or 0) > 0 or pp.get("ability_uses"):
            attended += 1

    team_tf = sum(sum((f["players"][idx[q["player_slot"]]].get("damage") or 0)
                      for q in team) for f in tfs) or 1

    gold = p.get("gold_t") or []

    def gold_at(minute):
        if not gold:
            return None
        return gold[min(len(gold) - 1, minute)]

    items = []
    for e in p.get("purchase_log") or []:
        k = e.get("key")
        if k in KEY_ITEM_CN and (e.get("time") or -1) > 0:
            items.append((e["time"], KEY_ITEM_CN[k]))

    return {
        "early": sum(1 for t in times if t < 600),
        "mid": sum(1 for t in times if 600 <= t < 1500),
        "late": sum(1 for t in times if t >= 1500),
        "fed": fed,
        "neutral_kills": p.get("neutral_kills") or 0,
        "ancient_kills": p.get("ancient_kills") or 0,
        "camps_stacked": p.get("camps_stacked") or 0,
        "tf_dmg": tf_dmg,
        "tf_share": tf_dmg / team_tf * 100.0,
        "tf_died": tf_died,
        "zero_farm": zero_farm,
        "attended": attended,
        "tfp": (p.get("teamfight_participation") or 0) * 100.0,
        "gold10": gold_at(10), "gold20": gold_at(20),
        "gold30": gold_at(30), "gold40": gold_at(40),
        "items": items[:5],
        "buyback": p.get("buyback_count") or 0,
        "lane_eff": p.get("lane_efficiency_pct"),
    }


# ----------------------------------------------------------------------------
# 分锅维度
# ----------------------------------------------------------------------------
def _vision_parsed(p):
    obs = p.get("obs_placed")
    sen = p.get("sen_placed")
    if obs is None and sen is None:
        return None
    wards = (obs or 0) + (sen or 0)
    return max(0.0, min(100.0, (18.0 - wards) / 18.0 * 100.0))


def blame_components(p, pos, team, match, parsed, extra=None):
    slot = p["player_slot"]
    dur = (match.get("duration") or 1)
    comp = {}

    # 送：同英雄阵亡率百分位 + 队内死亡相对 +（已解析）前期死亡相对
    dp = bpct(p, "deaths_per_min")
    deaths_vals = {q["player_slot"]: q["deaths"] for q in team}
    feed = blend(None if dp is None else 100.0 - dp,
                 team_rel_blame(team, deaths_vals, slot, higher_is_better=False))
    if parsed and extra:
        early_vals = {q["player_slot"]: parsed_extra(q, team, match)["early"] for q in team}
        feed = 0.8 * feed + 0.2 * team_rel_blame(team, early_vals, slot, higher_is_better=False)
    comp["feed"] = feed

    # 经济：GPM 同英雄百分位（仅核心）
    if pos <= 3:
        gp = bpct(p, "gold_per_min")
        comp["farm"] = None if gp is None else 100.0 - gp

    # 输出：英雄伤害/min 百分位 + 队内伤害/min 相对
    hp = bpct(p, "hero_damage_per_min")
    dmg_vals = {q["player_slot"]: (q.get("hero_damage") or 0) / dur for q in team}
    comp["dmg"] = blend(None if hp is None else 100.0 - hp,
                        team_rel_blame(team, dmg_vals, slot, higher_is_better=True))

    # 参团：已解析优先用 teamfight_participation；否则助攻/min 百分位
    if parsed and extra:
        base = 100.0 - extra["tfp"]
        rel = team_rel_blame(team, {q["player_slot"]: (parsed_extra(q, team, match)["tfp"])
                                    for q in team}, slot, higher_is_better=True)
        comp["assist"] = blend(base, rel)
    else:
        ap = bpct(p, "assists_per_min")
        team_kills = sum(q["kills"] for q in team) or 1
        part_vals = {q["player_slot"]: (q["kills"] + q["assists"]) / team_kills for q in team}
        comp["assist"] = blend(None if ap is None else 100.0 - ap,
                               team_rel_blame(team, part_vals, slot, higher_is_better=True))

    # 推塔（仅核心）
    if pos <= 3:
        tp = bpct(p, "tower_damage")
        td_vals = {q["player_slot"]: (q.get("tower_damage") or 0) for q in team}
        comp["obj"] = blend(None if tp is None else 100.0 - tp,
                            team_rel_blame(team, td_vals, slot, higher_is_better=True))

    # 视野（仅辅助，需解析）
    if pos >= 4:
        comp["vision"] = _vision_parsed(p) if parsed else None

    return comp


def blame_score(pos, comp):
    w = WEIGHTS[pos]
    total, wsum = 0.0, 0.0
    for k, ww in w.items():
        v = comp.get(k)
        if v is not None:
            total += v * ww
            wsum += ww
    return total / wsum if wsum else 50.0


# ----------------------------------------------------------------------------
# 分析
# ----------------------------------------------------------------------------
def crash_info(match, analyze_team):
    """经济差曲线（我方视角）。返回前期/崩盘里程碑。"""
    adv = match.get("radiant_gold_adv") or []
    if not adv:
        return None
    sign = 1 if analyze_team == "radiant" else -1
    my = [sign * v for v in adv]

    def first_below(th):
        for i, v in enumerate(my):
            if v <= -th:
                return i
        return None

    return {
        "max_lead": max(my),
        "max_lead_min": my.index(max(my)),
        "last_lead": max((i for i, v in enumerate(my) if v >= 0), default=None),
        "t3": first_below(3000), "t5": first_below(5000),
        "t10": first_below(10000), "t15": first_below(15000),
    }


def early_kills(team):
    return sum(1 for p in team for e in (p.get("kills_log") or []) if e.get("time") < 600)


def analyze(match, user_account_id=None):
    players = match["players"]
    parsed = is_parsed(match)
    rwin = bool(match.get("radiant_win"))

    teams = {
        "radiant": [p for p in players if p["player_slot"] < 128],
        "dire": [p for p in players if p["player_slot"] >= 128],
    }
    team_stats = {}
    for name, ps in teams.items():
        team_stats[name] = {
            "kills": sum(p["kills"] for p in ps),
            "deaths": sum(p["deaths"] for p in ps),
            "assists": sum(p["assists"] for p in ps),
            "net_worth": sum(p.get("net_worth") or 0 for p in ps),
            "hero_damage": sum(p.get("hero_damage") or 0 for p in ps),
        }

    my_slot = None
    if user_account_id:
        my_slot = next((p["player_slot"] for p in players
                        if p.get("account_id") == user_account_id), None)

    losing = "dire" if rwin else "radiant"
    if my_slot is not None:
        my_team = "dire" if my_slot >= 128 else "radiant"
        analyze_team = my_team
    else:
        my_team = losing
        analyze_team = losing

    target = teams[analyze_team]
    roles = assign_roles(target, parsed)

    opp_team = "radiant" if analyze_team == "dire" else "dire"
    our_tower_status = match.get("tower_status_" + analyze_team)
    our_rax_status = match.get("barracks_status_" + analyze_team)
    opp_tower_status = match.get("tower_status_" + opp_team)
    opp_rax_status = match.get("barracks_status_" + opp_team)
    our_towers_lost = 11 - popcount(our_tower_status) if our_tower_status is not None else None
    our_rax_lost = 6 - popcount(our_rax_status) if our_rax_status is not None else None
    opp_towers_lost = 11 - popcount(opp_tower_status) if opp_tower_status is not None else None
    opp_rax_lost = 6 - popcount(opp_rax_status) if opp_rax_status is not None else None

    rows = []
    for p in target:
        pos = roles[p["player_slot"]]
        extra = parsed_extra(p, target, match) if parsed else None
        comp = blame_components(p, pos, target, match, parsed, extra)
        rows.append({"p": p, "pos": pos, "comp": comp,
                     "score": blame_score(pos, comp), "extra": extra})
    total_score = sum(r["score"] for r in rows) or 1.0
    for r in rows:
        r["share"] = r["score"] / total_score * 100.0
    rows.sort(key=lambda r: r["score"], reverse=True)
    for i, r in enumerate(rows):
        r["rank"] = i + 1

    # 野区嫌疑人指数：野怪击杀队内排名 + 参团率低
    suspects = []
    for r in rows:
        p = r["p"]
        s = p["player_slot"]
        lh = p.get("last_hits") or 0
        part = (p["kills"] + p["assists"]) / (team_stats[analyze_team]["kills"] or 1) * 100.0
        if parsed and r["extra"]:
            nk = r["extra"]["neutral_kills"]
            nk_rank = pct_in_team({q["player_slot"]: (q.get("neutral_kills") or 0) for q in target}, s)
            greed = 0.6 * nk_rank + 0.4 * (100.0 - r["extra"]["tfp"])
        else:
            nk = 0
            nk_rank = 0
            greed = pct_in_team({q["player_slot"]: (q.get("last_hits") or 0) for q in target}, s) + \
                (100.0 - part)
        suspects.append({"p": p, "greed": greed, "lh": lh, "part": part,
                         "neutral_kills": nk, "nk_rank": nk_rank})
    suspects.sort(key=lambda x: x["greed"], reverse=True)

    crash = crash_info(match, analyze_team) if parsed else None
    early_my = early_kills(target)
    early_opp = early_kills(teams[opp_team])

    return {
        "match": match, "parsed": parsed, "duration": match.get("duration") or 0,
        "crash": crash, "early_my": early_my, "early_opp": early_opp,
        "teams": teams, "team_stats": team_stats, "my_slot": my_slot,
        "my_team": my_team, "analyze_team": analyze_team, "losing": losing,
        "roles": roles, "rows": rows, "suspects": suspects,
        "our_towers_lost": our_towers_lost, "our_rax_lost": our_rax_lost,
        "opp_towers_lost": opp_towers_lost, "opp_rax_lost": opp_rax_lost,
    }


# ----------------------------------------------------------------------------
# 渲染
# ----------------------------------------------------------------------------
def fmt_dur(sec):
    sec = int(sec or 0)
    return "%d:%02d" % (sec // 60, sec % 60)


def fmt_time(sec):
    sec = int(sec or 0)
    return "%d:%02d" % (sec // 60, sec % 60)


def fmt_date(ts):
    if not ts:
        return "未知"
    return datetime.fromtimestamp(ts, CST).strftime("%Y-%m-%d %H:%M")


def bar(v, width=8):
    n = int(round(max(0.0, min(100.0, v)) / 100.0 * width))
    return "█" * n + "░" * (width - n)


def hero_label(hero_id, en, cn):
    c = cn.get(hero_id)
    e = en.get(hero_id, str(hero_id))
    return "%s（%s）" % (c, e) if c else e


def pct_text(v):
    return "—" if v is None else "%.0f%%" % v


def dim_badge(v):
    if v is None:
        return "—"
    if v >= 75:
        return "🔴 %.0f" % v
    if v >= 50:
        return "🟠 %.0f" % v
    if v >= 25:
        return "🟡 %.0f" % v
    return "🟢 %.0f" % v


def crime_tags(r):
    comp = r["comp"]
    tags = []
    if comp.get("feed") is not None and comp["feed"] >= 60:
        tags.append("送")
    if comp.get("farm") is not None and comp["farm"] >= 60:
        tags.append("经济罪犯")
    if comp.get("dmg") is not None and comp["dmg"] >= 60:
        tags.append("团战隐身")
    if comp.get("assist") is not None and comp["assist"] >= 70:
        tags.append("不参团")
    if comp.get("obj") is not None and comp["obj"] >= 70:
        tags.append("不推塔")
    if comp.get("vision") is not None and comp["vision"] >= 70:
        tags.append("不买眼")
    if r.get("extra") and r["extra"].get("zero_farm"):
        tags.append("打架时在打钱")
    if not tags:
        tags.append("小锅")
    return tags


def rank_title(rank):
    return {1: "锅王", 2: "二锅", 3: "三锅", 4: "小锅", 5: "尽力局"}.get(rank, "锅")


def verdict_text(r, ts):
    p, pos = r["p"], r["pos"]
    k, d, a = p["kills"], p["deaths"], p["assists"]
    team_kills = ts["kills"] or 1
    team_deaths = ts["deaths"] or 1
    part = (k + a) / team_kills * 100.0
    dshare = d / team_deaths * 100.0
    nw = p.get("net_worth") or 0
    hd = p.get("hero_damage") or 0
    dmg_nw = hd / nw if nw else 0

    lines = []
    dp = bpct(p, "deaths_per_min")
    gp = bpct(p, "gold_per_min")
    hp = bpct(p, "hero_damage_per_min")
    tp = bpct(p, "tower_damage")

    if dp is not None and dp < 30:
        lines.append("阵亡率同英雄百分位只有 %.0f%%（%d 死，占全队 %.0f%%）" % (dp, d, dshare))
    if pos <= 3 and gp is not None and gp < 40:
        lines.append("经济同英雄百分位 %.0f%%（%d 正补 / %d GPM）" % (
            gp, p.get("last_hits") or 0, p.get("gold_per_min") or 0))
    if hp is not None and hp < 40:
        lines.append("英雄伤害/min 同英雄百分位 %.0f%%（共 %d 伤害）" % (hp, hd))
    if pos <= 3 and tp is not None and tp < 40:
        lines.append("建筑伤害同英雄百分位 %.0f%%（%d）" % (tp, p.get("tower_damage") or 0))
    if dmg_nw:
        lines.append("经济转化 %.2f 伤害/经济" % dmg_nw)
    if part <= 40:
        lines.append("参团率 %.0f%%（全队 K+A 参与）" % part)

    ex = r.get("extra")
    if ex:
        if ex["early"] >= 2:
            lines.append("前 10 分钟就死了 %d 次（全队 %d 次）" % (
                ex["early"], sum(x["extra"]["early"] for x in r["_team_rows"])))
        if ex["tf_died"] >= 4:
            lines.append("团战里阵亡 %d 次，打团基本是有去无回" % ex["tf_died"])
        if ex["zero_farm"]:
            lines.append("有 %d 场团战他 0 伤害、但经济在涨 —— 团在打，他在刷" % ex["zero_farm"])
        if ex["neutral_kills"] >= 60:
            lines.append("野怪击杀 %d 只（全队第 %d）" % (
                ex["neutral_kills"], extra_rank(r["_team_rows"], p["player_slot"], "neutral_kills")))
        if ex["items"]:
            lines.append("关键装：%s" % "、".join("%s %s" % (n, fmt_time(t)) for t, n in ex["items"]))
        if ex["fed"] >= 3000:
            lines.append("共给对面送了 %d 金币" % ex["fed"])
    return lines


def extra_rank(rows, slot, key):
    """某玩家在团队某 extra 指标中的排名（1 = 最高）"""
    vals = sorted(((r["p"]["player_slot"], r["extra"].get(key) or 0) for r in rows),
                  key=lambda x: x[1], reverse=True)
    for i, (s, _) in enumerate(vals):
        if s == slot:
            return i + 1
    return 0


def render(match, analysis, en, cn, user_account_id=None):
    rows = analysis["rows"]
    for r in rows:
        r["_team_rows"] = rows
    at = analysis["analyze_team"]
    ts = analysis["team_stats"][at]
    opp_team = "radiant" if at == "dire" else "dire"
    opp_ts = analysis["team_stats"][opp_team]
    rwin = bool(match.get("radiant_win"))
    team_cn = "天辉" if at == "radiant" else "夜魇"
    enemy_cn = "夜魇" if at == "radiant" else "天辉"
    lost = at != ("radiant" if rwin else "dire")
    if analysis["my_slot"] is None:
        result_text = "%s获胜，%s落败" % ("天辉" if rwin else "夜魇", team_cn)
    else:
        result_text = "你方（%s）%s" % (team_cn, "落败" if lost else "获胜")

    out = []
    out.append("# 🍳 分锅判决书 · 对局 %s" % match.get("match_id"))
    out.append("")
    out.append("| 项目 | 内容 |")
    out.append("|---|---|")
    out.append("| 开始时间 | %s |" % fmt_date(match.get("start_time")))
    out.append("| 时长 | %s |" % fmt_dur(analysis["duration"]))
    out.append("| 模式 | %s · %s |" % (
        LOBBY_TYPE.get(match.get("lobby_type"), "未知"),
        GAME_MODE.get(match.get("game_mode"), "未知")))
    out.append("| 比分 | 天辉 %s : %s 夜魇 |" % (match.get("radiant_score"), match.get("dire_score")))
    out.append("| 结果 | **%s** |" % result_text)
    if analysis["our_towers_lost"] is not None:
        out.append("| 建筑 | 我方 %d 塔 / %d 兵营被推；对面 %d 塔 / %d 兵营被推 |" % (
            analysis["our_towers_lost"], analysis["our_rax_lost"] or 0,
            analysis["opp_towers_lost"] or 0, analysis["opp_rax_lost"] or 0))
    out.append("| 数据状态 | %s |" % (
        "✅ 已解析（时间线 / 死亡日志 / 团战 / 眼位 / 装备）" if analysis["parsed"]
        else "⚠️ 未解析（仅聚合数据，已提交解析请求）"))
    out.append("")

    if not analysis["parsed"]:
        out.append("> **注意**：本局 OpenDota 尚未解析，以下结论基于官方聚合数据 + 同英雄基准百分位。"
                   "解析完成后加 `--refresh` 重跑即可升级为精确版。")
        out.append("")

    top = rows[0]
    out.append("## 🎯 一句话判决")
    out.append("")
    top_me = "（你）" if top["p"].get("account_id") == user_account_id else ""
    out.append("**锅王：「%s」%s（%d号位 · %s），背锅 %.1f%%。**" % (
        top["p"].get("personaname") or "无名氏", top_me, top["pos"],
        hero_label(top["p"]["hero_id"], en, cn), top["share"]))
    out.append("")
    out.append("**团队对比：**")
    out.append("")
    out.append("| 指标 | %s | %s |" % (team_cn, enemy_cn))
    out.append("|---|---|---|")
    out.append("| 人头 | %d | %d |" % (ts["kills"], opp_ts["kills"]))
    out.append("| 团队经济 | %d | %d |" % (ts["net_worth"], opp_ts["net_worth"]))
    out.append("| 英雄伤害 | %d | %d |" % (ts["hero_damage"], opp_ts["hero_damage"]))
    out.append("")
    if analysis["our_towers_lost"] is not None:
        out.append("> %s 人头 %d : %d 落后，塔 %d : %d、兵营 %d : %d 被推平。"
                   "这不是一个人的锅，但锅总得有人背。" % (
                       team_cn, ts["kills"], opp_ts["kills"],
                       analysis["our_towers_lost"], analysis["opp_towers_lost"] or 0,
                       analysis["our_rax_lost"] or 0, analysis["opp_rax_lost"] or 0))
        out.append("")

    # 崩盘时间线
    if analysis["parsed"] and analysis["crash"]:
        c = analysis["crash"]
        out.append("## 📉 崩盘时间线（我方视角）")
        out.append("")
        out.append("- 前 10 分钟人头：**%d : %d**（我方 : 对面）" % (
            analysis["early_my"], analysis["early_opp"]))
        lead_min = c["max_lead_min"]
        out.append("- 前期：第 %d 分钟前基本五五开，我方最多领先 %d 经济" % (
            lead_min, int(c["max_lead"])))
        marks = []
        for th, key in ((3000, "t3"), (5000, "t5"), (10000, "t10"), (15000, "t15")):
            if c[key] is not None:
                marks.append("第 %d 分钟落后破 %s" % (c[key], "%.0fk" % (th / 1000.0)))
        if marks:
            out.append("- 崩盘：%s" % "，".join(marks))
        out.append("- %s 结束，塔 %d : %d、兵营 %d : %d 被推平" % (
            fmt_dur(analysis["duration"]),
            analysis["our_towers_lost"] or 0, analysis["opp_towers_lost"] or 0,
            analysis["our_rax_lost"] or 0, analysis["opp_rax_lost"] or 0))
        out.append("")

    # 锅榜
    out.append("## 🏆 锅榜")
    out.append("")
    out.append("| 名次 | 玩家 | 英雄 | 号位 | 背锅占比 | 罪名 |")
    out.append("|---|---|---|---|---|---|")
    icons = {1: "🥇", 2: "🥈", 3: "🥉", 4: "4️⃣", 5: "5️⃣"}
    for r in rows:
        p = r["p"]
        me = "（你）" if p.get("account_id") == user_account_id else ""
        name = "「%s」%s" % (p.get("personaname") or "无名氏", me)
        out.append("| %s %d | %s | %s | %d号位 | `%s` %.1f%% | %s |" % (
            icons.get(r["rank"], ""), r["rank"], name,
            hero_label(p["hero_id"], en, cn), r["pos"],
            bar(r["share"], 8), r["share"], "、".join(crime_tags(r))))
    out.append("")

    # 逐人判决
    out.append("## ⚖️ 逐人判决（按锅从大到小）")
    out.append("")
    for r in rows:
        p, pos = r["p"], r["pos"]
        me = "（你）" if p.get("account_id") == user_account_id else ""
        out.append("### %s %s · 「%s」%s（%s号位 · %s）— %.1f%%" % (
            icons.get(r["rank"], ""), rank_title(r["rank"]),
            p.get("personaname") or "无名氏", me, pos,
            hero_label(p["hero_id"], en, cn), r["share"]))
        out.append("")
        out.append("**定罪名：** %s" % "、".join(crime_tags(r)))
        out.append("")
        out.append("| KDA | 正补 | GPM | 英雄伤害 | 建筑伤害 | 参团率 |")
        out.append("|---|---|---|---|---|---|")
        out.append("| %d/%d/%d | %d | %d | %d | %d | %.0f%% |" % (
            p["kills"], p["deaths"], p["assists"], p.get("last_hits") or 0,
            p.get("gold_per_min") or 0, p.get("hero_damage") or 0,
            p.get("tower_damage") or 0,
            (p["kills"] + p["assists"]) / (ts["kills"] or 1) * 100))
        out.append("")
        out.append("五维背锅分（0-100，越高越背锅）：")
        out.append("")
        out.append("| 送 | 经济 | 输出 | 参团 | 推塔 | 视野 |")
        out.append("|---|---|---|---|---|---|")
        out.append("| %s | %s | %s | %s | %s | %s |" % (
            dim_badge(r["comp"].get("feed")), dim_badge(r["comp"].get("farm")),
            dim_badge(r["comp"].get("dmg")), dim_badge(r["comp"].get("assist")),
            dim_badge(r["comp"].get("obj")), dim_badge(r["comp"].get("vision"))))
        out.append("")
        out.append("**判词：**")
        for line in verdict_text(r, ts):
            out.append("- %s" % line)
        out.append("")

    # 野区 / 参团
    out.append("## 🌲 谁在野区把线对？（野怪击杀 × 团战伤害 × 参团率）")
    out.append("")
    if analysis["parsed"]:
        out.append("| 玩家 | 野怪击杀 | 远古 | 团战伤害占比 | 有效0伤团 | 团战阵亡 | 参团率 |")
        out.append("|---|---|---|---|---|---|---|")
        for r in rows:
            ex = r["extra"]
            p = r["p"]
            me = "（你）" if p.get("account_id") == user_account_id else ""
            out.append("| 「%s」%s | %d | %d | %.1f%% | %d | %d | %.0f%% |" % (
                p.get("personaname") or "无名氏", me,
                ex["neutral_kills"], ex["ancient_kills"],
                ex["tf_share"], ex["zero_farm"], ex["tf_died"], ex["tfp"]))
        out.append("")
        s = analysis["suspects"][0]
        suspect_row = next(r for r in rows if r["p"]["player_slot"] == s["p"]["player_slot"])
        out.append("**嫌疑人：** 「%s」（%s，%s号位）—— 野怪击杀 %d 只（全队第 %d），"
                   "参团率仅 %.0f%%，%d 场团战 0 伤害且当时经济在涨。" % (
                       s["p"].get("personaname") or "无名氏",
                       hero_label(s["p"]["hero_id"], en, cn),
                       analysis["roles"][s["p"]["player_slot"]],
                       s["neutral_kills"],
                       extra_rank(rows, s["p"]["player_slot"], "neutral_kills"),
                       s["part"], suspect_row["extra"]["zero_farm"]))
        out.append("")
    else:
        out.append("**没有解析数据，无法直接定位野区**，用「补刀多 + 参团少」做近似推断：")
        out.append("")
        for s in analysis["suspects"][:3]:
            p = s["p"]
            me = "（你）" if p.get("account_id") == user_account_id else ""
            out.append("- **%s%s（%s）**：补刀 %d（队内第 %d），参团率 %.0f%%，差额 **%.0f**" % (
                p.get("personaname") or "无名氏", me,
                hero_label(p["hero_id"], en, cn), s["lh"],
                _rank_of_simple(analysis["teams"][at], p["player_slot"], "last_hits"),
                s["part"], s["greed"]))
        out.append("")
        out.append("> 差额越大 = 刷得越多、团得越少。解析完成后可升级为精确版。")
        out.append("")

    if analysis["parsed"]:
        # 死亡时间线
        out.append("## 🕐 死亡时间线（谁在什么时候送）")
        out.append("")
        out.append("| 玩家 | 前10分钟 | 10-25分钟 | 25分钟后 | 共送金 | 团战阵亡 |")
        out.append("|---|---|---|---|---|---|")
        for r in rows:
            ex = r["extra"]
            p = r["p"]
            me = "（你）" if p.get("account_id") == user_account_id else ""
            out.append("| 「%s」%s | %d | %d | %d | %d | %d |" % (
                p.get("personaname") or "无名氏", me,
                ex["early"], ex["mid"], ex["late"], ex["fed"], ex["tf_died"]))
        out.append("")
        out.append("> 「送金」= 死亡时送给对面的金币总额；「团战阵亡」= 在团战窗口内阵亡的次数。")
        out.append("")

        # 视野
        out.append("## 👁️ 视野与辅助职责")
        out.append("")
        out.append("| 玩家 | 假眼 | 真眼 | 买活 | 堆野 | 参团率 |")
        out.append("|---|---|---|---|---|---|")
        for r in rows:
            p = r["p"]
            ex = r["extra"]
            me = "（你）" if p.get("account_id") == user_account_id else ""
            out.append("| 「%s」%s | %s | %s | %d | %d | %.0f%% |" % (
                p.get("personaname") or "无名氏", me,
                p.get("obs_placed", "—"), p.get("sen_placed", "—"),
                ex["buyback"], ex["camps_stacked"], ex["tfp"]))
        out.append("")

        # 装备时间线
        out.append("## ⚔️ 关键装备时间线")
        out.append("")
        for r in rows:
            ex = r["extra"]
            if not ex["items"]:
                continue
            p = r["p"]
            me = "（你）" if p.get("account_id") == user_account_id else ""
            out.append("- **「%s」%s（%s）**：%s" % (
                p.get("personaname") or "无名氏", me,
                hero_label(p["hero_id"], en, cn),
                " / ".join("%s %s" % (n, fmt_time(t)) for t, n in ex["items"])))
        out.append("")

    # 对面为什么赢
    opp = analysis["teams"][opp_team]
    opp_rows = sorted(opp, key=lambda p: ((bpct(p, "hero_damage_per_min") or 0) +
                                          (bpct(p, "gold_per_min") or 0)), reverse=True)
    out.append("## 💀 对面为什么赢")
    out.append("")
    for p in opp_rows[:3]:
        extra_line = ""
        if analysis["parsed"]:
            dl = p.get("deaths_log") or []
            extra_line = "，全场只死 %d 次" % len(dl) if len(dl) <= 3 else ""
        out.append("- **%s（%s）**：%d/%d/%d，%d GPM，%d 英雄伤害，%d 正补%s" % (
            p.get("personaname") or "无名氏", hero_label(p["hero_id"], en, cn),
            p["kills"], p["deaths"], p["assists"], p.get("gold_per_min") or 0,
            p.get("hero_damage") or 0, p.get("last_hits") or 0, extra_line))
    out.append("")

    # 算法说明
    out.append("## 🧾 分锅算法（可复现）")
    out.append("")
    out.append("1. **号位识别**：已解析时按 `lane_role` 分路识别（安全路补刀最高=1号位、另一个=5号位；"
               "中路=2号位；劣势路补刀最高=3号位、另一个=4号位）；未解析时按补刀/经济近似。")
    out.append("2. **五维背锅分**（0-100，越高越背锅）：")
    out.append("   - 送 = 阵亡率同英雄百分位 + 队内死亡相对 + 20% 前期死亡相对")
    out.append("   - 经济 = GPM 同英雄百分位（仅 1/2/3 号位）")
    out.append("   - 输出 = 英雄伤害/min 百分位 + 队内伤害相对")
    out.append("   - 参团 = 团战参与率（K+A/团队击杀）取反 + 队内相对")
    out.append("   - 推塔 = 建筑伤害百分位 + 队内相对（仅核心）")
    out.append("   - 视野 = 真假眼数量（仅 4/5 号位，需解析数据）")
    out.append("3. **按号位加权**：大哥看经济/输出，辅助看参团/视野；加权后归一化成 5 人锅占比。")
    out.append("4. **数据来源**：OpenDota 同英雄基准百分位 + 对局解析数据（时间线/死亡日志/团战/眼位/购买日志）。")
    out.append("")
    out.append("> 分锅是玄学：数据只能抓「显性犯罪」，抓不到拉野、卡线、指挥、让刀这些隐性贡献。"
               "本报告用于五黑赛后复盘与友好互喷，不构成人身攻击。")
    out.append("")
    return "\n".join(out)


def _rank_of_simple(team, slot, key):
    vals = sorted(team, key=lambda p: (p.get(key) or 0), reverse=True)
    for i, p in enumerate(vals):
        if p["player_slot"] == slot:
            return i + 1
    return 0



# ----------------------------------------------------------------------------
# 结构化输出（给 Web 前端 / 分享卡片用）
# ----------------------------------------------------------------------------
def build_payload(match, analysis, en, cn, user_account_id=None):
    """把分析结果整理成 JSON 友好的结构，供后端 API / 前端渲染。"""
    at = analysis["analyze_team"]
    opp_team = "radiant" if at == "dire" else "dire"
    ts = analysis["team_stats"][at]
    opp_ts = analysis["team_stats"][opp_team]
    rows = analysis["rows"]
    for _r in rows:
        _r["_team_rows"] = rows
    rwin = bool(match.get("radiant_win"))
    team_cn = "天辉" if at == "radiant" else "夜魇"
    enemy_cn = "夜魇" if at == "radiant" else "天辉"
    lost = at != ("radiant" if rwin else "dire")

    if analysis["my_slot"] is None:
        result_text = "%s获胜，%s落败" % ("天辉" if rwin else "夜魇", team_cn)
    else:
        result_text = "你方（%s）%s" % (team_cn, "落败" if lost else "获胜")

    players = []
    for r in rows:
        p = r["p"]
        ex = r.get("extra")
        item = {
            "rank": r["rank"],
            "title": rank_title(r["rank"]),
            "name": p.get("personaname") or "无名氏",
            "account_id": p.get("account_id"),
            "is_me": (user_account_id is not None and p.get("account_id") == user_account_id),
            "hero_cn": cn.get(p["hero_id"]) or en.get(p["hero_id"]) or str(p["hero_id"]),
            "hero_en": en.get(p["hero_id"]) or "",
            "pos": r["pos"],
            "share": round(r["share"], 1),
            "tags": crime_tags(r),
            "kda": "%d/%d/%d" % (p["kills"], p["deaths"], p["assists"]),
            "kills": p["kills"], "deaths": p["deaths"], "assists": p["assists"],
            "lh": p.get("last_hits") or 0,
            "denies": p.get("denies") or 0,
            "gpm": p.get("gold_per_min") or 0,
            "xpm": p.get("xp_per_min") or 0,
            "net_worth": p.get("net_worth") or 0,
            "hero_damage": p.get("hero_damage") or 0,
            "tower_damage": p.get("tower_damage") or 0,
            "tfp": round((p["kills"] + p["assists"]) / (ts["kills"] or 1) * 100.0, 1),
            "comp": {k: (round(v, 1) if v is not None else None) for k, v in r["comp"].items()},
            "verdict": verdict_text(r, ts),
            "extra": None,
        }
        if ex:
            item["extra"] = {
                "early": ex["early"], "mid": ex["mid"], "late": ex["late"],
                "fed": ex["fed"], "tf_died": ex["tf_died"],
                "zero_farm": ex["zero_farm"], "tf_share": round(ex["tf_share"], 1),
                "neutral_kills": ex["neutral_kills"], "ancient_kills": ex["ancient_kills"],
                "camps_stacked": ex["camps_stacked"], "buyback": ex["buyback"],
                "obs": p.get("obs_placed"), "sen": p.get("sen_placed"),
                "items": [{"time": t, "name": n} for t, n in (ex["items"] or [])],
                "gold10": ex["gold10"], "gold20": ex["gold20"],
                "gold30": ex["gold30"], "gold40": ex["gold40"],
                "lane_eff": ex["lane_eff"],
            }
        players.append(item)

    crash = None
    c = analysis.get("crash")
    if c:
        marks = []
        for th, key in ((3000, "t3"), (5000, "t5"), (10000, "t10"), (15000, "t15")):
            if c.get(key) is not None:
                marks.append({"minute": c[key], "label": "%.0fk" % (th / 1000.0)})
        crash = {
            "early_my": analysis["early_my"], "early_opp": analysis["early_opp"],
            "max_lead": int(c["max_lead"]), "max_lead_min": c["max_lead_min"],
            "marks": marks,
        }

    suspect = None
    if analysis["suspects"]:
        s = analysis["suspects"][0]
        sp = s["p"]
        srow = next(r for r in rows if r["p"]["player_slot"] == sp["player_slot"])
        suspect = {
            "name": sp.get("personaname") or "无名氏",
            "is_me": (user_account_id is not None and sp.get("account_id") == user_account_id),
            "hero_cn": cn.get(sp["hero_id"]) or en.get(sp["hero_id"]) or "",
            "pos": analysis["roles"][sp["player_slot"]],
            "greed": round(s["greed"], 1),
            "neutral_kills": s.get("neutral_kills") or 0,
            "part": round(s["part"], 1),
            "zero_farm": (srow.get("extra") or {}).get("zero_farm") or 0,
            "neutral_rank": extra_rank(rows, sp["player_slot"], "neutral_kills"),
        }

    opp = analysis["teams"][opp_team]
    opp_sorted = sorted(opp, key=lambda q: ((bpct(q, "hero_damage_per_min") or 0) +
                                            (bpct(q, "gold_per_min") or 0)), reverse=True)
    enemy_top = []
    for q in opp_sorted[:3]:
        enemy_top.append({
            "name": q.get("personaname") or "无名氏",
            "hero_cn": cn.get(q["hero_id"]) or en.get(q["hero_id"]) or "",
            "kda": "%d/%d/%d" % (q["kills"], q["deaths"], q["assists"]),
            "gpm": q.get("gold_per_min") or 0,
            "hero_damage": q.get("hero_damage") or 0,
            "lh": q.get("last_hits") or 0,
        })

    return {
        "ok": True,
        "match_id": match.get("match_id"),
        "info": {
            "start": fmt_date(match.get("start_time")),
            "duration": fmt_dur(analysis["duration"]),
            "mode": "%s · %s" % (LOBBY_TYPE.get(match.get("lobby_type"), "未知"),
                                 GAME_MODE.get(match.get("game_mode"), "未知")),
            "score": "%s : %s" % (match.get("radiant_score"), match.get("dire_score")),
            "result": result_text,
            "winner": "天辉" if rwin else "夜魇",
            "team": team_cn, "enemy": enemy_cn,
            "team_side": at,
            "parsed": analysis["parsed"],
            "building": ("我方 %d 塔 / %d 兵营被推；对面 %d 塔 / %d 兵营被推" % (
                analysis["our_towers_lost"] or 0, analysis["our_rax_lost"] or 0,
                analysis["opp_towers_lost"] or 0, analysis["opp_rax_lost"] or 0))
            if analysis["our_towers_lost"] is not None else "",
            "tournament": "",
        },
        "team_stats": {
            "mine": {"kills": ts["kills"], "net_worth": ts["net_worth"],
                     "hero_damage": ts["hero_damage"]},
            "enemy": {"kills": opp_ts["kills"], "net_worth": opp_ts["net_worth"],
                      "hero_damage": opp_ts["hero_damage"]},
        },
        "verdict": {
            "name": players[0]["name"] if players else "",
            "is_me": players[0]["is_me"] if players else False,
            "hero_cn": players[0]["hero_cn"] if players else "",
            "pos": players[0]["pos"] if players else 0,
            "share": players[0]["share"] if players else 0,
        },
        "players": players,
        "crash": crash,
        "suspect": suspect,
        "enemy_top": enemy_top,
        "user_found": analysis["my_slot"] is not None,
    }


class MatchNotFound(ValueError):
    """对局不存在 / OpenDota 暂无数据"""


def run(match_id, user_account_id=None, refresh=False):
    """给后端调用：返回 payload（含 report_md）。出错抛异常。"""
    try:
        match = fetch_match(match_id, refresh=refresh)
    except urllib.error.HTTPError as e:
        if e.code in (400, 404):
            raise MatchNotFound("对局 %s 不存在，或者 OpenDota 还没有收录这场比赛" % match_id)
        raise
    except urllib.error.URLError as e:
        raise RuntimeError("连接 OpenDota 失败：%s" % e)
    if match.get("error"):
        raise MatchNotFound("OpenDota 返回错误：%s" % match.get("error"))
    parsed = is_parsed(match)
    if not parsed:
        request_parse(match_id)
    en, cn = load_hero_names()
    analysis = analyze(match, user_account_id)
    payload = build_payload(match, analysis, en, cn, user_account_id)
    payload["report_md"] = render(match, analysis, en, cn, user_account_id)
    payload["parsed"] = parsed
    return payload


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Dota 2 分锅器")
    ap.add_argument("match_id", help="对局 ID（录像编号）")
    ap.add_argument("--user", type=int, default=None, help="你的 account_id（SteamID 32 位）")
    ap.add_argument("--out", default=None, help="输出 markdown 文件")
    ap.add_argument("--refresh", action="store_true", help="强制重新拉取对局数据")
    args = ap.parse_args()

    print("[1/3] 拉取对局 %s ..." % args.match_id, flush=True)
    match = fetch_match(args.match_id, refresh=args.refresh)
    if match.get("error"):
        print("OpenDota 错误:", match.get("error"))
        return 1

    parsed = is_parsed(match)
    print("      %s" % ("已解析" if parsed else "未解析（聚合数据）"), flush=True)
    if not parsed:
        r = request_parse(args.match_id)
        if r and r.get("job"):
            print("      已提交解析请求 jobId=%s（稍后 --refresh 重跑可升级）"
                  % r["job"].get("jobId"), flush=True)

    print("[2/3] 加载英雄名 / 计算分锅 ...", flush=True)
    en, cn = load_hero_names()
    analysis = analyze(match, args.user)

    print("[3/3] 生成判决书 ...", flush=True)
    report = render(match, analysis, en, cn, args.user)

    out = args.out or os.path.join(HERE, "report_%s.md" % args.match_id)
    with open(out, "w", encoding="utf-8") as f:
        f.write(report)
    print("已输出:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
