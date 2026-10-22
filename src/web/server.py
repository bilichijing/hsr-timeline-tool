"""标准库 HTTP 服务：静态前端 + JSON API。

不引入 FastAPI / Flask 等依赖，`python web_main.py` 即可运行：
多线程 HTTP 服务器 + 模块级会话（单用户本地工具）。
"""

from __future__ import annotations

import json
import mimetypes
import threading
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from src.api.client import (
    fetch_character_list,
    fetch_lightcone_list,
    fetch_relicset_list,
    run_in_loop,
)
from src.api.consts import ELEMENT_MAP, PATH_MAP
from src.api.transforms import (
    transform_character_list,
    transform_lightcone_list,
    transform_relicset_list,
)
from src.web.session import WebError
from src.web.views import config_view, meta_view, row_view, state_view

STATIC_DIR = (Path(__file__).parent / "static").resolve()

# 会话与锁（单用户；命令串行执行，避免并发改模拟器状态）
SESSION = None  # type: ignore[assignment]
SESSION_LOCK = threading.RLock()


def get_session():
    global SESSION
    if SESSION is None:
        from src.web.session import Session

        SESSION = Session()
    return SESSION


# ── 目录数据视图 ──────────────────────────────────────────


def character_catalog() -> list[dict]:
    raw = run_in_loop(fetch_character_list())
    return [
        {
            "id": c.id,
            "name_zh": c.name_zh,
            "name_en": c.name_en,
            "rarity": int(c.rarity),
            "path": c.path,
            "path_zh": PATH_MAP.get(c.path, c.path),
            "element": c.element,
            "element_zh": ELEMENT_MAP.get(c.element, c.element),
            "icon": c.icon_url,
        }
        for c in transform_character_list(raw)
    ]


def lightcone_catalog() -> list[dict]:
    raw = run_in_loop(fetch_lightcone_list())
    return [
        {
            "id": c.id,
            "name_zh": c.name_zh,
            "name_en": c.name_en,
            "rarity": int(c.rarity),
            "path": c.path,
            "path_zh": PATH_MAP.get(c.path, c.path),
            "atk": c.atk,
            "icon": c.icon_url,
        }
        for c in transform_lightcone_list(raw)
    ]


def relicset_catalog() -> list[dict]:
    raw = run_in_loop(fetch_relicset_list())
    items = []
    for rs in transform_relicset_list(raw):
        items.append({
            "id": rs.id,
            "name_zh": rs.name_zh,
            "name_en": rs.name_en,
            "icon": rs.icon_url,
            "inner": rs.bonus_4pc is None,
            "bonus_2pc": rs.bonus_2pc.desc if rs.bonus_2pc else "",
            "bonus_4pc": rs.bonus_4pc.desc if rs.bonus_4pc else "",
        })
    return items


# ── HTTP 层 ───────────────────────────────────────────────


class Handler(BaseHTTPRequestHandler):
    server_version = "HSRWeb/1.0"
    protocol_version = "HTTP/1.1"

    # ── 响应工具 ──────────────────────────────────────

    def _send_bytes(self, data: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if content_type.startswith(("text/", "application/javascript")):
            self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _send_json(self, payload, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_bytes(data, "application/json; charset=utf-8", status)

    def _error(self, message: str, status: int = 400) -> None:
        self._send_json({"error": message}, status)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise WebError(f"请求体不是合法 JSON: {e}") from e
        if not isinstance(data, dict):
            raise WebError("请求体必须是 JSON 对象")
        return data

    # ── 路由 ──────────────────────────────────────────

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path in ("/", "/index.html"):
                return self._serve_static("index.html")
            if path.startswith("/static/"):
                return self._serve_static(path[len("/static/"):])
            if path == "/api/meta":
                return self._send_json(meta_view())
            if path == "/api/state":
                with SESSION_LOCK:
                    return self._send_json(state_view(get_session()))
            if path == "/api/catalog/characters":
                return self._send_json(character_catalog())
            if path == "/api/catalog/lightcones":
                return self._send_json(lightcone_catalog())
            if path == "/api/catalog/relicsets":
                return self._send_json(relicset_catalog())
            if path == "/favicon.ico":
                return self._send_bytes(b"", "image/x-icon", 204)
            return self._error("未知路径: " + path, 404)
        except WebError as e:
            return self._error(str(e))
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            return self._error(f"服务器错误: {e}", 500)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            body = self._read_json()
            with SESSION_LOCK:
                message = self._dispatch(path, body)
                payload = {"message": message or "", "state": state_view(get_session())}
            return self._send_json(payload)
        except WebError as e:
            return self._error(str(e))
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            return self._error(f"服务器错误: {e}", 500)

    def _dispatch(self, path: str, body: dict) -> str:
        """执行写操作；返回给前端的提示文本。"""
        session = get_session()
        session.message = ""

        if path == "/api/team/name":
            session.set_name(int(body.get("row", 0)), str(body.get("name", "")))
        elif path == "/api/team/rank":
            session.set_rank(int(body.get("row", 0)), int(body.get("rank", 0)))
        elif path == "/api/team/panel":
            session.set_panel(int(body.get("row", 0)), body.get("values") or {})
        elif path == "/api/team/character":
            char_id = body.get("char_id")
            if not char_id:
                raise WebError("缺少 char_id")
            run_in_loop(session.set_character(int(body.get("row", 0)), str(char_id)))
        elif path == "/api/team/lightcone":
            run_in_loop(session.set_lightcone(
                int(body.get("row", 0)),
                body.get("lightcone_id"),
                int(body.get("rank", 1) or 1),
                bool(body.get("clear")),
            ))
        elif path == "/api/team/relics":
            relics = body.get("relics")
            if not isinstance(relics, list):
                raise WebError("relics 必须是数组")
            run_in_loop(session.set_relics(int(body.get("row", 0)), relics))
        elif path == "/api/config":
            self._update_config(session, body)
        elif path == "/api/import/freesr":
            data = body.get("data")
            if not isinstance(data, dict):
                raise WebError("缺少 freesr 数据")
            info = run_in_loop(session.import_freesr(data))
            unmatched = info.get("unmatched") or []
            text = f"已导入 {info['matched']} 个角色"
            if unmatched:
                text += f"；未匹配 {len(unmatched)} 个（不在队伍中）: " + "、".join(unmatched[:8])
            return text
        elif path == "/api/reset":
            session.reset()
            return "已重置队伍配置"
        elif path == "/api/sim/start":
            session.start_sim()
            message = session.message
            session.message = ""
            session.save()
            return message
        elif path == "/api/sim/advance":
            session.advance()
        elif path == "/api/sim/act":
            session.act(str(body.get("skill_type", "normal")))
        elif path == "/api/sim/ultra":
            session.ultra(int(body.get("index", 0)))
        elif path == "/api/sim/rewind":
            session.rewind(int(body.get("index", 0)))
        elif path == "/api/sim/target":
            session.select_target(str(body.get("unit_id", "")))
        elif path == "/api/sim/run":
            session.run()
            message = session.message
            session.message = ""
            session.save()
            return message
        else:
            raise WebError("未知接口: " + path, )

        message = session.message
        session.message = ""
        session.save()
        return message

    @staticmethod
    def _update_config(session, body: dict) -> None:
        """局部更新配置（enemy / battle / skill_levels / enemy_attacks）。"""
        cfg = session.config
        for section in ("enemy", "battle", "skill_levels"):
            patch = body.get(section)
            if not isinstance(patch, dict):
                continue
            merged = dict(cfg.get(section) or {})
            for key, value in patch.items():
                if key in merged:
                    merged[key] = value
            cfg[section] = merged
        attacks = body.get("enemy_attacks")
        if isinstance(attacks, list):
            cfg["enemy_attacks"] = [a for a in attacks if isinstance(a, dict)]

    # ── 静态资源 ──────────────────────────────────────

    def _serve_static(self, relative: str) -> None:
        rel = unquote(relative).replace("\\", "/").lstrip("/")
        target = (STATIC_DIR / rel).resolve()
        if STATIC_DIR not in target.parents and target != STATIC_DIR:
            return self._error("非法路径", 403)
        if not target.is_file():
            return self._error("文件不存在: " + rel, 404)
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or target.suffix in (".js", ".css"):
            content_type += "; charset=utf-8"
        self._send_bytes(target.read_bytes(), content_type)

    # ── 日志 ──────────────────────────────────────────

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        """静默常规访问日志（错误仍由上层 print 输出）。"""

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    """启动 HTTP 服务（阻塞）。"""
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    url = f"http://{host}:{port}/"
    print("=" * 58)
    print("  星穹铁道排轴工具 · Web 前端")
    print(f"  地址: {url}")
    print("  停止: Ctrl+C")
    print("=" * 58)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        server.server_close()
