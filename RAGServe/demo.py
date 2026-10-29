"""Run the complete offline FAISS/LangChain travel planning example."""

from __future__ import annotations

import argparse
import asyncio
import sqlite3

from .data_preparation import DataPreparationModule
from .generation_integration import GenerationIntegrationModule
from .index_construction import IndexConstructionModule
from .retrieval_optimization import RetrievalOptimizationModule
from .travel_services import AMapAdapter, forecast_from_weather_mcp


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", nargs="?", default="北京一日游，想去故宫和景山公园")
    parser.add_argument("--live-routes", action="store_true", help="Use AMap POI and city routes")
    parser.add_argument("--route-mode", choices=("transit", "driving"), default="transit")
    parser.add_argument("--weather-date", help="Fetch this YYYY-MM-DD forecast via the weather MCP")
    args = parser.parse_args()

    preparation = DataPreparationModule()
    preparation.chunk_documents()
    with sqlite3.connect(":memory:") as database:
        preparation.save_chunks_to_sqlite(database)
        chunks = preparation.load_chunks_from_sqlite(database)
    index = IndexConstructionModule().build_vector_index(chunks)
    retriever = RetrievalOptimizationModule(index, chunks)
    catalog = preparation.get_catalog("北京")
    planner = GenerationIntegrationModule(catalog, retriever)
    selected = {item["id"] for item in catalog["attractions"] if item["name"] in args.query}
    selected = selected or {item["id"] for item in catalog["attractions"]}
    route_minutes = route_evidence = None
    if args.live_routes:
        amap = AMapAdapter()
        try:
            route_minutes, route_evidence = amap.route_matrix(
                catalog, selected, mode=args.route_mode
            )
        finally:
            amap.close()
    weather = (
        asyncio.run(forecast_from_weather_mcp("北京", args.weather_date))
        if args.weather_date else None
    )
    print(planner.render(planner.plan(
        args.query, weather=weather, route_minutes=route_minutes,
        route_evidence=route_evidence,
    )))


if __name__ == "__main__":
    main()
