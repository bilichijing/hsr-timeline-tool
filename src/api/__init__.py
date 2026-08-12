"""API 数据层：从 nanoka.cc 获取星铁数据。"""

from src.api.client import (
    fetch_character_detail,
    fetch_character_list,
    fetch_latest_version,
    fetch_lightcone_detail,
    fetch_lightcone_list,
    fetch_relicset_detail,
    fetch_relicset_list,
)
from src.api.consts import (
    ASSET_BASE,
    DATA_BASE,
    ELEMENT_MAP,
    NANOKA_BASE,
    PATH_MAP,
    RARITY_MAP,
    character_fullart_url,
    character_icon_url,
    lightcone_icon_url,
    monster_icon_url,
    relicset_icon_url,
)
from src.api.models import (
    Character,
    CharacterInfo,
    Lightcone,
    LightconeInfo,
    RelicSet,
    RelicSetInfo,
)
from src.api.transforms import (
    transform_character_detail,
    transform_character_list,
    transform_lightcone_detail,
    transform_lightcone_list,
    transform_relicset_detail,
    transform_relicset_list,
)

__all__ = [
    # 常量
    "NANOKA_BASE",
    "DATA_BASE",
    "ASSET_BASE",
    "RARITY_MAP",
    "PATH_MAP",
    "ELEMENT_MAP",
    # 图标 URL
    "character_icon_url",
    "character_fullart_url",
    "lightcone_icon_url",
    "relicset_icon_url",
    "monster_icon_url",
    # 客户端
    "fetch_latest_version",
    "fetch_character_list",
    "fetch_character_detail",
    "fetch_lightcone_list",
    "fetch_lightcone_detail",
    "fetch_relicset_list",
    "fetch_relicset_detail",
    # 模型
    "Character",
    "CharacterInfo",
    "Lightcone",
    "LightconeInfo",
    "RelicSet",
    "RelicSetInfo",
    # 提纯
    "transform_character_list",
    "transform_character_detail",
    "transform_lightcone_list",
    "transform_lightcone_detail",
    "transform_relicset_list",
    "transform_relicset_detail",
]
