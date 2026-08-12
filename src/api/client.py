"""HTTP 客户端 + diskcache 封装。

所有对 nanoka 的请求必须经过此模块，自动带磁盘缓存。
本地桌面应用无 CORS 限制，直接请求 static.nanoka.cc。
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

import diskcache
import httpx
from loguru import logger

from src.api.consts import ASSET_BASE, CacheTTL, DATA_BASE, MANIFEST_URL

# ── 缓存实例（模块级单例）──────────────────────────────────
# 路径相对于工作目录，运行时自动创建
CACHE_DIR = Path("./cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)
cache: diskcache.Cache = diskcache.Cache(str(CACHE_DIR))


# ── 共享事件循环 ───────────────────────────────────────────
# 应用级单线程 asyncio 循环（daemon，进程退出自动结束）。
# httpx 全局单例 client 绑定该循环——各 worker 线程通过 run_in_loop 提交协程，
# 避免"每线程 new loop + close 导致 client 绑定的循环已关闭"（Event loop is closed）。

_LOOP: asyncio.AbstractEventLoop | None = None
_LOOP_THREAD: threading.Thread | None = None
_LOOP_LOCK = threading.Lock()


def _ensure_loop() -> asyncio.AbstractEventLoop:
    """懒启动共享事件循环（永不关闭）。"""
    global _LOOP, _LOOP_THREAD
    if _LOOP is None or _LOOP.is_closed():
        with _LOOP_LOCK:
            if _LOOP is None or _LOOP.is_closed():
                _LOOP = asyncio.new_event_loop()
                _LOOP_THREAD = threading.Thread(
                    target=_LOOP.run_forever,
                    daemon=True,
                    name="hsr-asyncio",
                )
                _LOOP_THREAD.start()
    return _LOOP


def run_in_loop(coro) -> Any:
    """在共享事件循环上运行协程并等待结果（工作线程调用）。"""
    loop = _ensure_loop()
    return asyncio.run_coroutine_threadsafe(coro, loop).result()


# ── 异步客户端单例 ─────────────────────────────────────────

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    """获取全局 httpx 异步客户端单例（绑定共享事件循环）。"""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            headers={"User-Agent": "hsr-timeline-tool/0.1"},
            follow_redirects=True,
        )
    return _client


async def close_client() -> None:
    """关闭 HTTP 客户端（应用退出时调用）。"""
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
        _client = None


# ── 通用请求函数 ───────────────────────────────────────────


async def fetch_json(
    url: str,
    *,
    expire: int = CacheTTL.LIST,
    use_cache: bool = True,
) -> dict | list:
    """拉取 JSON 数据，带磁盘缓存。

    缓存未命中或过期时发真实请求；请求失败时尝试回退到过期缓存。
    """
    if use_cache:
        cached = cache.get(url)
        if cached is not None:
            logger.debug("缓存命中: {}", url)
            return cached

    client = get_client()
    try:
        r = await client.get(url)
        r.raise_for_status()
        data = r.json()
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        # 网络失败：尝试过期缓存兜底
        stale = cache.get(url, expired=True)
        if stale is not None:
            logger.warning("网络失败，使用过期缓存: {} | {}", url, e)
            return stale
        logger.error("请求失败且无缓存: {} | {}", url, e)
        raise
    except ValueError as e:
        logger.error("JSON 解析失败: {} | {}", url, e)
        raise

    if use_cache:
        cache.set(url, data, expire=expire)
    return data


# ── 版本管理 ───────────────────────────────────────────────


async def fetch_manifest() -> dict:
    """获取完整 manifest。"""
    return await fetch_json(MANIFEST_URL, expire=CacheTTL.VERSION)


async def fetch_latest_version() -> str:
    """获取星铁最新数据版本号。"""
    manifest = await fetch_manifest()
    version = manifest.get("hsr", {}).get("latest")
    if not version:
        raise ValueError("manifest 中未找到 hsr.latest 字段")
    return version


async def fetch_available_versions() -> list[str]:
    """获取所有可用版本。"""
    manifest = await fetch_manifest()
    return manifest.get("hsr", {}).get("available", [])


# ── 列表数据 ───────────────────────────────────────────────


async def fetch_character_list() -> dict[str, dict]:
    """角色列表 {id: {en, zh, rank, baseType, damageType, ...}}。"""
    version = await fetch_latest_version()
    url = f"{DATA_BASE}/{version}/character.json"
    return await fetch_json(url, expire=CacheTTL.LIST)


async def fetch_lightcone_list() -> dict[str, dict]:
    """光锥列表 {id: {en, zh, rank, baseType, atk, ...}}。"""
    version = await fetch_latest_version()
    url = f"{DATA_BASE}/{version}/lightcone.json"
    return await fetch_json(url, expire=CacheTTL.LIST)


async def fetch_relicset_list() -> dict[str, dict]:
    """遗器套装列表 {id: {en, zh, icon, set, ...}}。"""
    version = await fetch_latest_version()
    url = f"{DATA_BASE}/{version}/relicset.json"
    return await fetch_json(url, expire=CacheTTL.LIST)


async def fetch_monster_list() -> dict[str, dict]:
    """怪物列表 {id: {en, zh, icon, weak, rank, ...}}。"""
    version = await fetch_latest_version()
    url = f"{DATA_BASE}/{version}/monster.json"
    return await fetch_json(url, expire=CacheTTL.LIST)


# ── 详情数据 ───────────────────────────────────────────────


async def fetch_character_detail(char_id: str | int) -> dict:
    """角色详情（zh 版本，含技能/星魂/属性）。"""
    version = await fetch_latest_version()
    url = f"{DATA_BASE}/{version}/zh/character/{char_id}.json"
    return await fetch_json(url, expire=CacheTTL.DETAIL)


async def fetch_lightcone_detail(lightcone_id: str | int) -> dict:
    """光锥详情（含叠影效果、属性表）。"""
    version = await fetch_latest_version()
    url = f"{DATA_BASE}/{version}/zh/lightcone/{lightcone_id}.json"
    return await fetch_json(url, expire=CacheTTL.DETAIL)


async def fetch_relicset_detail(relicset_id: str | int) -> dict:
    """遗器套装详情（含单件故事、套装效果）。"""
    version = await fetch_latest_version()
    url = f"{DATA_BASE}/{version}/zh/relicset/{relicset_id}.json"
    return await fetch_json(url, expire=CacheTTL.DETAIL)


# ── 图标下载 ───────────────────────────────────────────────


async def download_icon(url: str, save_to: Path) -> Path:
    """下载图标到本地文件（不缓存，直接写磁盘）。

    已存在则跳过。
    """
    if save_to.exists():
        return save_to

    save_to.parent.mkdir(parents=True, exist_ok=True)
    client = get_client()
    try:
        r = await client.get(url)
        r.raise_for_status()
        save_to.write_bytes(r.content)
        logger.debug("图标已下载: {}", save_to.name)
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        logger.error("图标下载失败: {} | {}", url, e)
        raise
    return save_to


async def download_character_icon(char_id: str | int, save_dir: Path) -> Path:
    """下载角色头像到指定目录。"""
    from src.api.consts import character_icon_url

    url = character_icon_url(char_id)
    return await download_icon(url, save_dir / f"character_{char_id}.webp")


async def download_lightcone_icon(lightcone_id: str | int, save_dir: Path) -> Path:
    """下载光锥图标到指定目录。"""
    from src.api.consts import lightcone_icon_url

    url = lightcone_icon_url(lightcone_id)
    return await download_icon(url, save_dir / f"lightcone_{lightcone_id}.webp")
