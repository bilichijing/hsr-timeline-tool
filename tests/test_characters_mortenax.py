"""千冶•刃（Mortenax Blade, char_id=1507）技能模块单元测试。

技能参数取自 nanoka 真实数据（version 4.4.55）的 L1 数值。
测试角色面板：生命上限 10000（伤害断言以此计算）。
用 step() 手动驱动（不推进 total_av），敌人速度 1（几乎不行动），
避免 run() 默认逻辑与敌方行动的干扰。
"""

import pytest

from src.core.characters import MortenaxModule, get_module_cls
from src.core.simulator import BattleSimulator, CharacterUnit, EnemyState, PlayerAction
from src.core.skill import SkillType, parse_all_skills
from src.core.stats import BaseStats, StatBonus

ELEMENT = "Fire"


# ── 技能原始数据（L1 参数，取自 nanoka 1507）────────────────


def _mortenax_skills_raw():
    """千冶•刃九个技能的 nanoka 原始结构（新版 type + level）。"""
    lv = lambda params: {str(i + 1): {"param_list": list(params)} for i in range(15)}
    return {
        "150701": {
            "id": 150701, "name": "残锋，掠尽", "type": "Normal", "type_name": "普攻",
            "sp_base": 20, "bp_need": -1, "bp_add": 1,
            "show_stance_list": [30, 0, 0],
            "level": lv([0.25]),
        },
        "150702": {
            "id": 150702, "name": "刃下，归葬", "type": "BPSkill", "type_name": "战技",
            "sp_base": 30, "bp_need": -1,
            "show_stance_list": [15, 30, 0],
            "level": lv([0.36, 4, 0.12, 0.1]),
        },
        "150703": {
            "id": 150703, "name": "骸骨当炉，血肉即薪", "type": "Ultra", "type_name": "终结技",
            "sp_base": 5, "bp_need": -1,
            "show_stance_list": [0, 0, 0],
            "level": lv([0.2, 0.2, 0.3, 0.3, 70, 0.5, 0.2, 2]),
        },
        "150704": {
            "id": 150704, "name": "因果尽偿", "type": None, "type_name": "天赋",
            "sp_base": None, "bp_need": -1,
            "show_stance_list": [0, 0, 0],
            # 真实等级表：充能需求恒 9，回能量随等级 15→30（10 级 = 25）
            "level": {
                str(i + 1): {"param_list": [9, [15, 16, 17, 18, 19, 20, 21.25,
                                                22.5, 23.75, 25, 26, 27, 28, 29, 30][i]]}
                for i in range(15)
            },
        },
        "150706": {
            "id": 150706, "name": "断念一斩", "type": "MazeNormal", "type_name": "",
            "level": {"1": {"param_list": []}},
        },
        "150707": {
            "id": 150707, "name": "十方无赦", "type": "Maze", "type_name": "秘技",
            "level": lv([0.9, 2]),
        },
        "150708": {
            "id": 150708, "name": "淬锋，断魄", "type": "Normal", "type_name": "普攻",
            "sp_base": 20, "bp_need": -1, "bp_add": 1,
            "show_stance_list": [30, 0, 0],
            "level": lv([0.5]),
        },
        "150709": {
            "id": 150709, "name": "刃下，归葬", "type": "BPSkill", "type_name": "战技",
            "sp_base": 30, "bp_need": -1,
            "show_stance_list": [15, 30, 0],
            "level": lv([0.1]),
        },
        "150714": {
            "id": 150714, "name": "千冶铸一，万劫烬灭", "type": "Ultra", "type_name": "终结技",
            "sp_base": 5, "bp_need": -1,
            "show_stance_list": [0, 60, 0],
            "level": lv([2.1]),
        },
    }


def _make_mortenax(unit_id: str = "mortenax") -> CharacterUnit:
    """构造千冶•刃角色（L1 技能，生命上限 10000，终结技耗能 160）。"""
    char = CharacterUnit(
        unit_id=unit_id,
        name="千冶•刃",
        path="Warlock",
        element=ELEMENT,
        level=80,
        char_id="1507",
    )
    char.base_stats = BaseStats(hp_base=10000, spd_base=100, energy_max=160)
    char.bonus_stats = StatBonus()
    char.skills = parse_all_skills(_mortenax_skills_raw(), level=1, ultra_energy_cost=160)
    return char


def _make_enemy(broken: bool = True) -> EnemyState:
    """构造敌人（默认已击破，简化伤害断言；火弱点；速度 1 几乎不行动）。"""
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


def _make_sim(char: CharacterUnit, enemy: EnemyState) -> BattleSimulator:
    sim = BattleSimulator(characters=[char], enemies=[enemy], max_av=100000)
    sim.setup()
    return sim


def _module(sim: BattleSimulator) -> MortenaxModule:
    return sim.char_modules["mortenax"]


def _act(sim: BattleSimulator, skill_type: SkillType) -> None:
    """step 驱动一次角色行动。"""
    sim.step(PlayerAction(unit_id="mortenax", skill_type=skill_type, target_id="e1"))


def _freeze_countdown(sim: BattleSimulator) -> None:
    """把无量忿怒倒计时推到极远（测试结界内多次行动用）。

    真实机制：70 速倒计时在结界展开 142.86 AV 后行动，100 速千冶
    下一次行动（行动结束 +100 AV）晚于倒计时，结界内轮不到千冶行动。
    测试需要结界内行动时冻结倒计时。
    """
    mod = _module(sim)
    if mod.countdown_unit_id:
        entry = sim.action_queue.get(mod.countdown_unit_id)
        if entry is not None:
            entry.current_av = 999999.0


def _def_factor() -> float:
    """防御系数（千冶 80 级 vs 敌人 80 级；默认无减防 = 0.5）。"""
    return 100 / (100 + 100 * 1.0)


# ── 注册与初始化 ──────────────────────────────────────────


class TestRegistration:
    def test_registered(self):
        assert get_module_cls("1507") is MortenaxModule

    def test_battle_start_full_hp(self):
        char, enemy = _make_mortenax(), _make_enemy()
        sim = _make_sim(char, enemy)
        mod = _module(sim)
        assert char.current_hp == pytest.approx(10000)
        assert mod.rage is False
        assert mod.charge == 0


# ── 普攻 / 生命倍率 ───────────────────────────────────────


class TestNormalAttack:
    def test_normal_damage_by_max_hp(self):
        """普攻：25% 生命上限伤害（已击破：×防御系数 0.5）。"""
        char, enemy = _make_mortenax(), _make_enemy()
        sim = _make_sim(char, enemy)
        _act(sim, SkillType.NORMAL)
        # 2500 × 0.5 = 1250
        assert sim.logs[-1].total_damage == pytest.approx(1250)
        # 普攻回能 20（战斗开始能量已由【百炼骨】恢复至 75% = 120）
        assert char.energy == pytest.approx(140)
        # 普攻回复 SP
        assert sim.sp.current == 4

    def test_enhanced_normal_50pct_in_rage(self):
        """无量忿怒下普攻：强化版 50% 生命上限（150708）。"""
        char, enemy = _make_mortenax(), _make_enemy()
        sim = _make_sim(char, enemy)
        _act(sim, SkillType.ULTRA)  # 开结界
        assert _module(sim).rage is True
        _freeze_countdown(sim)
        _act(sim, SkillType.NORMAL)
        # 5000 × 易伤 1.3 × 防御系数（减防 20%）
        def_factor = 100 / (100 + 100 * 0.8)
        assert sim.logs[-1].total_damage == pytest.approx(5000 * 1.3 * def_factor)
        # 能量：终结技回 5 → 强化普攻回 20
        assert char.energy == pytest.approx(25)
        # 强化普攻回复 SP
        assert sim.sp.current == 4


# ── 战技 ──────────────────────────────────────────────────


class TestSkill:
    def test_skill_unavailable_without_rage(self):
        """非无量忿怒：无法施放战技（回合照常消耗，无伤害）。"""
        char, enemy = _make_mortenax(), _make_enemy()
        sim = _make_sim(char, enemy)
        _act(sim, SkillType.SKILL)
        assert "无法施放" in sim.logs[-1].notes
        assert sim.logs[-1].total_damage == 0
        # 无效行动不回能（战斗开始能量已恢复至 75% = 120）
        assert char.energy == pytest.approx(120)

    def test_skill_unavailable_at_hp_1(self):
        """生命 ≤1：即使无量忿怒也无法施放战技。"""
        char, enemy = _make_mortenax(), _make_enemy()
        sim = _make_sim(char, enemy)
        _act(sim, SkillType.ULTRA)
        _freeze_countdown(sim)
        char.current_hp = 1
        _act(sim, SkillType.SKILL)
        assert "无法施放" in sim.logs[-1].notes

    def test_skill_damage_and_hp_cost(self):
        """无量忿怒下战技：36% 全体 + 4×12% 随机、消耗 10% 生命、不耗 SP。"""
        char, enemy = _make_mortenax(), _make_enemy()
        sim = _make_sim(char, enemy)
        sp_before = sim.sp.current
        _act(sim, SkillType.ULTRA)
        assert char.current_hp == pytest.approx(8000)  # 终结技耗 20%
        _freeze_countdown(sim)
        _act(sim, SkillType.SKILL)
        # 生命消耗 10%
        assert char.current_hp == pytest.approx(7000)
        # 伤害 = (3600 + 4×1200) × 易伤 1.3 × 防御系数
        def_factor = 100 / (100 + 100 * 0.8)
        assert sim.logs[-1].total_damage == pytest.approx((3600 + 4 * 1200) * 1.3 * def_factor)
        # 战技不消耗战技点（也不回复）
        assert sim.sp.current == sp_before
        # 能量：战斗开始 120 → 终结技（120-160+5=5）→ 战技 30
        assert char.energy == pytest.approx(35)

    def test_skill_hp_cost_floor_1(self):
        """生命不足：战技消耗使当前生命降至 1。"""
        char, enemy = _make_mortenax(), _make_enemy()
        sim = _make_sim(char, enemy)
        _act(sim, SkillType.ULTRA)
        _freeze_countdown(sim)
        char.current_hp = 500
        _act(sim, SkillType.SKILL)
        assert char.current_hp == pytest.approx(1)


# ── 终结技 / 无量忿怒 ─────────────────────────────────────


class TestUltraRage:
    def test_ultra_open_rage(self):
        """终结技 150703：无伤害、消耗 20% 生命、全体煞火缠身、无量忿怒 buff、倒计时入队。"""
        char, enemy = _make_mortenax(), _make_enemy()
        sim = _make_sim(char, enemy)
        _act(sim, SkillType.ULTRA)
        log = sim.logs[-1]
        mod = _module(sim)
        # 本体无伤害
        assert log.total_damage == 0
        # 生命消耗 20%
        assert char.current_hp == pytest.approx(8000)
        # 无量忿怒 buff（暴击率 +20%、暴伤 +30%）
        assert mod.rage is True
        rage_buffs = [b for b in char.buff_mgr.buffs if b.name == "无量忿怒"]
        assert len(rage_buffs) == 2
        by_stat = {b.stat: b.value for b in rage_buffs}
        assert by_stat["crit_rate"] == pytest.approx(0.2)
        assert by_stat["crit_dmg"] == pytest.approx(0.3)
        # 煞火缠身：减防 +20%、易伤 +30%
        assert enemy.def_reduce == pytest.approx(0.2)
        assert enemy.vulnerability == pytest.approx(0.3)
        # 倒计时入队（70 速）
        assert mod.countdown_unit_id
        entries = [e for e in sim.action_queue.entries if e.unit_id == mod.countdown_unit_id]
        assert entries and entries[0].speed == pytest.approx(70)
        # 终结技回能 5（能量 0-160 后回 5）
        assert char.energy == pytest.approx(5)

    def test_enhanced_ultra_in_rage(self):
        """无量忿怒下终结技：替换为 150714（210% 全体），耗能 160。"""
        char, enemy = _make_mortenax(), _make_enemy()
        sim = _make_sim(char, enemy)
        _act(sim, SkillType.ULTRA)
        _freeze_countdown(sim)
        char.energy = 160
        _act(sim, SkillType.ULTRA)
        def_factor = 100 / (100 + 100 * 0.8)
        # 21000 × 易伤 1.3 × 防御系数
        assert sim.logs[-1].total_damage == pytest.approx(21000 * 1.3 * def_factor)
        # 扣 160 + 终结技回能 5
        assert char.energy == pytest.approx(5)
        # 结界未重新展开（倒计时仍存在）
        assert _module(sim).countdown_unit_id

    def test_countdown_expires_rage(self):
        """倒计时行动：结界解除、buff 清除、普攻恢复原版。

        100 速千冶开结界后，70 速倒计时（结界展开 142.86 AV 后行动）
        先于千冶下次行动（行动结束 +100 AV），所以结界内轮不到千冶行动。
        """
        char, enemy = _make_mortenax(), _make_enemy()
        sim = _make_sim(char, enemy)
        _act(sim, SkillType.ULTRA)
        mod = _module(sim)
        assert mod.rage is True
        # 倒计时行动（step 无 action，自动执行）
        assert sim.step() is not None
        assert mod.rage is False
        assert not any(b.name == "无量忿怒" for b in char.buff_mgr.buffs)
        assert mod.countdown_unit_id == ""
        # 倒计时日志
        assert sim.logs[-1].action_type == "countdown"
        # 结界解除后普攻恢复 25% 生命上限（煞火缠身独立计时，结界解除后仍在：
        # 减防 20% + 易伤 30%，持续 2 个敌方回合）
        _act(sim, SkillType.NORMAL)
        def_factor = 100 / (100 + 100 * 0.8)
        assert sim.logs[-1].total_damage == pytest.approx(2500 * 1.3 * def_factor)

    def test_ultra_hp_cost_floor_1(self):
        """生命不足：终结技消耗使当前生命降至 1。"""
        char, enemy = _make_mortenax(), _make_enemy()
        sim = _make_sim(char, enemy)
        char.current_hp = 500
        _act(sim, SkillType.ULTRA)
        assert char.current_hp == pytest.approx(1)


# ── 天赋充能 / 因果尽偿 ───────────────────────────────────


class TestTalentCharge:
    def test_charge_accumulates_per_action(self):
        """结界期间每次攻击（按行动计，含自身）+1 充能；战技 5 段只计 1 点。"""
        char, enemy = _make_mortenax(), _make_enemy()
        sim = _make_sim(char, enemy)
        _act(sim, SkillType.ULTRA)
        _freeze_countdown(sim)
        # 1 次战技（5 段命中）→ 充能 1
        _act(sim, SkillType.SKILL)
        assert _module(sim).charge == pytest.approx(1)
        # 再 7 次普攻 → 充能 8
        for _ in range(7):
            _act(sim, SkillType.NORMAL)
        assert _module(sim).charge == pytest.approx(8)

    def test_talent_extra_skill_at_9(self):
        """充能达 9：消耗充能、回 15 能量、额外施放战技（视为追加攻击）。"""
        char, enemy = _make_mortenax(), _make_enemy()
        sim = _make_sim(char, enemy)
        _act(sim, SkillType.ULTRA)
        _freeze_countdown(sim)
        # 8 次普攻 → 充能 8（能量 8×20 = 160 封顶）
        for _ in range(8):
            _act(sim, SkillType.NORMAL)
        assert _module(sim).charge == pytest.approx(8)
        assert char.energy == pytest.approx(160)
        # 第 9 次攻击触发天赋
        _act(sim, SkillType.NORMAL)
        mod = _module(sim)
        # 额外战技 5 段命中（同 log）→ 充能 1（清零后计回 1）
        assert mod.charge == pytest.approx(1)
        # 能量封顶 160（普攻 20 + 天赋 15 均被上限钳制）
        assert char.energy == pytest.approx(160)
        # 额外战技日志（追加攻击类型）
        fu_logs = [l for l in sim.logs if l.action_type == "follow_up"]
        assert fu_logs and "追加战技" in fu_logs[-1].notes
        # 伤害记录同时标记战技与追加攻击（secondary_skill_type=SKILL）
        assert all(
            r.secondary_skill_type == SkillType.SKILL
            for r in fu_logs[-1].damage_records
        )
        # 额外战技伤害 = 战技全套（36% + 4×12%）
        def_factor = 100 / (100 + 100 * 0.8)
        assert fu_logs[-1].total_damage == pytest.approx((3600 + 4 * 1200) * 1.3 * def_factor)
        # 额外战技消耗生命（8000 - 1000 = 7000；普攻不耗生命）
        assert char.current_hp == pytest.approx(7000)

    def test_charge_retained_when_uncastable(self):
        """生命 ≤1 时充能达标不触发（保留），生命恢复后触发。"""
        char, enemy = _make_mortenax(), _make_enemy()
        sim = _make_sim(char, enemy)
        _act(sim, SkillType.ULTRA)
        _freeze_countdown(sim)
        mod = _module(sim)
        # 充能 8、生命 1
        mod.charge = 8
        char.current_hp = 1
        _act(sim, SkillType.NORMAL)
        # 充能达到 9 但无法施放：保留
        assert mod.charge == pytest.approx(9)
        assert not any(l.action_type == "follow_up" for l in sim.logs)
        # 生命恢复后下一次攻击触发
        char.current_hp = 5000
        _act(sim, SkillType.NORMAL)
        assert any(l.action_type == "follow_up" for l in sim.logs)
        assert mod.charge == pytest.approx(1)

    def test_charge_capped_at_9(self):
        """充能封顶需求值（9），不溢出。"""
        char, enemy = _make_mortenax(), _make_enemy()
        sim = _make_sim(char, enemy)
        _act(sim, SkillType.ULTRA)
        _freeze_countdown(sim)
        mod = _module(sim)
        mod.charge = 9
        char.current_hp = 1  # 无法触发，验证封顶
        _act(sim, SkillType.NORMAL)
        assert mod.charge == pytest.approx(9)


# ── 煞火缠身 ──────────────────────────────────────────────


class TestBlaze:
    def test_blaze_expires_after_enemy_turns(self):
        """煞火缠身持续 2 个敌方回合后撤销减防/易伤贡献。"""
        char, enemy = _make_mortenax(), _make_enemy()
        sim = _make_sim(char, enemy)
        _act(sim, SkillType.ULTRA)
        assert enemy.def_reduce == pytest.approx(0.2)
        assert enemy.vulnerability == pytest.approx(0.3)
        mod = _module(sim)
        # 敌方行动 2 次
        for _ in range(2):
            mod.on_enemy_act(sim, enemy, sim.logs[0])
        assert enemy.def_reduce == pytest.approx(0.0)
        assert enemy.vulnerability == pytest.approx(0.0)
        assert enemy.unit_id not in mod.blaze

    def test_blaze_refresh_keeps_contribution(self):
        """天赋命中刷新煞火缠身计时，不重复叠加减防/易伤。"""
        char, enemy = _make_mortenax(), _make_enemy()
        sim = _make_sim(char, enemy)
        _act(sim, SkillType.ULTRA)
        _freeze_countdown(sim)
        # 结界内攻击一次（刷新计时）
        _act(sim, SkillType.NORMAL)
        assert enemy.def_reduce == pytest.approx(0.2)
        assert enemy.vulnerability == pytest.approx(0.3)


# ── 百炼骨（行迹额外能力）─────────────────────────────────


def _trace_with_bailiangu(ratio: float = 0.75) -> dict:
    """构造含【百炼骨】额外能力的行迹原始结构。"""
    return {
        "group1": {
            "pointA": {
                "point_type": 3,
                "point_name": "百炼骨",
                "point_desc": "战斗开始时或结界解除时，若能量不足#1[i]%则立刻恢复至#1[i]%。",
                "param_list": [ratio, 80],
            },
        },
    }


class TestTraceEnergyRegen:
    def test_battle_start_regen_to_75(self):
        """战斗开始能量不足 75% → 恢复至 75%（默认比例 0.75）。"""
        char, enemy = _make_mortenax(), _make_enemy()
        char.initial_energy = 50  # 低于 120
        sim = _make_sim(char, enemy)
        assert char.energy == pytest.approx(160 * 0.75)

    def test_battle_start_no_regen_when_above(self):
        """战斗开始能量 ≥75% → 不调整。"""
        char, enemy = _make_mortenax(), _make_enemy()
        char.initial_energy = 130
        sim = _make_sim(char, enemy)
        assert char.energy == pytest.approx(130)

    def test_battle_start_uses_trace_ratio(self):
        """恢复比例从行迹额外能力参数读取（如 0.5 → 80）。"""
        char, enemy = _make_mortenax(), _make_enemy()
        char.skill_trees_raw = _trace_with_bailiangu(0.5)
        sim = _make_sim(char, enemy)
        assert _module(sim).energy_ratio == pytest.approx(0.5)
        assert char.energy == pytest.approx(80)

    def test_rage_expire_regen_to_75(self):
        """结界解除（倒计时行动）时能量不足 75% → 恢复至 75%。"""
        char, enemy = _make_mortenax(), _make_enemy()
        sim = _make_sim(char, enemy)
        _act(sim, SkillType.ULTRA)  # 能量 120-160 → 0+5 = 5
        assert char.energy == pytest.approx(5)
        sim.step()  # 倒计时行动 → 结界解除
        assert not _module(sim).rage
        assert char.energy == pytest.approx(160 * 0.75)


# ── 战技拒绝原因（UI 弹窗）───────────────────────────────


class TestSkillDenyReason:
    def test_deny_without_rage(self):
        """未开启结界：拒绝原因为未开启结界。"""
        char, enemy = _make_mortenax(), _make_enemy()
        sim = _make_sim(char, enemy)
        assert "未开启结界" in _module(sim).skill_deny_reason(sim, char)

    def test_deny_at_hp_1(self):
        """生命 ≤1：拒绝原因为生命值过低。"""
        char, enemy = _make_mortenax(), _make_enemy()
        sim = _make_sim(char, enemy)
        _act(sim, SkillType.ULTRA)
        char.current_hp = 1
        assert "生命值" in _module(sim).skill_deny_reason(sim, char)

    def test_allowed_in_rage(self):
        """结界内生命 >1：可施放（返回 None）。"""
        char, enemy = _make_mortenax(), _make_enemy()
        sim = _make_sim(char, enemy)
        _act(sim, SkillType.ULTRA)
        assert _module(sim).skill_deny_reason(sim, char) is None


# ── 组队回归（模块不干扰队友）────────────────────────────


def _make_module_teammate() -> CharacterUnit:
    """构造带模块（不死途 1504）的队友角色，验证千冶模块不拦截队友技能。"""
    from src.core.damage import DamageType
    from src.core.skill import Skill, SkillEffect

    def make_skill(skill_id: str, name: str, skill_type: SkillType, mult: float) -> Skill:
        return Skill(
            id=skill_id, name=name, skill_type=skill_type,
            sp_cost=1 if skill_type == SkillType.SKILL else 0,
            effects=[SkillEffect(damage_type=DamageType.NORMAL, multiplier=mult)],
        )

    char = CharacterUnit(
        unit_id="mate",
        name="队友",
        path="Warlock",
        element="Fire",
        level=80,
        char_id="1504",  # 挂载不死途模块
    )
    char.base_stats = BaseStats(atk_base=1000, spd_base=150, energy_max=100)
    char.bonus_stats = StatBonus()
    char.skills = {
        "preset_normal": make_skill("preset_normal", "普攻", SkillType.NORMAL, 1.0),
        "preset_skill": make_skill("preset_skill", "战技", SkillType.SKILL, 1.5),
        "preset_ultra": Skill(
            id="preset_ultra", name="终结技", skill_type=SkillType.ULTRA,
            sp_cost=0, energy_cost=100,
            effects=[SkillEffect(damage_type=DamageType.NORMAL, multiplier=2.0)],
        ),
    }
    return char


class TestTeamwork:
    def test_teammate_skill_not_blocked(self):
        """千冶模块只解析自己的技能，不拦截队友的战技（伤害正常）。"""
        char1 = _make_mortenax()          # 千冶（未开结界）
        char2 = _make_module_teammate()   # 队友（不死途模块）
        enemy = _make_enemy()
        sim = BattleSimulator(characters=[char1, char2], enemies=[enemy], max_av=100000)
        sim.setup()
        sim.step(PlayerAction(unit_id="mate", skill_type=SkillType.SKILL, target_id="e1"))
        # 1500 × 防御系数 0.5 = 750
        assert sim.logs[-1].total_damage == pytest.approx(750)
        assert "无法施放" not in sim.logs[-1].notes

    def test_teammate_ultra_not_blocked(self):
        """千冶未开结界不影响队友终结技。"""
        char1 = _make_mortenax()
        char2 = _make_module_teammate()
        enemy = _make_enemy()
        sim = BattleSimulator(characters=[char1, char2], enemies=[enemy], max_av=100000)
        sim.setup()
        char2.energy = 100
        sim.step(PlayerAction(unit_id="mate", skill_type=SkillType.ULTRA, target_id="e1"))
        assert "无法施放" not in sim.logs[-1].notes
        assert sim.logs[-1].total_damage > 0

    def test_trigger_and_follow_up_both_charged_when_ashveil_first(self):
        """不死途在队伍前（分发顺序 ash 先）：触发攻击与追击各自计费，合计 2 层。

        回归：分发循环内不死途 begin_new_action 修改全局 action_token，
        千冶若读全局令牌会把本体命中误判为与追击同一行动（只计 1 层）。
        """
        from test_characters_ashveil import _ashveil_skills_raw

        # 队伍顺序 [不死途, 千冶, 角色D]：char_modules 分发顺序 {ash, mortenax}
        char1 = CharacterUnit(
            unit_id="ash", name="不死途", path="Rogue", element="Thunder",
            level=80, char_id="1504",
        )
        char1.base_stats = BaseStats(atk_base=1000, spd_base=90, energy_max=150)
        char1.bonus_stats = StatBonus()
        char1.skills = parse_all_skills(_ashveil_skills_raw(), level=10, ultra_energy_cost=150)

        char2 = _make_mortenax()
        char2.base_stats.spd_base = 200

        charD = _make_module_teammate()  # 角色 D（战技 1.5 倍率，150 速）

        enemy = _make_enemy()
        sim = BattleSimulator(
            characters=[char1, char2, charD], enemies=[enemy], max_av=100000
        )
        sim.setup()
        # 千冶（200 速）先开结界并冻结倒计时
        sim.step(PlayerAction(unit_id="mortenax", skill_type=SkillType.ULTRA, target_id="e1"))
        _freeze_countdown(sim)
        # 角色 D（150 速，开结界后剩 16.7 AV）战技 → 触发不死途天赋追击
        sim.step(PlayerAction(unit_id="mate", skill_type=SkillType.SKILL, target_id="e1"))
        fu = [l for l in sim.logs if l.action_type == "follow_up"]
        assert fu and "天赋追击" in fu[-1].notes
        # 角色 D 战技 1 层 + 追击 1 层 = 2 层
        assert _module(sim).charge == pytest.approx(2)

    def test_skill_chain_log_order_and_energy(self):
        """千冶战技连锁（战技→追击→追加战技）：日志顺序、充能 1/9、不死途能量按行动计。

        回归：
        - 战技额外段在 on_skill_end 打出（主日志先入列）→ 日志顺序正确
        - 千冶充能按令牌集合去重（连锁令牌交替 T/T+1/T+2 不重复计费）
        - 不死途天赋回 8 按行动计（战技 5 段命中只回一次），充能不足时回能照常
        """
        from test_characters_ashveil import _ashveil_skills_raw

        char1 = _make_mortenax()
        char1.base_stats.spd_base = 200
        char2 = CharacterUnit(
            unit_id="ash", name="不死途", path="Rogue", element="Thunder",
            level=80, char_id="1504",
        )
        char2.base_stats = BaseStats(atk_base=1000, spd_base=90, energy_max=150)
        char2.bonus_stats = StatBonus()
        char2.skills = parse_all_skills(_ashveil_skills_raw(), level=10, ultra_energy_cost=150)

        enemy = _make_enemy()
        sim = BattleSimulator(characters=[char1, char2], enemies=[enemy], max_av=100000)
        sim.setup()
        mod = sim.char_modules["mortenax"]
        ash = sim.char_modules["ash"]
        _act(sim, SkillType.ULTRA)
        _freeze_countdown(sim)
        # 场景：千冶充能 7/9、不死途圆点 1、能量 66
        mod.charge = 7
        ash.charge = 1
        char2.energy = 66
        _act(sim, SkillType.SKILL)
        # 日志顺序：战技 → 不死途追击 → 千冶追加战技
        tail = [(l.action_type, l.actor_id) for l in sim.logs[-3:]]
        assert tail == [
            ("skill", "mortenax"),
            ("follow_up", "ash"),
            ("follow_up", "mortenax"),
        ]
        # 千冶充能：7→8（战技）→9（追击）→0（天赋消耗）→1（追加战技）
        assert mod.charge == pytest.approx(1)
        # 不死途能量：66 + 8（战技受击）+ 5（追击回能，测试面板无能量恢复效率）+ 8（追加战技受击）
        assert char2.energy == pytest.approx(66 + 8 + 5 + 8, abs=0.01)
        # 不死途圆点耗尽
        assert ash.charge == pytest.approx(0)

    def test_ashveil_charge_max_3(self):
        """不死途追击充能上限为 3（头像圆点徽章用）。"""
        from src.core.characters import AshveilModule
        assert AshveilModule.CHARGE_STYLE == "dots"
        assert AshveilModule.CHARGE_MAX == 3

    def test_ashveil_ultra_chain_is_one_action(self):
        """不死途终结技：本体攻击 1 层 + 追击链（强化+婪酣）整体 1 层 = 2 层充能。"""
        from test_characters_ashveil import _ashveil_skills_raw

        char1 = _make_mortenax()  # 千冶（提速先行动）
        char1.base_stats.spd_base = 200
        char2 = CharacterUnit(
            unit_id="ash", name="不死途", path="Rogue", element="Thunder",
            level=80, char_id="1504",
        )
        char2.base_stats = BaseStats(atk_base=1000, spd_base=90, energy_max=150)
        char2.bonus_stats = StatBonus()
        char2.skills = parse_all_skills(_ashveil_skills_raw(), level=10, ultra_energy_cost=150)

        enemy = _make_enemy()
        sim = BattleSimulator(characters=[char1, char2], enemies=[enemy], max_av=100000)
        sim.setup()
        # 千冶开结界并冻结倒计时；再行动一次把不死途（90 速）推到前面
        sim.step(PlayerAction(unit_id="mortenax", skill_type=SkillType.ULTRA, target_id="e1"))
        assert _module(sim).rage is True
        _freeze_countdown(sim)
        sim.step(PlayerAction(unit_id="mortenax", skill_type=SkillType.NORMAL, target_id="e1"))
        # 不死途：攒满婪酣（8 层 → 2 段婪酣追击）与能量
        ash_mod = sim.char_modules["ash"]
        ash_mod.greed = 8
        char2.energy = 150
        # 终结技：本体命中 + 强化追击 + 2 段婪酣追击 = 3 个追加日志、4 次命中
        sim.step(PlayerAction(unit_id="ash", skill_type=SkillType.ULTRA, target_id="e1"))
        assert sim.logs[-1].actor_id == "ash"
        fu = [l for l in sim.logs if l.action_type == "follow_up"]
        # 终结技追击链：强化追击 + 2 段婪酣追击（千冶普攻还触发了 1 次天赋追击，另行统计）
        ultra_fu = [l for l in fu if "强化追击" in l.notes or "婪酣追击" in l.notes]
        assert len(ultra_fu) == 3
        # 千冶普攻 1 + 天赋追击 1 + 终结技本体 1 + 追击链整体 1 = 4 层充能
        assert _module(sim).charge == pytest.approx(4)

    def test_ashveil_talent_follow_up_is_separate_action(self):
        """不死途天赋追击是独立攻击：触发攻击 + 天赋追击 = 2 层充能。"""
        from test_characters_ashveil import _ashveil_skills_raw

        char1 = _make_mortenax()  # 千冶（提速先行动）
        char1.base_stats.spd_base = 200
        char2 = CharacterUnit(
            unit_id="ash", name="不死途", path="Rogue", element="Thunder",
            level=80, char_id="1504",
        )
        char2.base_stats = BaseStats(atk_base=1000, spd_base=90, energy_max=150)
        char2.bonus_stats = StatBonus()
        char2.skills = parse_all_skills(_ashveil_skills_raw(), level=10, ultra_energy_cost=150)

        enemy = _make_enemy()
        sim = BattleSimulator(characters=[char1, char2], enemies=[enemy], max_av=100000)
        sim.setup()
        sim.step(PlayerAction(unit_id="mortenax", skill_type=SkillType.ULTRA, target_id="e1"))
        _freeze_countdown(sim)
        # 千冶攻击饲饵（不死途战斗开始自动标记）→ 触发不死途天赋追击
        sim.step(PlayerAction(unit_id="mortenax", skill_type=SkillType.NORMAL, target_id="e1"))
        fu = [l for l in sim.logs if l.action_type == "follow_up"]
        assert fu and "天赋追击" in fu[-1].notes
        # 千冶攻击 1 层 + 不死途天赋追击 1 层 = 2 层
        assert _module(sim).charge == pytest.approx(2)


# ── 能量 / SP ─────────────────────────────────────────────


class TestEnergySp:
    def test_ultra_energy_cost_160(self):
        """终结技耗能 160（sp_need）。"""
        char, enemy = _make_mortenax(), _make_enemy()
        sim = _make_sim(char, enemy)
        char.energy = 160
        _act(sim, SkillType.ULTRA)
        assert char.energy == pytest.approx(5)  # 扣 160 + 终结技回能 5

    def test_skill_no_sp_cost(self):
        """战技 sp_cost=0（不消耗也不回复战技点）。"""
        skill = parse_all_skills(_mortenax_skills_raw(), level=1)["150702"]
        assert skill.sp_cost == 0

    def test_ultra_no_sp_change(self):
        """终结技（bp_need=-1）不回复战技点。"""
        skill = parse_all_skills(_mortenax_skills_raw(), level=1)["150703"]
        assert skill.sp_cost == 0


class TestEidolons:
    """星魂参数加载测试（完整战斗效果由核心机制测试覆盖）。"""

    def _with_rank(self, rank: int, ranks: dict):
        char = _make_mortenax()
        char.rank = rank
        char.ranks_raw = ranks
        sim = _make_sim(char, _make_enemy())
        return char, sim, _module(sim)

    def test_e2_charge_limit(self):
        """E2：充能上限降低至 7。"""
        _, _, module = self._with_rank(2, {
            "2": {"id": 150702, "name": "二魂", "desc": "充能上限降低", "param_list": [0.75, 7]},
        })
        assert module.charge_limit == 7

    def test_e6_enhanced_mult(self):
        """E6：强化终结技倍率提高为原倍率的 150%。"""
        _, _, module = self._with_rank(6, {
            "6": {"id": 150706, "name": "六魂", "desc": "倍率提高", "param_list": [1.5]},
        })
        assert module.e6_enhanced_mult == 1.5

    def test_e1_res_reduce(self):
        """E1：结界期间全属性抗性降低 20%。"""
        _, _, module = self._with_rank(1, {
            "1": {"id": 150701, "name": "一魂", "desc": "抗性降低", "param_list": [0.2, 0.15]},
        })
        assert module.e1_res_reduce == 0.2
