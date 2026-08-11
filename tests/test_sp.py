"""sp 模块单元测试。"""

from src.core.sp import SkillPoint


class TestSkillPoint:
    def test_initial(self):
        sp = SkillPoint()
        assert sp.current == 3
        assert sp.MAX == 5
        assert sp.INITIAL == 3

    def test_custom_initial(self):
        sp = SkillPoint(initial=5)
        assert sp.current == 5

    def test_consume_success(self):
        sp = SkillPoint()
        assert sp.consume(1) is True
        assert sp.current == 2

    def test_consume_insufficient(self):
        sp = SkillPoint()
        assert sp.consume(4) is False
        assert sp.current == 3  # 未消耗

    def test_recover(self):
        sp = SkillPoint(initial=2)
        sp.recover(1)
        assert sp.current == 3

    def test_recover_overflow(self):
        sp = SkillPoint(initial=4)
        sp.recover(2)
        assert sp.current == 5  # 不超过上限

    def test_can_consume(self):
        sp = SkillPoint(initial=2)
        assert sp.can_consume(2) is True
        assert sp.can_consume(3) is False

    def test_recover_returns_actual(self):
        sp = SkillPoint(initial=4)
        actual = sp.recover(10)
        assert actual == 1  # 只回复 1 点到上限
