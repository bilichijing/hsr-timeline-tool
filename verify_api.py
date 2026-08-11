"""验证脚本：实测 API 数据通路。

运行方式：
    uv run python verify_api.py
或：
    python verify_api.py

验证内容：
1. manifest 拉取与版本解析
2. 角色列表拉取与提纯
3. 角色详情拉取与提纯（含技能/星魂/属性）
4. 光锥列表 + 详情
5. 遗器套装列表 + 详情
6. 怪物列表
7. 图标 URL 可访问性
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# 把 src 加入 path（未安装为包时）
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.api import client
from src.api.consts import (
    ELEMENT_MAP,
    PATH_MAP,
    character_icon_url,
    lightcone_icon_url,
    monster_icon_url,
    relicset_icon_url,
)
from src.api.transforms import (
    transform_character_detail,
    transform_character_list,
    transform_lightcone_detail,
    transform_lightcone_list,
    transform_monster_list,
    transform_relicset_detail,
    transform_relicset_list,
)


def print_section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def print_ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def print_fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


async def main() -> None:
    # ── 1. 版本管理 ────────────────────────────────────────
    print_section("1. Manifest 与版本管理")
    try:
        version = await client.fetch_latest_version()
        print_ok(f"最新版本: {version}")

        versions = await client.fetch_available_versions()
        print_ok(f"可用版本数: {len(versions)}")
    except Exception as e:
        print_fail(f"版本获取失败: {e}")
        return

    # ── 2. 角色列表 ────────────────────────────────────────
    print_section("2. 角色列表")
    try:
        raw_list = await client.fetch_character_list()
        print_ok(f"原始列表条目数: {len(raw_list)}")

        characters = transform_character_list(raw_list)
        print_ok(f"提纯后角色数: {len(characters)}")

        # 抽查三月七
        march7th = next(c for c in characters if c.id == "1001")
        print_ok(f"抽查 1001: {march7th.name_zh} | {march7th.rarity}星 | "
                 f"{PATH_MAP.get(march7th.path, '?')} | {ELEMENT_MAP.get(march7th.element, '?')}")
        print_ok(f"  图标 URL: {march7th.icon_url}")
    except Exception as e:
        print_fail(f"角色列表失败: {e}")

    # ── 3. 角色详情 ────────────────────────────────────────
    print_section("3. 角色详情（1001 三月七）")
    try:
        raw_detail = await client.fetch_character_detail("1001")
        print_ok(f"原始详情字段: {len(raw_detail)} 个")

        info = transform_character_detail(raw_detail, "1001")
        print_ok(f"名称: {info.name}")
        print_ok(f"属性: {info.rarity}星 / {PATH_MAP.get(info.path, '?')} / {ELEMENT_MAP.get(info.element, '?')}")
        print_ok(f"能量需求: {info.sp_need}")
        print_ok(f"属性表等级数: {len(info.stats)}")
        print_ok(f"技能数: {len(info.skills)}")
        print_ok(f"星魂数: {len(info.ranks)}")

        # 抽查 0 级属性
        if "0" in info.stats:
            s = info.stats["0"]
            print_ok(f"0级属性: ATK={s.attack_base} HP={s.hp_base} DEF={s.defence_base} SPD={s.speed_base}")

        # 抽查普攻技能
        if "100101" in info.skills:
            skill = info.skills["100101"]
            print_ok(f"普攻: {skill['name']} ({skill.get('type_name', '?')})")
            if "1" in skill.get("level", {}):
                print_ok(f"  1级倍率参数: {skill['level']['1']['param_list']}")
    except Exception as e:
        print_fail(f"角色详情失败: {e}")

    # ── 4. 光锥 ────────────────────────────────────────────
    print_section("4. 光锥列表 + 详情")
    try:
        raw_lc_list = await client.fetch_lightcone_list()
        lightcones = transform_lightcone_list(raw_lc_list)
        print_ok(f"光锥数: {len(lightcones)}")

        lc = next(l for l in lightcones if l.id == "20000")
        print_ok(f"抽查 20000: {lc.name_zh} | {lc.rarity}星 | ATK={lc.atk}")

        raw_lc_detail = await client.fetch_lightcone_detail("20000")
        lc_info = transform_lightcone_detail(raw_lc_detail, "20000")
        print_ok(f"叠影名: {lc_info.refinement.name if lc_info.refinement else '无'}")
        if lc_info.refinement:
            print_ok(f"叠影1级参数: {lc_info.refinement.levels.get('1', [])}")
    except Exception as e:
        print_fail(f"光锥失败: {e}")

    # ── 5. 遗器套装 ────────────────────────────────────────
    print_section("5. 遗器套装列表 + 详情")
    try:
        raw_rs_list = await client.fetch_relicset_list()
        relicsets = transform_relicset_list(raw_rs_list)
        print_ok(f"套装数: {len(relicsets)}")

        rs = next(r for r in relicsets if r.id == "101")
        print_ok(f"抽查 101: {rs.name_zh}")
        if rs.bonus_2pc:
            print_ok(f"  2件套: {rs.bonus_2pc.desc}")
        if rs.bonus_4pc:
            print_ok(f"  4件套: {rs.bonus_4pc.desc}")

        raw_rs_detail = await client.fetch_relicset_detail("101")
        rs_info = transform_relicset_detail(raw_rs_detail, "101")
        print_ok(f"套装件数: {len(rs_info.parts)}")
    except Exception as e:
        print_fail(f"遗器套装失败: {e}")

    # ── 6. 怪物列表 ────────────────────────────────────────
    print_section("6. 怪物列表")
    try:
        raw_mon_list = await client.fetch_monster_list()
        monsters = transform_monster_list(raw_mon_list)
        print_ok(f"怪物数: {len(monsters)}")

        mon = next(m for m in monsters if m.id == "1002011")
        print_ok(f"抽查 1002011: {mon.name_zh} | 弱点: {mon.weaknesses}")
    except Exception as e:
        print_fail(f"怪物列表失败: {e}")

    # ── 7. 图标 URL 可访问性 ───────────────────────────────
    print_section("7. 图标 URL 可访问性")
    import httpx

    icon_urls = [
        ("角色", character_icon_url("1001")),
        ("光锥", lightcone_icon_url("20000")),
        ("遗器", relicset_icon_url("SpriteOutput/ItemIcon/71000.png")),
        ("怪物", monster_icon_url("SpriteOutput/MonsterFigure/Monster_1002011.png")),
    ]
    async with httpx.AsyncClient() as http_client:
        for name, url in icon_urls:
            try:
                r = await http_client.head(url, timeout=10.0)
                if r.status_code == 200:
                    print_ok(f"{name}: {url}")
                else:
                    print_fail(f"{name} [{r.status_code}]: {url}")
            except Exception as e:
                print_fail(f"{name}: {e}")

    # ── 8. 缓存验证 ────────────────────────────────────────
    print_section("8. 缓存命中验证")
    try:
        import time

        t1 = time.perf_counter()
        await client.fetch_character_list()
        t2 = time.perf_counter()
        elapsed_ms = (t2 - t1) * 1000
        if elapsed_ms < 50:
            print_ok(f"第二次请求耗时: {elapsed_ms:.1f}ms (< 50ms 缓存命中)")
        else:
            print_fail(f"第二次请求耗时: {elapsed_ms:.1f}ms (>= 50ms 可能未命中缓存)")
    except Exception as e:
        print_fail(f"缓存验证失败: {e}")

    print_section("验证完成")
    await client.close_client()


if __name__ == "__main__":
    asyncio.run(main())
