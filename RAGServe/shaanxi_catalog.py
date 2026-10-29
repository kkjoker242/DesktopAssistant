"""Reviewable first-pass catalogue for Shaanxi's well-known attractions.

City names omit the administrative suffix, matching the existing Xi'an records.
Yangling is a demonstration zone and is represented as a separate locality.
"""

REGION = "陕西省"

# id: (city, canonical name, specific aliases)
ATTRACTIONS = {
    "terracotta_army": ("西安", "秦始皇帝陵博物院", ("秦始皇帝陵博物院", "兵马俑")),
    "city_wall": ("西安", "西安城墙", ("西安城墙", "西安明城墙")),
    "big_wild_goose_pagoda": ("西安", "大雁塔", ("大雁塔",)),
    "bell_tower": ("西安", "西安钟楼", ("西安钟楼",)),
    "drum_tower": ("西安", "西安鼓楼", ("西安鼓楼",)),
    "huaqing_palace": ("西安", "华清宫", ("华清宫", "华清池")),
    "tang_paradise": ("西安", "大唐芙蓉园", ("大唐芙蓉园",)),
    "shaanxi_history_museum": ("西安", "陕西历史博物馆", ("陕西历史博物馆", "陕历博")),
    "famen_temple": ("宝鸡", "法门寺文化景区", ("法门寺文化景区", "法门寺")),
    "taibai_mountain": ("宝鸡", "太白山", ("太白山",)),
    "qianling": ("咸阳", "乾陵", ("乾陵",)),
    "yuanjia_village": ("咸阳", "袁家村", ("袁家村",)),
    "zhaojin": ("铜川", "照金革命纪念地", ("照金革命纪念地", "照金革命根据地")),
    "yaowang_mountain": ("铜川", "药王山", ("药王山",)),
    "huashan": ("渭南", "华山", ("华山景区", "西岳华山")),
    "huangdi_mausoleum": ("延安", "黄帝陵", ("黄帝陵",)),
    "yanan_revolution_museum": ("延安", "延安革命纪念馆", ("延安革命纪念馆",)),
    "hongshi_gorge": ("榆林", "红石峡", ("榆林红石峡", "红石峡")),
    "qingmuchuan": ("汉中", "青木川古镇", ("青木川古镇",)),
    "yinghu": ("安康", "瀛湖", ("瀛湖景区", "瀛湖")),
    "jinsixia": ("商洛", "金丝峡", ("金丝峡", "金丝大峡谷")),
    "yangling_agroforestry_museum": ("杨凌", "杨凌农林博物院", ("杨凌农林博物院",)),
}

CITIES = {city for city, _, _ in ATTRACTIONS.values()}
NAME_TO_ID = {(city, name): key for key, (city, name, _) in ATTRACTIONS.items()}


def resolve_attraction(city: str, name: str) -> tuple[str, str]:
    try:
        attraction_id = NAME_TO_ID[(city, name)]
    except KeyError as exc:
        raise ValueError(f"Unknown 陕西省/{city} attraction_name: {name}") from exc
    return attraction_id, name
