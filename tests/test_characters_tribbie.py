"""缇宝（Tribbie, char_id=1403）技能模块单元测试。

技能参数取自 nanoka 真实数据（version 4.4.55）的 L1 数值。
测试角色面板：生命上限 10000（伤害断言以此计算），能量上限 120。
用 step() 手动驱动（不推进 total_av），敌人速度 1（几乎不行动）。
双角色队伍的 AV 顺序：缇宝 100 速 vs 队友 90 速 → 严格交替
tribbie → ally → tribbie → ally（step() 按 next_actor 行动）。
插队终结技（execute_ultra）不推进行动队列，不影响该顺序。
"""

import pytest

from src.core.characters import TribbieModule, get_module_cls
from src.core.simulator import BattleSimulator, CharacterUnit, EnemyState, PlayerAction
from src.core.skill import SkillType, parse_all_skills
from src.core.stats import BaseStats, StatBonus

ELEMENT = "Quantum"

# 缇宝 L1 参数
NORMAL_MULT = 0.15     # 普攻主目标 15% 生命上限
ULTRA_MULT = 0.15      # 终结技全体 15% 生命上限
FIELD_VULN = 0.15      # 结界敌方受伤提高 15%
EXTRA_MULT = 0.06      # 结界附加伤害 6%
TALENT_MULT = 0.09     # 天赋追击 9%
ORACLE_PEN = 0.12      # 神启抗性穿透 12%
ORACLE_TURNS = 3       # 神启持续 3 回合
FIELD_TURNS = 2        # 结界持续 2 回合
A2_RATIO = 0.09        # A2 行迹 HP 上限比例
A4_START = 30.0        # A4 战斗开始回能
A4_HIT = 1.5           # A4 攻击回能
A6_DMG = 0.72          # A6 增伤每层
A6_STACKS = 3          # A6 上限层数
A6_TURNS = 3           # A6 持续回合

ALLY_HP = 5000         # 队友生命上限


# ── 技能原始数据（L1 参数，取自 nanoka 1403）────────────────


def _tribbie_skills_raw():
    """缇宝五个技能的 nanoka 原始结构（新版 type + level）。"""
    lv = lambda params: {str(i + 1): {"param_list": list(params)} for i in range(15)}
    return {
        "140301": {
            "id": 140301, "name": "一百层的小火箭", "type": "Normal", "type_name": "普攻",
            "sp_base": 20, "bp_need": -1, "bp_add": 1,
            "show_stance_list": [30, 0, 15],
            "level": lv([NORMAL_MULT, 0.075]),
        },
        "140302": {
            "id": 140302, "name": "礼物都去哪儿了", "type": "BPSkill", "type_name": "战技",
            "sp_base": 30, "bp_need": 1,
            "show_stance_list": [0, 0, 0],
            "level": lv([ORACLE_PEN, ORACLE_TURNS]),
        },
        "140303": {
            "id": 140303, "name": "猜猜这里住着谁", "type": "Ultra", "type_name": "终结技",
            "sp_base": 5, "bp_need": -1,
            "show_stance_list": [0, 60, 0],
            "level": lv([ULTRA_MULT, FIELD_VULN, EXTRA_MULT, FIELD_TURNS]),
        },
        "140304": {
            "id": 140304, "name": "好忙好忙的缇宝", "type": None, "type_name": "天赋",
            "sp_base": 5, "bp_need": -1,
            "show_stance_list": [0, 15, 0],
            "level": lv([TALENT_MULT]),
        },
        "140307": {
            "id": 140307, "name": "开心你就拍拍手", "type": "Maze", "type_name": "秘技",
            "level": {"1": {"param_list": [3]}},
        },
    }


def _tribbie_trees_raw():
    """三个行迹额外能力（point_type=3）的原始结构。"""
    return {
        "point06": {"1": {
            "point_type": 3, "point_name": "城墙外的羊羔儿…",
            "param_list": [A6_DMG, A6_STACKS, A6_TURNS],
        }},
        "point07": {"1": {
            "point_type": 3, "point_name": "长翅膀的玻璃球！",
            "param_list": [A2_RATIO],
        }},
        "point08": {"1": {
            "point_type": 3, "point_name": "岔路旁的小石子？",
            "param_list": [A4_START, A4_HIT],
        }},
    }


def _make_tribbie(unit_id: str = "tribbie") -> CharacterUnit:
    """构造缇宝角色（L1 技能，生命上限 10000，能量上限 120）。"""
    char = CharacterUnit(
        unit_id=unit_id,
        name="缇宝",
        path="Shaman",
        element=ELEMENT,
        level=80,
        char_id="1403",
    )
    char.base_stats = BaseStats(hp_base=10000, spd_base=100, energy_max=120)
    char.bonus_stats = StatBonus()
    char.skills = parse_all_skills(_tribbie_skills_raw(), level=1, ultra_energy_cost=120)
    char.skill_trees_raw = _tribbie_trees_raw()
    return char


def _make_ally(unit_id: str = "ally") -> CharacterUnit:
    """构造无模块队友（90 速 < 缇宝 100 速 → 行动序列交替 tribbie→ally）。

    用于触发缇宝附加伤害 / A4 回能 / 天赋追击。
    """
    char = CharacterUnit(
        unit_id=unit_id,
        name="队友",
        path="Rogue",
        element="Thunder",
        level=80,
        char_id="",
    )
    char.base_stats = BaseStats(hp_base=ALLY_HP, atk_base=1000, spd_base=90, energy_max=100)
    char.bonus_stats = StatBonus()
    lv = lambda params: {"1": {"param_list": list(params)}}
    raw = {
        "1001": {
            "id": 1001, "name": "普攻", "type": "Normal", "type_name": "普攻",
            "sp_base": 20, "bp_need": -1, "bp_add": 1,
            "level": lv([1.0]),
        },
        "1002": {
            "id": 1002, "name": "战技", "type": "BPSkill", "type_name": "战技",
            "sp_base": 30, "bp_need": 1,
            "level": lv([1.0]),
        },
        "1003": {
            "id": 1003, "name": "终结技", "type": "Ultra", "type_name": "终结技",
            "sp_base": 5, "bp_need": -1, "energy_cost": 100,
            "level": lv([2.0]),
        },
    }
    char.skills = parse_all_skills(raw, level=1, ultra_energy_cost=100)
    return char


def _make_enemy(broken: bool = True) -> EnemyState:
    """构造敌人（默认已击破；量子弱点；速度 1 几乎不行动）。"""
    return EnemyState(
        unit_id="e1",
        name="史莱姆",
        max_toughness=100,
        current_toughness=0 if broken else 100,
        weakness_elements=[ELEMENT],
        is_broken=broken,
        level=80,
        speed=1,
    )


def _make_sim(*chars: CharacterUnit, enemy: EnemyState | None = None) -> BattleSimulator:
    sim = BattleSimulator(
        characters=list(chars),
        enemies=[enemy or _make_enemy()],
        max_av=100000,
    )
    sim.setup()
    return sim


def _module(sim: BattleSimulator) -> TribbieModule:
    return sim.char_modules["tribbie"]


def _act(sim: BattleSimulator, unit_id: str, skill_type: SkillType) -> None:
    """step 驱动一次行动。

    注意：step() 按 next_actor 行动（90 速队友与 100 速缇宝严格交替），
    action.unit_id 仅指定"轮到该角色时用什么技能"。若 next_actor 与
    unit_id 不符，本次行动的是 next_actor（行动日志 actor 可验证）。
    """
    sim.step(PlayerAction(unit_id=unit_id, skill_type=skill_type, target_id="e1"))


def _ultra(sim: BattleSimulator, unit_id: str) -> None:
    """插队终结技（不消耗回合、不推进行动队列）。"""
    for i, c in enumerate(sim.characters):
        if c.unit_id == unit_id:
            c.energy = c.base_stats.energy_max  # 充满能量
            sim.execute_ultra(i)
            return
    raise AssertionError(f"未找到角色 {unit_id}")


def _def_factor() -> float:
    """防御系数（80 级 vs 80 级；默认无减防 = 0.5）。"""
    return 100 / (100 + 100 * 1.0)


def _dmg(hp: float, mult: float, *zones: float) -> float:
    """伤害 = 生命上限 × 倍率 × 防御 × 各乘区（易伤/穿透等）。

    战斗开始秘技进战神启常驻 → 默认所有伤害吃 1.12 抗性穿透。
    """
    r = 1.0
    for v in zones:
        r *= v
    return hp * mult * _def_factor() * r * (1 + ORACLE_PEN)


def _extra_logs(sim: BattleSimulator) -> list:
    """含附加伤害（SkillType.ADDED）记录的行动日志（附加伤害并入触发行动）。"""
    return [
        l for l in sim.logs
        if any(r.skill_type == SkillType.ADDED for r in l.damage_records)
    ]


# ── 注册与初始化 ──────────────────────────────────────────


class TestRegistration:
    def test_registered(self):
        assert get_module_cls("1403") is TribbieModule

    def test_battle_start_a4_energy_and_oracle(self):
        """战斗开始：A4 回 30 能量；秘技进战获得【神启】（全体抗性穿透）。"""
        char = _make_tribbie()
        sim = _make_sim(char)
        mod = _module(sim)
        # A4 行迹：战斗开始恢复 30 点能量
        assert char.energy == pytest.approx(A4_START)
        # 秘技进战：获得神启 → 全体（含自己）res_pen buff
        assert char.final_stats().res_pen == pytest.approx(ORACLE_PEN)
        assert mod.field_turns == 0
        # 行迹参数已读取
        assert mod.a2_hp_ratio == pytest.approx(A2_RATIO)
        assert mod.a4_start_energy == pytest.approx(A4_START)
        assert mod.a4_hit_energy == pytest.approx(A4_HIT)
        assert mod.a6_dmg == pytest.approx(A6_DMG)
        assert mod.a6_max_stacks == A6_STACKS

    def test_no_trace_no_crash(self):
        """无行迹数据（预设角色）不崩溃，用兜底常量。"""
        char = _make_tribbie()
        char.skill_trees_raw = {}
        sim = _make_sim(char)
        mod = _module(sim)
        assert mod.a2_hp_ratio == pytest.approx(0.09)
        assert mod.a4_start_energy == pytest.approx(30.0)


# ── 神启（抗性穿透）───────────────────────────────────────


class TestOracle:
    def test_skill_applies_oracle_to_all_allies(self):
        """战技：获得【神启】——我方全体（含自己）抗性穿透提高。"""
        char, ally = _make_tribbie(), _make_ally()
        sim = _make_sim(char, ally)
        _act(sim, "tribbie", SkillType.SKILL)  # 第 1 次行动：缇宝
        assert char.final_stats().res_pen == pytest.approx(ORACLE_PEN)
        assert ally.final_stats().res_pen == pytest.approx(ORACLE_PEN)

    def test_skill_no_damage(self):
        """战技无伤害（#1 是抗性穿透而非倍率，effects 已清空）。"""
        char = _make_tribbie()
        sim = _make_sim(char)
        before = sim.total_damage
        _act(sim, "tribbie", SkillType.SKILL)
        assert sim.total_damage == before
        assert sim.logs[-1].total_damage == 0

    def test_res_pen_boosts_damage(self):
        """普攻伤害 = 750 × 1.12（HP 上限倍率 + 神启穿透，弱点抗性 0 → -12%）。"""
        char = _make_tribbie()
        sim = _make_sim(char)
        _act(sim, "tribbie", SkillType.NORMAL)
        assert sim.logs[-1].total_damage == pytest.approx(_dmg(10000, NORMAL_MULT))

    def test_normal_damage_by_max_hp(self):
        """普攻按生命上限计（atk=0 时依然有伤害）。"""
        char = _make_tribbie()
        sim = _make_sim(char)
        _act(sim, "tribbie", SkillType.NORMAL)
        # 10000 × 0.15 × 0.5 × 1.12 = 840
        assert sim.logs[-1].total_damage == pytest.approx(840)

    def test_oracle_counts_down_on_own_turn_only(self):
        """神启回合扣减：仅缇宝回合开始 -1（buff TURNS_SELF_START source_unit=缇宝）。

        行动序列：缇宝(1) → 队友(2) → 缇宝(3) → 缇宝(5)。
        """
        char, ally = _make_tribbie(), _make_ally()
        sim = _make_sim(char, ally)
        def buff_count():
            return next(b.duration_count for b in char.buff_mgr.buffs if b.id == "tribbie_oracle_pen")
        # 第 1 次行动：缇宝（回合开始 -1）
        _act(sim, "tribbie", SkillType.NORMAL)
        assert buff_count() == ORACLE_TURNS - 1
        # 第 2 次行动：队友（回合开始不扣缇宝的神启）
        _act(sim, "ally", SkillType.NORMAL)
        assert buff_count() == ORACLE_TURNS - 1
        # 第 3 次行动：缇宝（-1）
        _act(sim, "tribbie", SkillType.NORMAL)
        assert buff_count() == ORACLE_TURNS - 2
        # 第 5 次行动：缇宝（第 3 次缇宝回合，归零消失）
        _act(sim, "tribbie", SkillType.NORMAL)
        _act(sim, "ally", SkillType.NORMAL)
        _act(sim, "tribbie", SkillType.NORMAL)
        assert not any(b.id == "tribbie_oracle_pen" for b in char.buff_mgr.buffs)
        assert char.final_stats().res_pen == 0


# ── 终结技 / 结界 ─────────────────────────────────────────


class TestField:
    def test_ultra_damage_and_field(self):
        """终结技：开启结界（敌方受伤提高 15%）+ 本体伤害吃易伤。

        单角色场景 A2 行迹也生效：HP = 10000 × 1.09 = 10900。
        """
        char = _make_tribbie()
        enemy = _make_enemy()
        sim = _make_sim(char, enemy=enemy)
        _ultra(sim, "tribbie")
        mod = _module(sim)
        assert mod.field_turns == FIELD_TURNS
        assert enemy.vulnerability == pytest.approx(FIELD_VULN)
        # 终结技日志 = 本体伤害 + 附加伤害（附加伤害并入触发它的行动，
        # 均为 10900 × 倍率 × 0.5 × 1.15 × 1.12；易伤在 on_skill_cast 已生效）
        assert sim.logs[-1].total_damage == pytest.approx(
            _dmg(10000 * (1 + A2_RATIO), ULTRA_MULT, 1 + FIELD_VULN)
            + _dmg(10000 * (1 + A2_RATIO), EXTRA_MULT, 1 + FIELD_VULN)
        )

    def test_a2_hp_buff_during_field(self):
        """A2 行迹：结界期间缇宝生命上限 = 我方全体生命上限之和的 9%。"""
        char, ally = _make_tribbie(), _make_ally()
        sim = _make_sim(char, ally)
        _ultra(sim, "tribbie")
        # (10000 + 5000) × 9% = 1350
        a2_hp = (10000 + ALLY_HP) * A2_RATIO
        assert char.final_stats().hp == pytest.approx(10000 + a2_hp)
        # 终结技伤害用提高后的生命上限计算（本体 + 附加伤害并入同一日志）
        assert sim.logs[-1].total_damage == pytest.approx(
            _dmg(10000 + a2_hp, ULTRA_MULT, 1 + FIELD_VULN)
            + _dmg(10000 + a2_hp, EXTRA_MULT, 1 + FIELD_VULN)
        )

    def test_field_counts_down_on_own_turn(self):
        """结界持续 2 回合（缇宝回合开始 -1），归零解除（易伤撤销、A2 移除）。

        行动序列：缇宝(1) → 队友(2) → 缇宝(3)。
        """
        char, ally = _make_tribbie(), _make_ally()
        enemy = _make_enemy()
        sim = _make_sim(char, ally, enemy=enemy)
        _ultra(sim, "tribbie")
        mod = _module(sim)
        # 第 1 次行动：缇宝 → 2-1 = 1（结界仍在）
        _act(sim, "tribbie", SkillType.NORMAL)
        assert mod.field_turns == 1
        assert enemy.vulnerability == pytest.approx(FIELD_VULN)
        # 第 2 次行动：队友（不扣结界）
        _act(sim, "ally", SkillType.NORMAL)
        assert mod.field_turns == 1
        # 第 3 次行动：缇宝 → 1-1 = 0 解除
        _act(sim, "tribbie", SkillType.NORMAL)
        assert mod.field_turns == 0
        assert enemy.vulnerability == 0
        assert not any(b.id == "tribbie_a2_hp" for b in char.buff_mgr.buffs)

    def test_extra_damage_on_ally_attack(self):
        """结界期间我方攻击（按行动）：触发 1 次附加伤害（#3 倍率）。

        序列：缇宝终结技（插队）→ 缇宝普攻(1) → 队友普攻(2)。
        """
        char, ally = _make_tribbie(), _make_ally()
        sim = _make_sim(char, ally)
        _ultra(sim, "tribbie")
        a2_hp = (10000 + ALLY_HP) * A2_RATIO
        _act(sim, "tribbie", SkillType.NORMAL)  # 第 1 次：缇宝（也触发附加伤害）
        _act(sim, "ally", SkillType.NORMAL)     # 第 2 次：队友
        # 最后一条日志是队友普攻行动，附加伤害并入其中（AttackType=ADDED）
        assert sim.logs[-1].actor_id == "ally"
        assert sim.logs[-1].action_type == "normal"
        extra = _dmg(10000 + a2_hp, EXTRA_MULT, 1 + FIELD_VULN)
        extra_record = next(
            r for r in sim.logs[-1].damage_records if r.skill_type == SkillType.ADDED
        )
        assert extra_record.value == pytest.approx(extra)

    def test_extra_damage_once_per_action(self):
        """附加伤害按行动触发：一次攻击行动只触发 1 次（多段命中不重复）。

        每轮：终结技刷新结界（+1，本体命中触发）→ 缇宝普攻（+1）→ 队友普攻（+1）。
        结界 2 回合后自然解除（缇宝第 2 次行动回合），故每轮刷新。
        """
        char, ally = _make_tribbie(), _make_ally()
        sim = _make_sim(char, ally)
        for _ in range(3):
            _ultra(sim, "tribbie")  # 刷新结界（终结技本体命中触发 1 次）
            _act(sim, "tribbie", SkillType.NORMAL)
            _act(sim, "ally", SkillType.NORMAL)
            assert len(_extra_logs(sim)) == 3 * (_ + 1)

    def test_own_attack_triggers_extra_no_recursion(self):
        """缇宝自己的攻击也触发附加伤害（文本"我方目标"含自己），且不递归。

        终结技本体命中 1 次 + 普攻命中 1 次 = 2 条，无第三条。
        """
        char = _make_tribbie()
        sim = _make_sim(char)
        _ultra(sim, "tribbie")
        _act(sim, "tribbie", SkillType.NORMAL)
        assert len(_extra_logs(sim)) == 2  # 终结技、普攻各含 1 条，无递归
        # 缇宝普攻日志 = 普攻伤害 + 附加伤害（并入同一行动，普攻自身伤害不变）
        a2_hp = 10000 * A2_RATIO
        assert sim.logs[-1].total_damage == pytest.approx(
            _dmg(10000 + a2_hp, NORMAL_MULT, 1 + FIELD_VULN)
            + _dmg(10000 + a2_hp, EXTRA_MULT, 1 + FIELD_VULN)
        )


# ── A4 行迹（攻击回能）────────────────────────────────────


class TestA4:
    def test_ally_attack_regen_once_per_action(self):
        """A4：我方其他目标攻击（按行动）回 1.5 能量；同一行动只回 1 次。

        序列：队友普攻(2) 与 队友普攻(4)，中间夹缇宝普攻(1、3)。
        """
        char, ally = _make_tribbie(), _make_ally()
        sim = _make_sim(char, ally)
        _act(sim, "tribbie", SkillType.NORMAL)  # 第 1 次：缇宝（无 A4）
        before = char.energy
        _act(sim, "ally", SkillType.NORMAL)     # 第 2 次：队友
        assert char.energy == pytest.approx(before + A4_HIT)
        _act(sim, "tribbie", SkillType.NORMAL)  # 第 3 次：缇宝（无 A4）
        before = char.energy
        _act(sim, "ally", SkillType.NORMAL)     # 第 4 次：队友
        assert char.energy == pytest.approx(before + A4_HIT)

    def test_own_attack_no_regen(self):
        """A4 只吃"其他目标"攻击：缇宝自己的攻击不回能。"""
        char = _make_tribbie()
        sim = _make_sim(char)
        _act(sim, "tribbie", SkillType.NORMAL)
        # 30（A4 战斗开始）+ 20（普攻回能），无 A4 额外回能
        assert char.energy == pytest.approx(A4_START + 20)


# ── 天赋（队友终结技触发追击）─────────────────────────────


class TestTalentFollowUp:
    def test_ally_ultra_triggers_follow_up(self):
        """队友终结技后：缇宝对全体造成 #1 生命上限量子伤害（追加攻击）。"""
        char, ally = _make_tribbie(), _make_ally()
        sim = _make_sim(char, ally)
        _ultra(sim, "ally")
        # 缇宝追击日志在队友终结技日志之后（伤害吃神启穿透）
        assert sim.logs[-1].actor_id == "tribbie"
        assert sim.logs[-1].notes == "天赋追击"
        assert sim.logs[-1].total_damage == pytest.approx(_dmg(10000, TALENT_MULT))
        # 队友终结技本体日志在前
        assert sim.logs[-2].actor_id == "ally"
        assert sim.logs[-2].action_type == "ultra"
        # 追加攻击回能（天赋 sp_base=5）+ 队友终结技触发的 A4 回能 1.5
        assert char.energy == pytest.approx(A4_START + 5 + A4_HIT)

    def test_each_ally_once_until_reset(self):
        """每角色最多触发 1 次；缇宝施放终结技重置。"""
        char, ally = _make_tribbie(), _make_ally()
        sim = _make_sim(char, ally)
        _ultra(sim, "ally")
        _ultra(sim, "ally")  # 第二次队友终结技：次数已耗尽，不触发
        follow_ups = [l for l in sim.logs if l.notes == "天赋追击"]
        assert len(follow_ups) == 1
        # 缇宝终结技重置
        _ultra(sim, "tribbie")
        _ultra(sim, "ally")
        follow_ups = [l for l in sim.logs if l.notes == "天赋追击"]
        assert len(follow_ups) == 2

    def test_a6_stack_after_follow_up(self):
        """A6 行迹：天赋追击后增伤 72%/层，最多 3 层，3 回合后消失。

        （插队终结技不推进行动队列，末尾缇宝回合 = 第 1、3、5 次行动）
        """
        char, ally = _make_tribbie(), _make_ally()
        sim = _make_sim(char, ally)
        _ultra(sim, "ally")
        assert char.final_stats().dmg_bonus == pytest.approx(A6_DMG)
        # 缇宝终结技重置后再次追击 → 2 层
        _ultra(sim, "tribbie")
        _ultra(sim, "ally")
        assert char.final_stats().dmg_bonus == pytest.approx(2 * A6_DMG)
        # 再次重置再追击 → 满层 3
        _ultra(sim, "tribbie")
        _ultra(sim, "ally")
        assert char.final_stats().dmg_bonus == pytest.approx(3 * A6_DMG)
        # 满层后再追击：不超 3 层（刷新时效）
        _ultra(sim, "tribbie")
        _ultra(sim, "ally")
        assert char.final_stats().dmg_bonus == pytest.approx(3 * A6_DMG)
        # 3 个缇宝回合后 A6 消失（TURNS_SELF_START；序列中缇宝在第 1、3、5 次行动）
        _act(sim, "tribbie", SkillType.NORMAL)  # 1：缇宝
        _act(sim, "ally", SkillType.NORMAL)     # 2：队友
        _act(sim, "tribbie", SkillType.NORMAL)  # 3：缇宝
        _act(sim, "ally", SkillType.NORMAL)     # 4：队友
        _act(sim, "tribbie", SkillType.NORMAL)  # 5：缇宝
        assert char.final_stats().dmg_bonus == 0

    def test_own_ultra_no_follow_up(self):
        """缇宝自己的终结技不触发天赋追击（只重置）。"""
        char = _make_tribbie()
        sim = _make_sim(char)
        _ultra(sim, "tribbie")
        follow_ups = [l for l in sim.logs if l.notes == "天赋追击"]
        assert len(follow_ups) == 0

    def test_own_talent_follow_up_triggers_extra(self):
        """缇宝天赋追击（独立行动）也会触发结界附加伤害。"""
        char, ally = _make_tribbie(), _make_ally()
        sim = _make_sim(char, ally)
        _ultra(sim, "tribbie")  # 开结界（终结技本体触发 1 段）
        _ultra(sim, "ally")     # 队友终结技 → 缇宝天赋追击（独立行动）
        fu_log = next(l for l in sim.logs if l.actor_id == "tribbie" and l.notes == "天赋追击")
        added = [r for r in fu_log.damage_records if r.skill_type == SkillType.ADDED]
        assert len(added) == 1  # 追击命中触发 1 段附加伤害，并入追击日志
        # 结界期间 A2 提高 HP = (10000 + 5000) × 9%
        hp = 10000 + (10000 + ALLY_HP) * A2_RATIO
        assert fu_log.total_damage == pytest.approx(
            _dmg(hp, TALENT_MULT, 1 + FIELD_VULN) + _dmg(hp, EXTRA_MULT, 1 + FIELD_VULN)
        )

    def test_own_skill_no_extra(self):
        """缇宝战技无伤害（非攻击），不触发附加伤害。"""
        char = _make_tribbie()
        sim = _make_sim(char)
        _ultra(sim, "tribbie")
        _act(sim, "tribbie", SkillType.SKILL)
        assert len(_extra_logs(sim)) == 1  # 仅终结技那次，战技未增加


# ── 与其他角色模块的组合（附加伤害 ≠ 攻击）────────────────


class TestWithOtherModules:
    """附加伤害不是"攻击"：不触发"攻击后"系效果（不死途天赋、千冶充能）。"""

    def _twin_weakness_enemy(self) -> EnemyState:
        return EnemyState(
            unit_id="e1", name="史莱姆", max_toughness=100, current_toughness=0,
            weakness_elements=[ELEMENT, "Thunder"], is_broken=True, level=80, speed=1,
        )

    def test_ashveil_triggered_once_by_tribbie_ultra(self):
        """缇宝终结技命中 + 结界附加伤害：不死途天赋只触发 1 次。

        回归验证：附加伤害曾用"分发时全局令牌"触发不死途第 2 次追击
        （不死途追击 begin_new_action 改令牌 → 附加伤害被误判为新行动）。
        """
        from test_characters_ashveil import _make_ashveil

        ash = _make_ashveil()  # 100 速（先行动）
        char = _make_tribbie()
        char.base_stats.spd_base = 90
        sim = _make_sim(ash, char, enemy=self._twin_weakness_enemy())
        _ultra(sim, "tribbie")
        ash_fu = [l for l in sim.logs if l.actor_id == "ashveil" and l.notes == "天赋追击"]
        assert len(ash_fu) == 1
        # 附加伤害 1 段并入终结技日志（is_attack=False，未触发不死途）
        assert len([
            r for r in sim.logs[-1].damage_records if r.skill_type == SkillType.ADDED
        ]) == 1

    def test_ashveil_not_triggered_by_extra_damage(self):
        """缇宝普攻 + 附加伤害：不死途天赋仍只计缇宝的普攻 1 次。

        行动序列：不死途(1，自身攻击不触发) → 缇宝普攻(2)。
        """
        from test_characters_ashveil import _make_ashveil

        ash = _make_ashveil()
        char = _make_tribbie()
        char.base_stats.spd_base = 90
        sim = _make_sim(ash, char, enemy=self._twin_weakness_enemy())
        _ultra(sim, "tribbie")  # 结界开启，不死途 +1
        _act(sim, "tribbie", SkillType.NORMAL)  # 第 1 次行动：不死途（自身攻击不触发）
        _act(sim, "tribbie", SkillType.NORMAL)  # 第 2 次行动：缇宝普攻
        ash_fu = [l for l in sim.logs if l.actor_id == "ashveil" and l.notes == "天赋追击"]
        # 终结技 1 + 缇宝普攻 1；不死途追击/普攻也是我方攻击，各触发 1 段附加伤害
        # （5 次攻击行动 = 终结技/追击/不死途普攻/缇宝普攻/第2次追击，每行动 1 段）
        assert len(ash_fu) == 2
        assert len([
            r for l in sim.logs for r in l.damage_records
            if r.skill_type == SkillType.ADDED
        ]) == 5

    def test_mortenax_charge_not_triggered_by_extra_damage(self):
        """缇宝终结技 + 附加伤害：千冶充能只 +1（一次行动一次，附加伤害不计）。"""
        from test_characters_mortenax import _make_mortenax, _make_enemy as _mortenax_enemy

        mx = _make_mortenax()  # 千冶 100 速
        char = _make_tribbie()
        char.base_stats.spd_base = 90
        enemy = _mortenax_enemy()
        enemy.weakness_elements = [ELEMENT]  # 缇宝量子伤害可命中
        sim = _make_sim(mx, char, enemy=enemy)
        # 千冶终结技开结界（本体命中已计 1 次充能，含自身攻击）
        mx.energy = mx.base_stats.energy_max
        sim.execute_ultra(0)
        assert sim.char_modules["mortenax"].rage
        # 缇宝终结技：命中 1 次行动 → 充能 +1；附加伤害不计 → 共 2
        _ultra(sim, "tribbie")
        assert sim.char_modules["mortenax"].charge == 2
