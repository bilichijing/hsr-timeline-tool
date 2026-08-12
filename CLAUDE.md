# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

崩坏：星穹铁道 排轴与伤害计算工具（桌面应用，PySide6 + Python ≥3.10）。数据源为 nanoka（`static.nanoka.cc`），核心是 AV 行动值系统与战斗模拟引擎。所有 UI 文本、代码注释、文档均为中文，新代码应保持一致。

## 常用命令

```bash
# 运行 GUI（入口）
python ui_main.py

# 运行测试（当前 118 个全部通过）
python -m pytest            # 全部
python -m pytest tests/test_av_system.py   # 单个文件
python -m pytest tests/test_av_system.py -k "next_actor"  # 单测
python -m pytest -q -W ignore::pytest.PytestConfigWarning   # 忽略 asyncio_mode 警告

# Lint / 格式化（ruff，line-length=100，pyproject.toml 已配置）
ruff check .
ruff format .

# 实测 API 数据通路（打真实网络，带 diskcache）
python verify_api.py
```

注意：`pyproject.toml` 中 `asyncio_mode = "auto"` 需要 pytest-asyncio，当前环境未装会告警但测试照常通过。

## 架构

分层结构，依赖方向：`ui → core`、`ui → api`，`core` 与 `api` 互不依赖。

- **`src/api/`** — 数据层，全部指向 nanoka：
  - `consts.py` — 基址常量、枚举映射（稀有度/命途/属性）、图标 URL 构造（纯函数）。
  - `client.py` — httpx 异步单例 + diskcache 模块级缓存单例（`./cache` 目录，TTL 见 `CacheTTL`）。所有网络请求必须经过此模块；请求失败时回退过期缓存。应用退出需调 `close_client()`。
  - `models.py` / `transforms.py` — pydantic 模型与"nanoka 原始结构 → 业务模型"的提纯函数（纯函数，无 IO）。

- **`src/core/`** — 业务核心，**不得导入任何 PySide6 代码**，可独立测试：
  - `av_system.py` — 行动值系统。核心公式 `AV = 10000 / 速度`；`ActionQueue.advance()` 返回（行动者, 消耗 AV）并把行动者 AV 重置，其余单位扣减；`update_speed()` 用官方换速公式（见文件 docstring）；推条 `AV×(1+rate)`、拉条 `max(0, AV×(1-rate))`。`unit_id` 是字符串（`"monster_1"`、`"__aha__"` 等）。
  - `simulator.py` — 战斗模拟引擎。三种运行方式：`run(actions)` 一次性跑完（到 `max_av` 默认 300 结束）；`step(action)` 交互步进；`execute_ultra(char_index)` 终结技插队（不推进队列、不消耗回合）。`snapshot()`/`restore()` 做快照回溯（交互模式回退用）。`setup()` 必须先调。
  - `damage.py` — 伤害公式（`calculate_damage(DamageContext)`），含普攻/技能/终结/击破/欢愉（ELATION）伤害类型。
  - `buff.py`、`sp.py`、`skill.py`、`stats.py` — Buff 管理器（`BuffDuration`/`StackRule` 枚举）、战技点、技能与倍率、属性叠加。

- **`src/ui/`** — PySide6 界面：
  - `battle_simulator.py` — 1434 行的主窗口（`BattleSimulatorWindow`），侧栏 + 6 个 Tab（配置/交互/日志/时间轴/伤害占比/汇总）。内置 `make_preset_character()` 构造预设角色，未接入真实数据下拉。
  - `theme.py` — 深色 QSS（`DARK_STYLE`）与颜色常量（`Colors`、`ELEMENT_COLORS`、`PATH_COLORS`），样式集中于此，不在控件里硬编码。
  - `widgets/` — 复用控件：`character_picker`（含图标下载）、`timeline_gantt`（甘特图）、`damage_pie`、`sp_indicator`、`energy_orb`。

- **`tests/`** — pytest；`conftest.py` 提供 `tests/fixtures/*.json`（nanoka 原始数据）作为 fixtures，API 测试不打真实网络。

- **`verify_api.py`** — 手动验证脚本：拉取 manifest → 列表/详情 → 提纯 → 图标 URL 可访问性。

## 欢愉（阿哈）机制

模拟器中特有的机制：`Elation` 命途角色持有"笑点"（laugh_point）；笑点 > 0 时"阿哈"（`__aha__`）入行动队列；阿哈行动时触发"阿哈时刻"：所有欢愉角色按 `elation_skill_index` 顺序释放欢愉技 → 清空笑点 → 好活当赏（buff，name="好活当赏"）+= 本次笑点数 → 笑点重置为欢愉角色数。好活当赏以独立 buff 形式累加（`_sum_good_joke()`）。

## 数据源与缓存

- 数据源：`static.nanoka.cc`，版本走 `manifest.json` 的 `hsr.latest` 字段；列表/详情 URL 模式见 `consts.py`。
- diskcache 单例路径 `./cache`（已 gitignore），TTL：manifest 1h / 列表 10min / 详情 1h。
- 伤害公式必须用游戏内实测数据校准（`技术规范.md` 5.4），改动 `damage.py` 前先看该节。

## 文档与实际的差异（重要）

`docs/开发文档.md` 与 `docs/技术规范.md` 是**规划性文档**，其中不少文件结构与类名（如 `main_window.py`、`lightcone_picker.py`、`team_editor.py`、`src/data/`、`src/app.py`）**尚未实现**。实际代码以 `src/` 下现有文件为准。技术规范中的错误分层策略、日志规范（loguru）、测试命名约定（`test_<函数>_<场景>_<预期>`、Arrange-Act-Assert）是有效的。

## 其他

请记住：如果在开发过程中对游戏机制有任何不清楚的地方，都应当立即向用户提问