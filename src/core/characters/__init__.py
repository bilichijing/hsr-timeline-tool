"""角色技能模块注册表。

注册方式：char_id（nanoka 角色 ID）→ 模块类。
模拟器 setup() 时按 CharacterUnit.char_id 查表实例化模块。

用法：
    @register
    class AshveilModule(CharacterModule):
        CHAR_ID = "1504"
        ...
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import CharacterModule

# 注册表：nanoka 角色 ID → 模块类
_REGISTRY: dict[str, type[CharacterModule]] = {}


def register(module_cls: type[CharacterModule]) -> type[CharacterModule]:
    """类装饰器：以 module_cls.CHAR_ID 注册角色模块。"""
    _REGISTRY[module_cls.CHAR_ID] = module_cls
    return module_cls


def get_module_cls(char_id: str) -> type[CharacterModule] | None:
    """按 nanoka 角色 ID 查模块类（未注册返回 None）。"""
    return _REGISTRY.get(char_id)


# 导入子模块触发注册（放在注册函数之后）
from . import ashveil  # noqa: E402, F401
from .ashveil import AshveilModule  # noqa: E402
