"""状态 → JSON 视图。

后端把所有派生展示数据都在这里算好，前端只做渲染
（表格、甘特图、饼图、汇总卡片），保证与桌面端显示口径一致。
"""

from __future__ import annotations

import copy
from html import escape as _esc

from src.api.consts import ELEMENT_MAP, PATH_MAP, character_icon_url
from src.core.freesr import RELIC_SUB_AFFIXES, parse_relic
from src.core.relics.labels import (
    MAX_SUB_AFFIXES,
    PCT_FIELDS,
    SLOT_NAMES,
    SUB_AFFIX_LABELS,
    main_affix_label,
    main_affix_options,
    relic_slot_summary,
    sub_affix_label,
)
from src.core.skill import SkillType
from src.web.session import (
    PANEL_KEYS,
    PANEL_LABELS,
    PERCENT_KEYS,
    ROW_COUNT,
    Row,
    Session,
)

ACTION_NAMES_ZH: dict[str, str] = {
    "normal": "普攻",
    "skill": "战技",
    "ultra": "终结技",
    "monster": "怪物行动",
    "aha_moment": "阿哈时刻",
    "follow_up": "追加攻击",
    "technique": "秘技",
    "enemy_attack": "敌方攻击",
    "memo_skill": "忆灵技",
    "countdown": "倒计时",
}

DAMAGE_TYPE_NAMES_ZH: dict[str, str] = {
    "normal": "常规",
    "break": "击破",
    "super_break": "超击破",
    "dot": "持续",
    "elation": "欢愉",
    "true": "真实伤害",
}

PREVIEW_AV_WINDOW = 300.0


# ── 格式化 ────────────────────────────────────────────────


def fmt_value(key: str, value: float) -> str:
    """面板数值格式化（百分比 → xx.x%，速度 1 位小数，其余整数/原样）。"""
    if key in PERCENT_KEYS:
        return f"{float(value) * 100:.1f}%"
    if key == "spd":
        return f"{float(value):.1f}"
    if key in ("hp", "atk", "def"):
        return str(int(round(float(value))))
    return f"{float(value):g}"


def meta_view() -> dict:
    """前端初始化所需的常量表。"""
    return {
        "panel_keys": list(PANEL_KEYS),
        "panel_labels": PANEL_LABELS,
        "percent_keys": sorted(PERCENT_KEYS),
        "paths": PATH_MAP,
        "elements": ELEMENT_MAP,
        "action_names": ACTION_NAMES_ZH,
        "damage_type_names": DAMAGE_TYPE_NAMES_ZH,
        "slots": [{"id": k, "name": v} for k, v in SLOT_NAMES.items()],
        "main_affixes": {
            str(slot): [{"id": mid, "label": label}
                        for mid, label in main_affix_options(slot)]
            for slot in SLOT_NAMES
        },
        "sub_affixes": [
            {"id": sid, "label": sub_affix_label(sid)} for sid in sorted(SUB_AFFIX_LABELS)
        ],
        # 副词条数值表：{id: {label, tiers:[t1,t2,t3], percent}}，供前端实时预览数值
        "sub_affix_table": {
            str(sid): {
                "label": SUB_AFFIX_LABELS.get(sid, str(sid)),
                "tiers": list(RELIC_SUB_AFFIXES[sid][1]),
                "percent": RELIC_SUB_AFFIXES[sid][0] in PCT_FIELDS,
            }
            for sid in RELIC_SUB_AFFIXES
        },
        "max_sub_affixes": MAX_SUB_AFFIXES,
        "row_count": ROW_COUNT,
        "limits": {
            "rank": [0, 6],
            "lightcone_rank": [1, 5],
            "enemy_count": [1, 5],
            "toughness": [1, 1000],
            "enemy_level": [1, 100],
            "non_weak_resist": [0, 100],
            "initial_sp": [0, 5],
            "max_av": [50, 10000],
            "skill_levels": {"normal": [1, 10], "skill": [1, 15], "ultra": [1, 15],
                             "talent": [1, 15], "memo": [1, 15], "elation": [1, 15]},
        },
    }


def _relic_items(row: Row) -> list[dict]:
    names = row.relic_set_names or {}
    items = []
    for raw in row.relics:
        if not isinstance(raw, dict):
            continue
        relic = parse_relic(raw)
        set_name = names.get(str(relic.relic_set_id), "")
        items.append({
            "slot": relic.slot,
            "slot_name": SLOT_NAMES.get(relic.slot, f"部位{relic.slot}"),
            "set_id": str(relic.relic_set_id),
            "set_name": set_name,
            "main_affix_id": relic.main_affix_id,
            "main_affix_label": main_affix_label(relic.slot, relic.main_affix_id),
            "subs": [
                {"id": sid, "label": sub_affix_label(sid), "count": count, "step": step}
                for sid, count, step in relic.sub_affixes
                if sid
            ],
            "summary": relic_slot_summary(relic, set_name),
        })
    return items


def row_view(row: Row, index: int) -> dict:
    counts = row.relic_set_counts or {}
    names = row.relic_set_names or {}
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    cells = row.cells or {}
    return {
        "index": index,
        "name": row.name,
        "char_id": row.char_id,
        "loaded": row.loaded,
        "path": row.path,
        "path_zh": PATH_MAP.get(row.path, row.path),
        "element": row.element,
        "element_zh": ELEMENT_MAP.get(row.element, row.element),
        "icon": character_icon_url(row.char_id) if row.char_id else "",
        "rank": row.rank,
        "values": {key: float(cells.get(key, 0.0)) for key in PANEL_KEYS},
        "cells": {key: fmt_value(key, cells.get(key, 0.0)) for key in PANEL_KEYS},
        "lightcone": {
            "id": row.lightcone_id,
            "name": row.lightcone_name,
            "rank": row.lightcone_rank,
            "label": (
                f"{row.lightcone_name}（{row.lightcone_rank} 叠影）"
                if row.lightcone_name else "未装备"
            ),
            "desc": row.lightcone_desc,
        },
        "relics": {
            "count": sum(counts.values()),
            "summary": (
                " · ".join(
                    f"{names.get(str(sid)) or sid}×{cnt}" for sid, cnt in ordered
                )
                if counts else "未配置"
            ),
            "sets": [
                {"id": str(sid), "name": names.get(str(sid), ""), "count": cnt}
                for sid, cnt in ordered
            ],
            "items": _relic_items(row),
        },
    }


def config_view(config: dict) -> dict:
    return {
        "enemy": dict(config.get("enemy") or {}),
        "battle": dict(config.get("battle") or {}),
        "skill_levels": dict(config.get("skill_levels") or {}),
        "enemy_attacks": list(config.get("enemy_attacks") or []),
    }


# ── 交互模拟 ──────────────────────────────────────────────


def _actor_kind(sim, actor) -> str:
    if actor.unit_id == "__aha__":
        return "阿哈"
    if actor.unit_id in sim._enemy_attack_map:
        return "敌方攻击"
    if actor.unit_id in sim.countdown_units:
        return "倒计时"
    if actor.is_monster:
        return "怪物"
    return "角色"


def _predict_timeline(sim) -> list[dict]:
    """静态推演未来 300 AV 的行动顺序（不修改模拟器状态）。"""
    if not sim.action_queue.entries or sim.total_av >= sim.max_av:
        return []
    queue = copy.deepcopy(sim.action_queue)
    actor = queue.next_actor()
    window_end = min(sim.total_av + PREVIEW_AV_WINDOW, sim.max_av)
    total_av = (sim.total_av if sim.pending_av_actor == actor.unit_id
                else sim.total_av + actor.current_av)
    items: list[dict] = []
    safety = 0
    while total_av <= window_end + 1e-9 and safety < 60:
        items.append({
            "unit_id": actor.unit_id,
            "name": actor.name,
            "kind": _actor_kind(sim, actor),
            "delta_av": round(total_av - sim.total_av, 1),
            "total_av": round(total_av, 1),
        })
        queue.advance()
        if actor.unit_id in sim._enemy_attack_map or actor.unit_id in sim.countdown_units:
            queue.remove(actor.unit_id)
        if not queue.entries:
            break
        actor = queue.next_actor()
        total_av += max(0.0, actor.current_av)
        safety += 1
    return items


def _character_buffs(sim, char) -> list[dict]:
    buffs = []
    for buff in char.buff_mgr.buffs:
        value = buff.value
        if buff.stat.endswith("_pct") or buff.stat in PERCENT_KEYS:
            text = f"+{value * 100:.1f}%"
        else:
            text = f"+{value:g}"
        remaining = buff.duration_count
        buffs.append({
            "name": buff.name,
            "stat": buff.stat,
            "text": text,
            "stacks": buff.current_stacks,
            "remaining": None if remaining is None or remaining < 0 else remaining,
            "debuff": bool(buff.is_debuff),
        })
    return buffs


def _sim_view(session: Session) -> dict | None:
    sim = session.sim
    if sim is None:
        return None

    ended = False
    status = ""
    kind = ""
    current = None
    pending = False
    if not sim.enemies:
        ended = True
        status = (f"战斗结束！全部敌人已死亡 · 总AV {sim.total_av:.1f}/{sim.max_av:.0f}"
                  f" · 总伤害 {sim.total_damage:.0f}")
    elif sim.total_av >= sim.max_av:
        ended = True
        status = (f"战斗结束！总AV {sim.total_av:.1f}/{sim.max_av:.0f}"
                  f" · 总伤害 {sim.total_damage:.0f} · 阿哈时刻 {sim.aha_count} 次")
    elif not sim.action_queue.entries:
        ended = True
        status = "行动队列为空，战斗结束"
    else:
        actor = sim.action_queue.next_actor()
        kind = _actor_kind(sim, actor)
        laugh = sum(c.laugh_point for c in sim.characters if c.is_elation)
        laugh_info = f" · 笑点 {laugh:.0f}" if laugh else ""
        pending = sim.pending_av_actor != actor.unit_id
        if pending:
            status = (f"按「推进」轮到下个行动者，或直接按 Q/E 推进并施放普攻/战技"
                      f" · 总AV {sim.total_av:.1f}/{sim.max_av:.0f}{laugh_info}")
        else:
            current = {"unit_id": actor.unit_id, "name": actor.name, "kind": kind}
            energy = " · ".join(f"{_esc(c.name)} {c.energy:.0f}" for c in sim.characters)
            status = (f"当前行动者：[{_esc(actor.name)}]（{kind}）· 总AV {sim.total_av:.1f}/{sim.max_av:.0f}"
                      f"{laugh_info}<br>全队能量：{energy}")

    next_uid = sim.action_queue.next_actor().unit_id if sim.action_queue.entries else ""
    active_uid = ""
    pending_uid = ""
    if sim.pending_av_actor:
        if sim.pending_av_actor == next_uid:
            active_uid = next_uid
        else:
            active_uid = sim.pending_av_actor
            pending_uid = next_uid
    else:
        pending_uid = next_uid

    orbs = []
    for char in sim.characters:
        stats = char.final_stats()
        module = sim.char_modules.get(char.unit_id)
        charge = getattr(module, "charge", None) if module is not None else None
        charge_style = getattr(module, "CHARGE_STYLE", "dots") if module else "dots"
        charge_max = 0
        if module is not None:
            charge_max = int(
                getattr(module, "charge_limit", 0)
                or getattr(module, "CHARGE_MAX", 0)
                or (3 if charge_style == "dots" else 9)
            )
        ultra_cost = sim._get_energy_cost(char, SkillType.ULTRA)
        orbs.append({
            "unit_id": char.unit_id,
            "name": char.name,
            "icon": character_icon_url(char.char_id) if char.char_id else "",
            "energy": round(char.energy, 1),
            "energy_max": round(stats.energy_max, 1),
            "hp": round(char.current_hp, 1),
            "hp_max": round(stats.hp, 1),
            "active": char.unit_id == active_uid,
            "pending": char.unit_id == pending_uid,
            "full": char.energy >= ultra_cost,
            "charge": (
                {"style": charge_style, "value": float(charge), "max": charge_max}
                if charge is not None else None
            ),
            "buffs": _character_buffs(sim, char),
        })

    enemies = []
    for enemy in sim.enemies:
        debuffs: list[dict] = []
        for module in sim.char_modules.values():
            try:
                for name, desc in module.enemy_buffs(sim, enemy) or []:
                    debuffs.append({"name": name, "desc": desc})
            except Exception:  # noqa: BLE001 - 模块实现问题不应中断渲染
                continue
        enemies.append({
            "unit_id": enemy.unit_id,
            "name": enemy.name,
            "hp": round(enemy.current_hp or 0, 1),
            "hp_max": round(enemy.max_hp, 1),
            "toughness": round(enemy.current_toughness, 1),
            "toughness_max": round(enemy.max_toughness, 1),
            "broken": enemy.is_broken,
            "weaknesses": [ELEMENT_MAP.get(w, w) for w in enemy.weakness_elements],
            "level": enemy.level,
            "selected": enemy.unit_id == session.selected_target,
            "debuffs": debuffs,
        })

    logs = [
        _interactive_log(i, log, False) for i, log in enumerate(sim.logs)
    ] + [
        _interactive_log(len(sim.logs) + i, log, True)
        for i, log in enumerate(session.old_logs)
    ]

    actor_for_buttons = None
    is_auto = False
    if sim.action_queue.entries:
        actor_entry = sim.action_queue.next_actor()
        is_auto = sim.is_auto_unit(actor_entry)
        actor_for_buttons = actor_entry.unit_id

    can = {
        "advance": (not ended and session.sim_active
                    and (pending or is_auto)),
        "act": (not ended and session.sim_active
                and not pending and not is_auto),
        "ultra": [
            (not ended and session.sim_active
             and char.energy >= sim._get_energy_cost(char, SkillType.ULTRA))
            for char in sim.characters
        ],
        "rewind": len(session.snapshots) > 1,
        "start": True,
    }

    return {
        "active": session.sim_active,
        "ended": ended,
        "status": status,
        "current": current,
        "pending": pending,
        "sp": sim.sp.current,
        "total_av": round(sim.total_av, 1),
        "max_av": round(sim.max_av, 1),
        "total_damage": round(sim.total_damage, 1),
        "orbs": orbs,
        "enemies": enemies,
        "logs": logs,
        "preview": _predict_timeline(sim),
        "can": can,
        "selected_target": session.selected_target,
        "actor_uid": actor_for_buttons or "",
    }


def _interactive_log(index: int, log, is_old: bool) -> dict:
    damages = ", ".join(f"{d:.0f}" for d in log.damages) if log.damages else "-"
    notes = log.notes or ""
    if log.enemy_broken:
        notes = "【击破】" + notes
    return {
        "index": index,
        "turn": index + 1,
        "av": round(log.av, 1),
        "total_av": round(log.total_av, 1),
        "actor": log.actor_name,
        "action": ACTION_NAMES_ZH.get(log.action_type, log.action_type),
        "damages": damages,
        "total": round(log.total_damage, 1),
        "notes": notes,
        "old": is_old,
    }


# ── 结果 ──────────────────────────────────────────────────


def _result_view(session: Session) -> dict | None:
    result = session.result
    if result is None:
        return None
    chars = session.result_chars
    enemies = session.result_enemies
    by_unit = {c.unit_id: c for c in chars}
    enemy_by_unit = {e.unit_id: e for e in enemies}

    logs = []
    for i, log in enumerate(result.logs):
        damages = ", ".join(f"{d:.0f}" for d in log.damages) if log.damages else "-"
        notes = ("【击破】" + log.notes) if log.enemy_broken else (log.notes or "")
        types = "、".join(dict.fromkeys(
            DAMAGE_TYPE_NAMES_ZH.get(rec.damage_type.value, rec.damage_type.value)
            for rec in log.damage_records
        )) or "-"
        logs.append({
            "turn": i + 1,
            "av": round(log.av, 1),
            "total_av": round(log.total_av, 1),
            "actor": log.actor_name,
            "action": ACTION_NAMES_ZH.get(log.action_type, log.action_type),
            "target": log.target_id or "-",
            "damages": damages,
            "segments": f"{len(log.damages)} 段" if log.damages else "-",
            "types": types,
            "total": round(log.total_damage, 1),
            "notes": notes or "-",
        })

    # 甘特图：按单位聚合
    unit_actions: dict[str, list] = {}
    order: list[str] = []
    for char in chars:
        unit_actions.setdefault(char.unit_id, [])
        order.append(char.unit_id)
    for enemy in enemies:
        if enemy.unit_id not in unit_actions:
            unit_actions[enemy.unit_id] = []
            order.append(enemy.unit_id)
    for log in result.logs:
        unit_actions.setdefault(log.actor_id, [])
        if log.actor_id not in order:
            order.append(log.actor_id)
        unit_actions[log.actor_id].append({
            "total_av": round(log.total_av, 1),
            "type": log.action_type,
            "label": ACTION_NAMES_ZH.get(log.action_type, log.action_type),
            "damage": round(log.total_damage, 1),
            "note": log.notes or "",
            "broken": log.enemy_broken,
        })
    lanes = []
    for uid in order:
        actions = unit_actions.get(uid) or []
        if not actions:
            continue
        if uid == "__aha__":
            name = "阿哈"
        elif uid in by_unit:
            name = by_unit[uid].name
        elif uid in enemy_by_unit:
            name = enemy_by_unit[uid].name
        else:
            name = uid
        lanes.append({"unit_id": uid, "name": name, "actions": actions})
    max_av = max((a["total_av"] for lane in lanes for a in lane["actions"]), default=0.0)
    max_av = max(50.0, (int(max_av / 50) + 1) * 50.0)

    # 伤害占比
    damage_by_unit: dict[str, float] = {}
    for log in result.logs:
        if log.actor_id == "__aha__" or log.actor_id.startswith("enemy"):
            continue
        damage_by_unit[log.actor_id] = damage_by_unit.get(log.actor_id, 0.0) + log.total_damage
    ordered = sorted(damage_by_unit.items(), key=lambda kv: kv[1], reverse=True)
    total = sum(d for _, d in ordered)
    pie = [
        {
            "unit_id": uid,
            "name": by_unit[uid].name if uid in by_unit else uid,
            "damage": round(damage, 1),
            "share": round(damage / total * 100, 1) if total > 0 else 0.0,
        }
        for uid, damage in ordered
    ]
    ranks = []
    for item in pie:
        char = by_unit.get(item["unit_id"])
        ranks.append({
            "name": item["name"],
            "path_zh": PATH_MAP.get(char.path, char.path) if char else "",
            "element_zh": ELEMENT_MAP.get(char.element, char.element) if char else "",
            "damage": item["damage"],
            "share": item["share"],
        })

    char_summary = []
    for char in chars:
        stats = char.final_stats()
        char_summary.append({
            "name": char.name,
            "path_zh": PATH_MAP.get(char.path, char.path),
            "element_zh": ELEMENT_MAP.get(char.element, char.element),
            "atk": round(stats.atk, 1),
            "spd": round(stats.spd, 1),
            "crit": f"{stats.crit_rate * 100:.1f}% / {stats.crit_dmg * 100:.1f}%",
            "energy": f"{char.energy:.0f}/{stats.energy_max:.0f}",
        })
    enemy_summary = [
        {
            "name": enemy.name,
            "toughness": f"{enemy.current_toughness:.0f}/{enemy.max_toughness:.0f}",
            "broken": "是" if enemy.is_broken else "否",
            "weaknesses": ", ".join(ELEMENT_MAP.get(w, w) for w in enemy.weakness_elements),
            "level": enemy.level,
        }
        for enemy in enemies
    ]

    return {
        "cards": {
            "turns": result.total_turns,
            "total_av": round(result.total_av, 1),
            "total_damage": round(result.total_damage, 0),
            "avg_per_turn": round(result.total_damage / max(1, result.total_turns), 0),
            "aha_count": result.aha_count,
            "final_sp": result.final_sp,
        },
        "end_reason": result.end_reason.value,
        "logs": logs,
        "lanes": lanes,
        "max_av": max_av,
        "pie": pie,
        "ranks": ranks,
        "char_summary": char_summary,
        "enemy_summary": enemy_summary,
    }


# ── 汇总 ──────────────────────────────────────────────────


def state_view(session: Session) -> dict:
    """前端一次渲染所需的全部数据。"""
    return {
        "rows": [row_view(row, i) for i, row in enumerate(session.rows)],
        "config": config_view(session.config),
        "sim": _sim_view(session),
        "result": _result_view(session),
        "message": session.message,
    }
