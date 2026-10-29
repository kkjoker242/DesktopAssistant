"""Expose the sample travel planner through the desktop MCP server."""

from __future__ import annotations

import asyncio
from typing import Literal

import mcp.types as types
from pydantic import BaseModel, ConfigDict, Field

from .data_preparation import DataPreparationModule
from .generation_integration import GenerationIntegrationModule
from .index_construction import IndexConstructionModule
from .retrieval_optimization import RetrievalOptimizationModule
from .travel_services import AMapAdapter, forecast_from_weather_mcp

class TripInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(min_length=1, max_length=500, description="中文旅行需求与景点偏好")
    city: Literal["北京"] = Field(default="北京", description="示例数据目前只支持北京")
    live_routes: bool = Field(default=False, description="是否查询实时高德市内路线")
    route_mode: Literal["transit", "driving"] = Field(
        default="transit", description="市内交通方式，默认公交/地铁优先"
    )
    weather_date: str | None = Field(
        default=None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="可选天气预报日期 YYYY-MM-DD"
    )


def _build_planner() -> GenerationIntegrationModule:
    preparation = DataPreparationModule()
    chunks = preparation.chunk_documents()
    index = IndexConstructionModule().build_vector_index(chunks)
    retriever = RetrievalOptimizationModule(index, chunks)
    return GenerationIntegrationModule(preparation.get_catalog("北京"), retriever)


PLANNER = _build_planner()


def list_travel_tools(prefix: str = "travel-") -> list[types.Tool]:
    return [types.Tool(
        name=f"{prefix}plan-trip",
        description=(
            "规划北京一日游示例，比较高铁站和机场落地并用本地 FAISS 资料补充景点介绍。"
            "跨城班次、到返时刻、景区开放与知识库均为模拟值，不可据此确认当天往返。"
            "默认离线；可选实时高德公交/地铁路线与指定日期天气预报。"
        ),
        inputSchema=TripInput.model_json_schema(),
    )]


def _live_route_matrix(catalog: dict, selected: set[str], mode: str) -> tuple[dict, dict]:
    amap = AMapAdapter()
    try:
        return amap.route_matrix(catalog, selected, mode=mode)
    finally:
        amap.close()


async def call_travel_tool(
    name: str, arguments: dict | None, prefix: str = "travel-"
) -> list[types.TextContent]:
    if name != f"{prefix}plan-trip":
        raise ValueError(f"Unknown travel tool: {name}")
    request = TripInput.model_validate(arguments or {})
    catalog = PLANNER.catalog
    selected = {item["id"] for item in catalog["attractions"] if item["name"] in request.query}
    selected = selected or {item["id"] for item in catalog["attractions"]}
    route_minutes = route_evidence = None
    if request.live_routes:
        route_minutes, route_evidence = await asyncio.to_thread(
            _live_route_matrix, catalog, selected, request.route_mode
        )
    weather = (
        await forecast_from_weather_mcp(request.city, request.weather_date)
        if request.weather_date else None
    )
    plan = PLANNER.plan(
        request.query, weather=weather,
        route_minutes=route_minutes, route_evidence=route_evidence,
    )
    return [types.TextContent(type="text", text=PLANNER.render(plan))]
