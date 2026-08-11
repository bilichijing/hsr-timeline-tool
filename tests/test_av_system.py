"""av_system 模块单元测试。"""

import pytest

from src.core.av_system import ActionEntry, ActionQueue, AV_PER_ACTION


class TestActionEntry:
    def test_reset_av(self):
        e = ActionEntry(unit_id="c1", name="C1", speed=100, current_av=50)
        e.reset_av()
        assert e.current_av == 100.0  # 10000 / 100


class TestActionQueue:
    def test_next_actor_min_av(self):
        q = ActionQueue()
        q.add(ActionEntry("c1", "C1", speed=100, current_av=80))
        q.add(ActionEntry("c2", "C2", speed=134, current_av=74.6))
        q.add(ActionEntry("c3", "C3", speed=120, current_av=83.3))
        assert q.next_actor().unit_id == "c2"

    def test_next_actor_empty_raises(self):
        q = ActionQueue()
        with pytest.raises(RuntimeError):
            q.next_actor()

    def test_advance(self):
        """测试 advance：AV 最小的先行动，所有单位 AV 减少，行动者重置。

        advance() 返回 (行动者, 本次消耗的 AV)。
        """
        q = ActionQueue()
        # c2 AV=74.6 < c1 AV=100，c2 先行动
        q.add(ActionEntry("c1", "C1", speed=100, current_av=100))
        q.add(ActionEntry("c2", "C2", speed=134, current_av=74.6))
        actor, consumed = q.advance()
        assert actor.unit_id == "c2"  # AV 最小的先行动
        assert consumed == pytest.approx(74.6)  # 本次消耗的 AV
        # c1 的 AV 应减少 74.6
        c1 = q.get("c1")
        assert c1.current_av == pytest.approx(100 - 74.6)
        # c2 重置为 10000/134 ≈ 74.6268
        c2 = q.get("c2")
        assert c2.current_av == pytest.approx(10000 / 134)

    def test_apply_push(self):
        q = ActionQueue()
        q.add(ActionEntry("c1", "C1", speed=100, current_av=100))
        q.apply_push("c1", 0.25)  # 延后 25%
        assert q.get("c1").current_av == 125.0

    def test_apply_pull(self):
        q = ActionQueue()
        q.add(ActionEntry("c1", "C1", speed=100, current_av=100))
        q.apply_pull("c1", 0.25)  # 提前 25%
        assert q.get("c1").current_av == 75.0

    def test_apply_pull_floor_zero(self):
        q = ActionQueue()
        q.add(ActionEntry("c1", "C1", speed=100, current_av=100))
        q.apply_pull("c1", 2.0)  # 提前 200%（超过 100%）
        assert q.get("c1").current_av == 0.0

    def test_update_speed(self):
        """测试速度变化公式：
        新 AV = 原 AV × 新基础 AV / 原基础 AV - 新基础 AV × (提前 - 延后)
        """
        q = ActionQueue()
        # 速度 100，基础 AV = 100，当前 AV = 80
        q.add(ActionEntry("c1", "C1", speed=100, current_av=80))
        # 速度变为 134，无推拉条
        q.update_speed("c1", new_speed=134)
        # 原 AV=80，新基础 AV=10000/134≈74.6268，原基础 AV=100
        # 新 AV = 80 × 74.6268 / 100 - 0 = 59.7014
        new_base_av = 10000 / 134
        expected = 80 * new_base_av / 100
        assert q.get("c1").current_av == pytest.approx(expected, abs=0.01)
        assert q.get("c1").speed == 134

    def test_update_speed_with_advance(self):
        """速度变化同时附带提前 25%。"""
        q = ActionQueue()
        q.add(ActionEntry("c1", "C1", speed=100, current_av=80))
        q.update_speed("c1", new_speed=134, advance_rate=0.25)
        # 新 AV = 80 × 74.6268/100 - 74.6268 × 0.25 = 59.7014 - 18.6567 = 41.0447
        new_base_av = 10000 / 134
        expected = 80 * new_base_av / 100 - new_base_av * 0.25
        assert q.get("c1").current_av == pytest.approx(expected, abs=0.1)

    def test_remove(self):
        q = ActionQueue()
        q.add(ActionEntry("c1", "C1", speed=100, current_av=100))
        q.remove("c1")
        assert q.get("c1") is None
        assert q.entries == []

    def test_snapshot_sorted(self):
        q = ActionQueue()
        q.add(ActionEntry("c1", "C1", speed=100, current_av=100))
        q.add(ActionEntry("c2", "C2", speed=134, current_av=74.6))
        snap = q.snapshot()
        assert snap[0][0] == "c2"  # AV 小的排前面
