"""遗器套装模块注册表。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import RelicSetModule

_REGISTRY: dict[str, type[RelicSetModule]] = {}


def register(module_cls: type[RelicSetModule]) -> type[RelicSetModule]:
    _REGISTRY[module_cls.CHAR_ID] = module_cls
    return module_cls


def get_module_cls(set_id: str) -> type[RelicSetModule] | None:
    return _REGISTRY.get(set_id)


from . import eagle_110  # noqa: E402, F401
from . import duke_115  # noqa: E402, F401
from . import smith_132  # noqa: E402, F401
from . import vonwacq_308  # noqa: E402, F401
from . import bone_319  # noqa: E402, F401
from . import city_326  # noqa: E402, F401
