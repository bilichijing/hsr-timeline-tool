"""buff 模块单元测试。"""

import pytest

from src.core.buff import Buff, BuffDuration, BuffManager, StackRule


def make_buff(
    buff_id: str = "b1",
    name: str = "攻击力提升",
    stat: str = "atk_pct",
    value: float = 0.2,
    duration_type: BuffDuration = BuffDuration.TURNS_SELF_END,
    duration_count: int = 2,
    source_unit: str = "c1",
    stack_rule: StackRule = StackRule.NO_STACK_SAME_NAME,
    max_stacks: int = 1,
    **kwargs,
) -> Buff:
    """构造 Buff 的便捷 helper。

    兼容 id= 作为 buff_id= 的别名。
    """
    # 允许 id= 作为 buff_id= 的别名
    if "id" in kwargs:
        buff_id = kwargs.pop("id")
    return Buff(
        id=buff_id,
        name=name,
        stat=stat,
        value=value,
        duration_type=duration_type,
        duration_count=duration_count,
        source_unit=source_unit,
        stack_rule=stack_rule,
        max_stacks=max_stacks,
    )


class TestBuffDuration:
    def test_permanent_never_expires(self):
        b = make_buff(duration_type=BuffDuration.PERMANENT, duration_count=-1)
        assert b.is_expired() is False

    def test_once_expires_after_trigger(self):
        b = make_buff(duration_type=BuffDuration.ONCE, duration_count=1)
        assert b.is_expired() is False
        b.duration_count = 0
        assert b.is_expired() is True

    def test_turns_expires_when_zero(self):
        b = make_buff(duration_type=BuffDuration.TURNS_SELF_END, duration_count=2)
        assert b.is_expired() is False
        b.duration_count = 0
        assert b.is_expired() is True


class TestBuffTickTurnEnd:
    """测试 TURNS_SELF_END 的扣减规则。"""

    def test_normal_decrement(self):
        """非自身回合内获得，正常扣减。"""
        b = make_buff(duration_count=2, source_unit="c1")
        b.applied_in_self_turn = False
        b.tick_turn_end("c1")
        assert b.duration_count == 1

    def test_skip_first_decrement_when_applied_in_self_turn(self):
        """自身回合内获得，首次扣减跳过。"""
        b = make_buff(duration_count=2, source_unit="c1")
        b.applied_in_self_turn = True
        b.tick_turn_end("c1")
        assert b.duration_count == 2  # 未扣减
        assert b.applied_in_self_turn is False  # 标志已清除

    def test_normal_decrement_after_first_skip(self):
        """首次跳过后，第二次正常扣减。"""
        b = make_buff(duration_count=2, source_unit="c1")
        b.applied_in_self_turn = True
        b.tick_turn_end("c1")
        assert b.duration_count == 2
        b.tick_turn_end("c1")  # 第二次
        assert b.duration_count == 1

    def test_other_unit_no_decrement(self):
        """非来源单位的回合结束不扣减。"""
        b = make_buff(duration_count=2, source_unit="c1")
        b.tick_turn_end("c2")
        assert b.duration_count == 2


class TestBuffManager:
    def test_add_simple(self):
        mgr = BuffManager(unit_id="c1")
        b = make_buff()
        mgr.add(b)
        assert len(mgr.buffs) == 1

    def test_no_stack_same_name_refresh(self):
        """同名 buff 不叠加，刷新时效。"""
        mgr = BuffManager(unit_id="c1")
        mgr.add(make_buff(duration_count=2, value=0.2))
        mgr.add(make_buff(duration_count=3, value=0.3))
        assert len(mgr.buffs) == 1
        # 取较大值
        assert mgr.buffs[0].duration_count == 3
        assert mgr.buffs[0].value == 0.3

    def test_stack_always(self):
        mgr = BuffManager(unit_id="c1")
        mgr.add(make_buff(stack_rule=StackRule.STACK_ALWAYS))
        mgr.add(make_buff(stack_rule=StackRule.STACK_ALWAYS))
        assert len(mgr.buffs) == 2

    def test_stack_limit_n(self):
        mgr = BuffManager(unit_id="c1")
        b1 = make_buff(stack_rule=StackRule.STACK_LIMIT_N, max_stacks=3)
        mgr.add(b1)
        b2 = make_buff(stack_rule=StackRule.STACK_LIMIT_N, max_stacks=3)
        mgr.add(b2)
        assert len(mgr.buffs) == 1
        assert mgr.buffs[0].current_stacks == 2

    def test_stack_limit_max(self):
        mgr = BuffManager(unit_id="c1")
        for _ in range(5):
            mgr.add(make_buff(stack_rule=StackRule.STACK_LIMIT_N, max_stacks=3))
        assert mgr.buffs[0].current_stacks == 3  # 最多 3 层

    def test_tick_turn_end_decrement(self):
        mgr = BuffManager(unit_id="c1")
        b = make_buff(duration_count=2, source_unit="c1")
        b.applied_in_self_turn = False
        mgr.add(b)
        mgr.tick_turn_end()
        assert mgr.buffs[0].duration_count == 1

    def test_clear_expired(self):
        mgr = BuffManager(unit_id="c1")
        b = make_buff(duration_count=1, source_unit="c1")
        b.applied_in_self_turn = False
        mgr.add(b)
        mgr.tick_turn_end()  # duration_count: 1 -> 0
        assert len(mgr.buffs) == 0  # 过期被清除

    def test_total_bonus(self):
        mgr = BuffManager(unit_id="c1")
        mgr.add(make_buff(stat="atk_pct", value=0.2))
        mgr.add(make_buff(id="b2", stat="atk_pct", value=0.1, source_unit="c2"))
        bonus = mgr.total_bonus()
        assert bonus.atk_pct == pytest.approx(0.3)

    def test_applied_in_self_turn_via_begin_turn(self):
        """通过 begin_turn 标记自身回合，添加 buff 时自动打标志。"""
        mgr = BuffManager(unit_id="c1")
        mgr.begin_turn()
        b = make_buff(duration_count=2, source_unit="c1")
        mgr.add(b)
        assert b.applied_in_self_turn is True
        # 回合结束：跳过首次扣减
        mgr.tick_turn_end()
        assert mgr.buffs[0].duration_count == 2
        mgr.end_turn()
        # 下一回合：正常扣减
        mgr.tick_turn_end()
        assert mgr.buffs[0].duration_count == 1

    def test_not_applied_when_not_in_self_turn(self):
        """非自身回合添加 buff，不打标志。"""
        mgr = BuffManager(unit_id="c1")
        # 不调用 begin_turn
        b = make_buff(duration_count=2, source_unit="c1")
        mgr.add(b)
        assert b.applied_in_self_turn is False
        mgr.tick_turn_end()
        assert mgr.buffs[0].duration_count == 1  # 正常扣减
