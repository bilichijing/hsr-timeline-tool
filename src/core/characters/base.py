"""角色技能模块基类。

每个真实角色一个模块，通过事件钩子接入模拟器（模拟器发事件、模块响应）。
对比模拟器中硬编码的欢愉/阿哈机制，模块化让新角色无需改动模拟器核心。

约定：
- 子类定义 CHAR_ID（nanoka 角色 ID）与状态字段（纯数据：str/int/float/list），
  不持有 sim/char 引用——事件钩子每次传入，保证 snapshot() deepcopy 安全。
- 钩子按需覆盖，未覆盖的钩子走基类空实现（模拟器 getattr 分发，缺失即跳过）。
- 技能参数经 skill.params 读取（#N → params[N-1]），数据缺失时钩子应 no-op
  并在日志 notes 中标注，保证预设角色（无真实数据）不崩溃。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..simulator import BattleSimulator, CharacterUnit, EnemyState, PlayerAction
    from ..skill import Skill, SkillEffect
    from ..simulator import ActionLog


class CharacterModule:
    """角色技能模块基类。"""

    CHAR_ID: str = ""  # nanoka 角色 ID（如 "1504"）

    # ── 事件钩子（按需覆盖）──────────────────────────────

    def on_battle_start(self, sim: BattleSimulator, char: CharacterUnit) -> None:
        """战斗开始（setup() 末尾，模块实例化后）。"""

    def on_turn_start(self, sim: BattleSimulator, char: CharacterUnit) -> None:
        """角色回合开始（预留）。"""

    def on_turn_end(self, sim: BattleSimulator, char: CharacterUnit) -> None:
        """角色回合结束（预留）。"""

    def on_skill_cast(
        self,
        sim: BattleSimulator,
        char: CharacterUnit,
        skill: Skill,
        action: PlayerAction,
        target: EnemyState | None,
        log: ActionLog,
    ) -> None:
        """技能释放时（伤害结算前）：标记目标、追加伤害/回 SP 等。"""

    def on_attack_hit(
        self,
        sim: BattleSimulator,
        attacker: CharacterUnit,
        skill: Skill | None,
        target: EnemyState,
        effect: SkillEffect,
        damage: float,
        log: ActionLog | None,
    ) -> None:
        """攻击命中后（削韧/击破结算后）：判定天赋追加攻击等。

        skill 为发起攻击的技能；模块通过 deal_damage 发起的攻击时为 None。
        """

    def on_skill_end(
        self,
        sim: BattleSimulator,
        char: CharacterUnit,
        skill: Skill,
        action: PlayerAction,
        target: EnemyState | None,
        log: ActionLog,
    ) -> None:
        """技能结算后（本行动日志已入列）：触发终结技强化链等。"""


def module_params(skill: Any, index: int, default: float) -> float:
    """读取技能参数 #N（params[N-1]），缺失或越界时返回默认值。

    Args:
        skill: Skill 对象（无真实数据时 params 为空）
        index: 参数序号（#1 → index=1）
        default: 缺失时的回退值
    """
    params = getattr(skill, "params", None) or []
    if 1 <= index <= len(params):
        return params[index - 1]
    return default
