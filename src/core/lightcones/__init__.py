"""光锥模块注册表。

按光锥 nanoka ID 注册 LightconeModule 子类；模拟器 setup() 时按
CharacterUnit.lightcone_id 实例化。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import LightconeModule

_REGISTRY: dict[str, type[LightconeModule]] = {}


def register(module_cls: type[LightconeModule]) -> type[LightconeModule]:
    _REGISTRY[module_cls.CHAR_ID] = module_cls
    return module_cls


def get_module_cls(lightcone_id: str) -> type[LightconeModule] | None:
    return _REGISTRY.get(lightcone_id)


# 导入子模块触发注册
from . import lie_23056  # noqa: E402, F401
from . import blaze_23059  # noqa: E402, F401
from . import flower_23038  # noqa: E402, F401
