# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

崩坏：星穹铁道 排轴与伤害计算工具（桌面应用，PySide6 + Python ≥3.10）。数据源为 nanoka（`static.nanoka.cc`），核心是 AV 行动值系统与战斗模拟引擎。所有 UI 文本、代码注释、文档均为中文，新代码应保持一致。

## 常用命令

```bash
# 运行 GUI（入口，10 行，实际逻辑在 src/ui/battle_simulator.py 的 main()）
python ui_main.py

# 运行测试（当前 407 个用例：403 通过 + test_freesr.py 中 4 个受数据文件影响）
python -m pytest                                         # 全部
python -m pytest tests/test_av_system.py                 # 单个文件
python -m pytest tests/test_av_system.py -k "next_actor" # 单测
python -m pytest -q -W ignore::pytest.PytestConfigWarning # 忽略 asyncio_mode 警告

# Lint / 格式化（ruff 已在 pyproject.toml 配置：line-length=100，select E/F/W/I/UP/B/SIM）
ruff check .
ruff format .

# 实测 API 数据通路（打真实网络，带 diskcache）
python verify_api.py
```

注意：
- `pyproject.toml` 的 `asyncio_mode = "auto"` 需要 pytest-asyncio，**当前环境未安装**（会告警但测试照常通过）；`ruff` 同样未安装。
- `tests/test_freesr.py` 直接读取**仓库根目录的 `freesr-data.json`**，并断言不死途（1504）的星魂 / 能量 / 遗器数值。替换该文件（换角色或换配装）后其中 4 个用例会失败，需同步期望值。
- 测试全部使用 `tests/fixtures/*.json`（nanoka 原始数据），不打真实网络。

## 架构

分层结构，依赖方向：`ui → core`、`ui → api`，`core` 与 `api` 互不依赖。

- **`src/api/`** — 数据层，全部指向 nanoka：
  - `consts.py` — 基址常量（`NANOKA_BASE`/`DATA_BASE`/`ASSET_BASE`/`MANIFEST_URL`）、枚举映射（`RARITY_MAP`/`PATH_MAP`/`ELEMENT_MAP`）、图标 URL 构造（纯函数）、`CacheTTL`。
  - `client.py` — httpx 异步单例 + diskcache 模块级缓存单例（`./cache` 目录）。所有网络请求必须经过此模块；请求失败时回退过期缓存。另提供**共享 asyncio 事件循环**（`run_in_loop()`），UI 工作线程通过它提交协程，避免"每线程新建 loop 导致 client 绑定的循环已关闭"。
  - `models.py` / `transforms.py` — pydantic 模型与"nanoka 原始结构 → 业务模型"的提纯函数（纯函数，无 IO）；`clean_text()` 负责去富文本标签与 `#1[i]` 占位符替换。

- **`src/core/`** — 业务核心，**不得导入任何 PySide6 代码**，可独立测试：
  - `av_system.py` — 行动值系统。`AV_PER_ACTION = 10000.0`；`ActionQueue.advance()` **不接受参数**，返回 `(行动者, 消耗 AV)` 并重置行动者 AV；`apply_push(id, rate)` / `apply_pull(id, rate)`；`update_speed(id, new_speed, advance_rate=0, delay_rate=0)` 按官方换速公式调整剩余 AV。`unit_id` 是字符串（`"enemy1"`、`"__aha__"`、`"__countdown_<uid>__"`、`"__enemy_attack_N__"`）。
  - `simulator.py` — 战斗模拟引擎（约 1774 行）。`setup()` 必须先调；`run(actions)` 一次性跑完（到 `max_av` 默认 300）；`step(action)` 交互步进；`advance_av()` 交互模式手动推进时间（幂等，用 `pending_av_actor` 去重）；`execute_ultra(char_index)` 终结技插队（不推进队列、不消耗回合）；`snapshot()`/`restore()` 快照回溯。setup 顺序：**光锥模块 → 遗器模块 → 角色模块**，最后用最终速度重算初始 AV（保留战前拉条比例）。
  - `damage.py` — 伤害公式 `calculate_damage(DamageContext)`；`DamageType` 六类：`NORMAL`/`BREAK`/`SUPER_BREAK`/`DOT`/`ELATION`/`TRUE`；另有 `build_enemy_resistance()`、`calc_resistance/calc_defense/calc_damage_reduction/calc_crit_zone/calc_crit_expectation/calc_laugh_zone` 等分乘区函数。
  - `stats.py` — `BaseStats` / `StatBonus` / `FinalStats` / `StatCalculator.final()`。注意最终字段名是 `defense`（不是 `def_`），并有 `res_pen`、`elemental_dmg_bonus`、`follow_up_dmg_bonus`、`follow_up_crit_dmg_bonus`、`laugh_point`/`good_joke`/`elation_dmg`/`laugh_bonus`。
  - `buff.py` — `BuffDuration`（`PERMANENT`/`TURNS_SELF_START`/`TURNS_SELF_END`/`NEXT_ATTACK`/`ONCE`）、`StackRule`（`NO_STACK_SAME_NAME`/`NO_STACK_SAME_SOURCE`/`STACK_LIMIT_N`/`STACK_ALWAYS`）、`BuffManager`（`add`/`remove`/`remove_by_name`/`remove_debuffs`/`tick_turn_start`/`tick_turn_end`/`tick_attack`/`total_bonus`/`get_value`）。
  - `skill.py` — `SkillType` 八种（`NORMAL`/`SKILL`/`ULTRA`/`TALENT`/`TECHNIQUE`/`MEMO_DNSKILL`/`FOLLOW_UP`/`ADDED`）、`parse_all_skills()`、`get_skill_by_type()`；`bp_need=-1` 语义见下文。
  - `sp.py` — 战技点（`MAX=5`、`INITIAL=3`、`consume`/`recover`/`can_consume`）。
  - `eidolon.py` — 星魂参数读取（`parse_eidolons`/`get_rank_param`/`has_rank`/`rank_skill_level_bonuses`）。
  - `character_factory.py` — `build_character_unit(...)` 把 nanoka 详情 + freesr 数据装配成 `CharacterUnit`；`convert_stats80()`、`extract_trace_bonuses()`。
  - `freesr.py` — `parse_freesr()`、`parse_relic()`、`calc_sub_affix()`、`calc_relic_bonus()`、`compute_panel()` / `compute_panel_breakdown()`、`apply_lightcone_panel_bonus()`（光锥第一句常驻面板加成）。
  - `characters/`、`lightcones/`、`relics/` — 三类**效果模块**（见下节）。

- **`src/ui/`** — PySide6 界面：
  - `battle_simulator.py` — 约 3498 行的主窗口（`BattleSimulatorWindow(QMainWindow)`），侧栏 + **7 个 Tab**（配置 / 交互模拟 / 行动日志 / AV 时间轴 / 伤害占比 / 伤害明细 / 汇总）。已接入 nanoka 真实角色列表（`CharacterPickerDialog`）；`make_preset_character()`（模块级函数）是真实数据未就绪时的回退路径。队伍配置存 `./cache/team_config.json`（version 4）。
  - `theme.py` — 深色 QSS（`DARK_STYLE`）与颜色常量（`Colors`、`ELEMENT_COLORS`、`PATH_COLORS`），样式集中于此，不在控件里硬编码。
  - `widgets/` — 复用控件：`character_picker`（真实角色选择器，含图标下载）、`timeline_gantt`（甘特图）、`damage_pie`、`sp_indicator`、`energy_orb`、`enemy_target`。

- **`tests/`** — pytest（扁平结构 `tests/test_*.py`）；`conftest.py` 提供 `tests/fixtures/*.json`（角色 / 光锥 / 遗器列表与详情、怪物列表）作为 fixtures。

- **`verify_api.py`** — 手动验证脚本：拉取 manifest → 列表/详情 → 提纯 → 图标 URL 可访问性 → 缓存命中。

## 效果模块体系（重要扩展点）

三类模块结构同构：注册表 + `@register` 装饰器 + 事件钩子，模拟器用 `getattr` 分发（未实现的钩子即跳过）。**新角色 / 光锥 / 遗器效果只需新增模块文件，不改模拟器核心。**

- `src/core/characters/` — `CharacterModule`（`CHAR_ID` = nanoka 角色 ID）。已实现：不死途 1504（巡猎/雷）、缇宝 1403（同谐/量子）、千冶•刃 1507（虚无/火）、风堇 1409（记忆/风）。
- `src/core/lightcones/` — `LightconeModule`。已实现 23056 / 23059 / 23038 / 23042；**第一句常驻加成不在模块里**（走 `freesr.apply_lightcone_panel_bonus` 计入面板绿字，战斗内不重复挂载）。
- `src/core/relics/` — `RelicSetModule`（`CHAR_ID` = SET_ID）。已实现 110 / 115 / 125 / 132 / 308 / 319 / 320 / 326；实例化时件数 `< 2` 的套装跳过，2 件 / 4 件由模块内部自判。

**约定**：模块状态字段必须是纯数据（str/int/float/list），不持有 sim/char 引用（`snapshot()` 用 deepcopy）；技能参数用 `module_params(skill, N, default)` 读取（`#N → params[N-1]`），数据缺失时 no-op 并在 `log.notes` 标注。

**钩子（`characters/base.py`；光锥 / 遗器基类为其子集）**：

| 钩子 | 时机 / 用途 |
|---|---|
| `on_battle_start_setup(sim, char)` | 战斗开始·第一阶段：全队光环 / 常驻 buff / 治疗 / 能量 |
| `on_battle_start(sim, char)` | 第二阶段：进战动作（秘技伤害等） |
| `on_turn_start` / `on_turn_end` | 角色回合开始 / 结束（buff tick 之后分发） |
| `on_resolve_skill(sim, char, skill_type, skill)` | **替换**技能（返回新 Skill）或**拒绝**施放（返回 None，回合照常消耗）；返回原对象 = 不参与 |
| `on_skill_cast` | 伤害结算前：标记目标、消耗生命、清空无伤害技能的误解析 effects |
| `on_attack_hit(..., action_token)` | 每次命中后（削韧 / 击破结算后）：天赋触发等 |
| `on_skill_end` | 本行动日志入列后：追加伤害段、终结技追击链 |
| `on_post_skill` | 所有模块 `on_skill_end` 与追击链之后：行动完全结束时才结算的效果 |
| `on_countdown` | 行动条倒计时（如无量忿怒结界解除） |
| `on_enemy_act` / `on_enemy_dead` | 敌方行动计时 / 敌人死亡清理引用 |
| `on_incoming_damage` / `on_damage_taken` | 我方受击减免 / 受击后（千锻魂、星魂） |
| `on_heal`（仅遗器）、`on_memo_skill_end`（仅光锥）、`enemy_buffs`、`skill_deny_reason` | 治疗结算 / 忆灵技结算 / 敌方 debuff 展示 / 战技被拒原因 |

**行动令牌**：`sim.action_token` 每次技能施放（`_resolve_skill`）递增；一次行动的主伤害与追击链共享同一令牌，模块可用 `sim.begin_new_action()` 主动开启新行动。`on_attack_hit` 分发时传入**冻结令牌**（`hit_token` / `sim.frozen_action_token`）——按"行动"去重必须用它，读 `sim.action_token` 会在连锁（T→T+1→T+2）时误判。

**模块可用 API**：`deal_damage(...)`（含 `secondary_skill_type`；`is_attack=False` 表示"附加伤害 ≠ 攻击"，不触发 `on_attack_hit` 与 NEXT_ATTACK tick；`stats` 传命中时面板快照）、`deal_true_damage`、`heal`、`recover_energy(char, amount, fixed=)`、`make_follow_up_log`、`random_enemy()`（固定种子，多敌人随机目标可复现）、`add_countdown(owner, speed=, name=)`、`is_auto_unit(actor)`。

## 技能解析细节

- `bp_need=-1` 语义：普攻 = 回复（数量 `bp_add`）；**非普攻 = 不消耗**（如千冶战技"不消耗战技点"、终结技不回复 SP）。
- 生命倍率伤害：模块在 `on_skill_cast` 把 `effects[0].base_stat` 改为 `"hp"`（parse 默认 atk）；无伤害技能需清空 `effects` 防误伤。
- `DamageRecord`：`skill_type` × `damage_type` 双维度，`secondary_skill_type` 标注第二种技能类型（如千冶天赋触发的战技 = `FOLLOW_UP` + `SKILL`）。
- 技能无效行动（`on_resolve_skill` 返回 None）：回合照常消耗，写"无法施放（技能受限）"日志（与战斗结束区分，UI 不误判）。

## 欢愉（阿哈）机制

`Elation` 命途角色持有"笑点"（`laugh_point`）；笑点 > 0 时"阿哈"（`__aha__`）入行动队列，速度 = `80 + ∑(欢愉角色速度 / 5, 10, 20, 50)`（按速度降序取前 4）。阿哈行动触发"阿哈时刻"：所有欢愉角色按 `elation_skill_index` 顺序释放欢愉技 → 清空笑点 → 好活当赏（`name="好活当赏"` 的独立 buff，`TURNS_SELF_END` 2 回合）+= 本次笑点数 → 笑点重置为欢愉角色数。战斗开始时欢愉角色获得 20 点永久好活当赏。好活当赏以独立 buff 累加（`_sum_good_joke()`），非欢愉命途角色无法获得。

## 数据源与缓存

- 数据源：`static.nanoka.cc`，版本走 `manifest.json` 的 `hsr.latest` 字段；列表/详情 URL 模式见 `consts.py`。
- diskcache 单例路径 `./cache`（已 gitignore），TTL：manifest 1h / 列表 10min / 详情 1h。
- 列表 JSON **已包含 `zh`/`ko`/`ja`/`desc` 字段**（中文名无需两级查询）；详情含 `skills`/`skill_trees`/`ranks`/`stats`/`memosprite`。
- 伤害公式必须用游戏内实测数据校准（`docs/技术规范.md` 5.4），改动 `damage.py` 前先看 `docs/开发文档.md` 第 6.4 节。
- 命途映射以 `consts.PATH_MAP` 为准：`Knight`=存护、`Warrior`=毁灭、`Rogue`=巡猎、`Mage`=智识、`Warlock`=虚无、`Shaman`=同谐、`Priest`=丰饶、`Memory`=记忆、`Elation`=欢愉（`tests/test_enum_completeness.py` 会自检映射完整性）。

## 其他

- 请记住：如果在开发过程中对游戏机制有任何不清楚的地方，都应当立即向用户提问。
- 文档：`README.md`（面向使用者）、`docs/开发文档.md`（设计）、`docs/技术规范.md`（接口与约定）。新增角色 / 装备模块时，请同步更新这三份文档中的清单与机制小节。
