"""Web 后端测试：会话模型 / 视图 / HTTP 路由。

不依赖 PySide6；会话的数值口径与桌面端一致（面板 / 战斗构造 / 交互模拟）。
涉及 nanoka 网络的接口（角色详情 / 光锥 / 遗器套装目录）不在单测内打真实网络。
"""

from __future__ import annotations

import json
import shutil
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from src.web import server as web_server
from src.web.session import PANEL_KEYS, ROW_COUNT, Session, WebError
from src.web.views import meta_view, state_view


@pytest.fixture
def temp_dir():
    """独立临时目录（自行创建，避免依赖 pytest 的 basetemp 布局）。"""
    path = Path(tempfile.mkdtemp(prefix="hsr-web-test-"))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def session(monkeypatch, temp_dir):
    """隔离会话：缓存文件指向临时目录，避免读写真实 ./cache。"""
    monkeypatch.setattr("src.web.session.STATE_PATH", temp_dir / "web_state.json")
    return Session()


def _preset_row(session: Session, index: int = 0, name: str = "测试角色") -> None:
    """构造一行预设角色（不访问网络）。"""
    session.set_name(index, name)
    session.set_panel(index, {
        "hp": 12000, "atk": 1500, "def": 800, "spd": 134,
        "crit_rate": 0.3, "crit_dmg": 1.0, "break_effect": 0.5,
        "effect_res": 0.1, "energy_regen": 0.2, "effect_hit": 0.15,
        "outgoing_heal": 0.0, "dmg_bonus": 0.4,
    })


# ── 常量 / 视图 ───────────────────────────────────────────


class TestMetaView:
    def test_panel_meta(self):
        meta = meta_view()
        assert meta["panel_keys"] == list(PANEL_KEYS)
        assert meta["panel_labels"]["crit_rate"] == "暴击率"
        assert "crit_rate" in meta["percent_keys"]
        assert meta["row_count"] == ROW_COUNT

    def test_relic_affix_tables(self):
        meta = meta_view()
        assert [slot["id"] for slot in meta["slots"]] == [1, 2, 3, 4, 5, 6]
        assert len(meta["main_affixes"]["3"]) == 7          # 躯干 7 种主词条
        assert len(meta["sub_affix_table"]) == 12           # 12 种副词条
        assert meta["sub_affix_table"]["8"]["percent"] is True
        assert meta["max_sub_affixes"] == 4

    def test_limits(self):
        limits = meta_view()["limits"]
        assert limits["rank"] == [0, 6]
        assert limits["lightcone_rank"] == [1, 5]
        assert limits["enemy_count"] == [1, 5]


class TestStateView:
    def test_empty_state(self, session):
        view = state_view(session)
        assert set(view) == {"rows", "config", "sim", "result", "message"}
        assert len(view["rows"]) == ROW_COUNT
        assert view["sim"] is None and view["result"] is None
        row = view["rows"][0]
        assert row["lightcone"]["label"] == "未装备"
        assert row["relics"]["summary"] == "未配置"

    def test_panel_formatting(self, session):
        _preset_row(session)
        row = state_view(session)["rows"][0]
        assert row["name"] == "测试角色"
        assert row["cells"]["hp"] == "12000"
        assert row["cells"]["spd"] == "134.0"
        assert row["cells"]["crit_rate"] == "30.0%"
        assert row["cells"]["dmg_bonus"] == "40.0%"


# ── 会话模型 ─────────────────────────────────────────────


class TestSessionBasics:
    def test_reset_clears_rows(self, session):
        _preset_row(session)
        session.reset()
        assert all(not row.name for row in session.rows)
        assert session.config["enemy"]["count"] == 1

    def test_rank_clamped(self, session):
        session.set_rank(0, 99)
        assert session.rows[0].rank == 6
        session.set_rank(0, -5)
        assert session.rows[0].rank == 0

    def test_set_panel_ignores_unknown_and_bad_values(self, session):
        session.set_panel(0, {"hp": "12000", "nope": 1, "atk": "abc"})
        assert session.rows[0].cells["hp"] == 12000
        assert session.rows[0].cells["atk"] == 1000  # 默认值未被破坏

    def test_row_index_guard(self, session):
        with pytest.raises(WebError):
            session.set_name(9, "x")

    def test_persistence_roundtrip(self, session, temp_dir):
        try:
            (temp_dir / ".probe").write_text("x", encoding="utf-8")
        except OSError:  # 某些受限环境保护性地禁止写入系统临时目录
            pytest.skip("临时目录不可写，跳过落盘测试")
        _preset_row(session)
        session.save()
        assert (temp_dir / "web_state.json").exists()
        reloaded = Session()
        assert reloaded.rows[0].name == "测试角色"
        assert reloaded.rows[0].cells["hp"] == 12000


class TestBattleSetup:
    def test_build_enemies_from_config(self, session):
        session.config["enemy"].update({
            "count": 3, "toughness": 90, "hp": 200000,
            "weakness": "火, 冰", "level": 90, "non_weak_resist": 40,
        })
        enemies = session.build_enemies()
        assert [e.unit_id for e in enemies] == ["enemy1", "enemy2", "enemy3"]
        first = enemies[0]
        assert first.weakness_elements == ["Fire", "Ice"]
        assert first.resistance["Fire"] == pytest.approx(0.0)
        assert first.resistance["Physical"] == pytest.approx(0.4)
        assert first.level == 90
        assert first.speed == 0.0
        assert first.max_hp == pytest.approx(200000)

    def test_enemy_attack_slot_mapping(self, session):
        _preset_row(session, 0, "甲")
        _preset_row(session, 2, "丙")
        session.config["enemy_attacks"] = [
            {"total_av": 120, "source_enemy_index": 1, "attack": 1500,
             "target_indices": [0, 2, 3], "energy_recover": 10},
        ]
        attacks = session.build_enemy_attacks()
        assert len(attacks) == 1
        # 槽位 0/2 是已配置角色 → 下标 0/1；槽位 3 空 → 丢弃
        assert attacks[0].target_indices == [0, 1]
        assert attacks[0].total_av == pytest.approx(120)
        assert attacks[0].source_enemy_index == 1

    def test_build_characters_preset(self, session):
        _preset_row(session)
        chars, warnings = session.build_characters()
        assert not warnings
        assert len(chars) == 1
        char = chars[0]
        assert char.unit_id == "char1"
        assert char.final_stats().hp == pytest.approx(12000)
        assert char.final_stats().atk == pytest.approx(1500)
        assert char.final_stats().spd == pytest.approx(134)
        assert char.final_stats().crit_rate == pytest.approx(0.3)

    def test_build_characters_skips_empty_rows(self, session):
        _preset_row(session, 1, "第二行")
        chars, _ = session.build_characters()
        assert [c.unit_id for c in chars] == ["char2"]


class TestRun:
    def test_run_requires_character(self, session):
        with pytest.raises(WebError):
            session.run()

    def test_run_produces_result(self, session):
        _preset_row(session)
        session.config["battle"].update({"max_av": 300, "action_mode": 0})
        result = session.run()
        assert result.total_av >= 300
        assert result.logs
        view = state_view(session)["result"]
        assert view is not None
        assert view["cards"]["turns"] >= 1
        assert view["lanes"]
        assert sum(item["share"] for item in view["pie"]) > 0
        assert view["char_summary"][0]["name"] == "测试角色"


class TestInteractive:
    def test_flow_start_advance_act_rewind(self, session):
        _preset_row(session)
        session.start_sim()
        sim = session.sim
        assert sim is not None
        assert session.sim_active
        assert not sim.logs  # 停在待推进阶段

        session.advance()
        assert sim.total_av > 0

        # 轮到角色则释放战技
        actor = sim.action_queue.next_actor()
        if sim.pending_av_actor == actor.unit_id and not sim.is_auto_unit(actor):
            sp_before = sim.sp.current
            session.act("skill")
            assert sim.sp.current == sp_before - 1
            assert sim.logs

        # 回溯到第一帧
        session.rewind(0)
        assert sim.logs == []
        assert session.old_logs

    def test_act_requires_sim(self, session):
        with pytest.raises(WebError):
            session.act("normal")

    def test_ultra_without_energy_raises(self, session):
        _preset_row(session)
        session.start_sim()
        with pytest.raises(WebError):
            session.ultra(0)

    def test_rewind_invalid_index(self, session):
        _preset_row(session)
        session.start_sim()
        with pytest.raises(WebError):
            session.rewind(5)

    def test_select_target(self, session):
        session.config["enemy"].update({"count": 2})
        _preset_row(session)
        session.start_sim()
        session.select_target("enemy2")
        view = state_view(session)["sim"]
        assert [e["selected"] for e in view["enemies"]] == [False, True]


# ── HTTP 路由 ────────────────────────────────────────────


@pytest.fixture
def http_session(monkeypatch, temp_dir):
    """起一个真实 HTTP 服务（随机端口），会话缓存指向临时目录。"""
    monkeypatch.setattr("src.web.session.STATE_PATH", temp_dir / "web_state.json")
    web_server.SESSION = None
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), web_server.Handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        web_server.SESSION = None


def _get(url: str, timeout: float = 30.0):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.status, resp.headers.get("Content-Type", ""), resp.read()


def _post_json(url: str, body: dict):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30.0) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8"))


class TestHttp:
    def test_meta_and_state(self, http_session):
        status, _, body = _get(http_session + "/api/meta")
        assert status == 200
        assert json.loads(body)["panel_keys"] == list(PANEL_KEYS)

        status, _, body = _get(http_session + "/api/state")
        assert status == 200
        state = json.loads(body)
        assert len(state["rows"]) == ROW_COUNT

    def test_index_html_served(self, http_session):
        status, content_type, body = _get(http_session + "/")
        assert status == 200
        assert "text/html" in content_type
        assert "星穹铁道排轴工具" in body.decode("utf-8")

    def test_static_js_served(self, http_session):
        status, content_type, body = _get(http_session + "/static/js/app.js")
        assert status == 200
        assert "javascript" in content_type
        assert len(body) > 1000

    def test_static_path_traversal_blocked(self, http_session):
        try:
            status, _, _ = _get(http_session + "/static/../session.py")
        except urllib.error.HTTPError as err:
            status = err.code
        assert status in (403, 404)

    def test_set_name_and_panel(self, http_session):
        status, payload = _post_json(http_session + "/api/team/name", {"row": 0, "name": "甲"})
        assert status == 200 and payload["state"]["rows"][0]["name"] == "甲"

        status, payload = _post_json(
            http_session + "/api/team/panel", {"row": 0, "values": {"hp": 4321}},
        )
        assert status == 200
        assert payload["state"]["rows"][0]["cells"]["hp"] == "4321"

    def test_config_patch(self, http_session):
        status, payload = _post_json(
            http_session + "/api/config", {"enemy": {"count": 3, "toughness": 90}},
        )
        assert status == 200
        enemy = payload["state"]["config"]["enemy"]
        assert enemy["count"] == 3 and enemy["toughness"] == 90
        assert enemy["hp"] == 100000  # 未提交的字段保持原值

    def test_sim_run_and_rewind(self, http_session):
        _post_json(http_session + "/api/team/name", {"row": 0, "name": "甲"})
        status, payload = _post_json(http_session + "/api/sim/run", {})
        assert status == 200
        result = payload["state"]["result"]
        assert result and result["logs"]
        assert result["cards"]["turns"] >= 1

    def test_unknown_endpoint_and_errors(self, http_session):
        status, payload = _post_json(http_session + "/api/nope", {})
        assert status == 400
        assert "未知接口" in payload["error"]

        status, payload = _post_json(http_session + "/api/sim/act", {"skill_type": "skill"})
        assert status == 400
        assert "交互模拟" in payload["error"]

    def test_run_without_character_returns_error(self, http_session):
        status, payload = _post_json(http_session + "/api/sim/run", {})
        assert status == 400
        assert "至少需要一个角色" in payload["error"]
