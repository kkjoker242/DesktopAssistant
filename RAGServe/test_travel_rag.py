"""Focused checks for the offline travel RAG path."""

from __future__ import annotations

import copy
import asyncio
import os
import sqlite3
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from .data_preparation import DataPreparationModule
from .generation_integration import GenerationIntegrationModule
from .index_construction import IndexConstructionModule
from .retrieval_optimization import RetrievalOptimizationModule
from .travel_services import AMapAdapter, forecast_from_weather_mcp
from .mcp_tools import call_travel_tool


class TravelRagTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.preparation = DataPreparationModule()
        cls.chunks = cls.preparation.chunk_documents()
        cls.index_builder = IndexConstructionModule()
        cls.store = cls.index_builder.build_vector_index(cls.chunks)
        cls.retriever = RetrievalOptimizationModule(cls.store, cls.chunks)
        cls.catalog = cls.preparation.get_catalog("北京")

    def test_chunk_ids_are_stable(self) -> None:
        other = DataPreparationModule().chunk_documents()
        self.assertEqual(
            [doc.metadata["chunk_id"] for doc in self.chunks],
            [doc.metadata["chunk_id"] for doc in other],
        )

    def test_sqlite_round_trip_preserves_chunks(self) -> None:
        with sqlite3.connect(":memory:") as database:
            self.preparation.save_chunks_to_sqlite(database)
            loaded = self.preparation.load_chunks_from_sqlite(database)
        self.assertEqual(
            [doc.metadata["chunk_id"] for doc in self.chunks],
            [doc.metadata["chunk_id"] for doc in loaded],
        )
        self.assertEqual(
            [doc.page_content for doc in self.chunks],
            [doc.page_content for doc in loaded],
        )

    def test_search_respects_attraction_filter(self) -> None:
        results = self.retriever.hybrid_search(
            "故宫 建筑 中轴线",
            city="北京",
            attraction_ids={"palace"},
        )
        self.assertTrue(results)
        self.assertTrue(all(doc.metadata["attraction_id"] == "palace" for doc in results))
        self.assertEqual([], self.retriever.hybrid_search("故宫", city="上海"))

    def test_itinerary_has_return_buffer_and_sources(self) -> None:
        planner = GenerationIntegrationModule(self.catalog, self.retriever)
        result = planner.plan("北京一日游，想去故宫和景山公园")
        self.assertEqual("provisional", result["status"])
        self.assertEqual("sample_only", result["data_status"])
        self.assertGreaterEqual(result["free_minutes_before_departure"], 35)
        self.assertTrue(all(stop["evidence"] for stop in result["stops"]))
        self.assertIn("模拟数据", planner.render(result))

    def test_route_provenance_is_carried_into_answer(self) -> None:
        planner = GenerationIntegrationModule(self.catalog, self.retriever)
        result = planner.plan(
            "故宫",
            route_minutes=self.catalog["route_minutes"],
            route_evidence={"source": "AMap test response", "mode": "driving"},
        )
        self.assertEqual("AMap test response", result["route_evidence"]["source"])
        self.assertIn("高德查询时估计", planner.render(result))

    def test_optional_langchain_generation_path(self) -> None:
        planner = GenerationIntegrationModule(self.catalog, self.retriever)
        result = planner.plan("故宫")
        model = RunnableLambda(lambda _prompt: AIMessage(content="示例回答"))
        self.assertEqual("示例回答", planner.generate_answer("故宫", result, model))

    def test_infeasible_window_is_rejected(self) -> None:
        catalog = copy.deepcopy(self.catalog)
        for hub in catalog["hubs"]:
            hub["departure"] = "10:00"
        planner = GenerationIntegrationModule(catalog, self.retriever)
        self.assertEqual("infeasible", planner.plan("故宫")["status"])

    def test_untrusted_index_is_not_loaded(self) -> None:
        with self.assertRaises(ValueError):
            self.index_builder.load_index()

    def test_amap_adapter_parses_poi_and_duration(self) -> None:
        def respond(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v3/place/text":
                return httpx.Response(200, json={
                    "status": "1",
                    "pois": [{"id": "p1", "name": "故宫", "location": "116.1,39.9"}],
                })
            return httpx.Response(200, json={
                "status": "1", "route": {"paths": [{"cost": {"duration": "3661"}}]},
            })

        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            adapter = AMapAdapter(key="test-only", client=client)
            self.assertEqual("p1", adapter.search_poi("北京", "故宫")["id"])
            self.assertEqual(62, adapter.driving_minutes("116.1,39.9", "116.2,39.9"))

    def test_amap_routes_use_environment_key(self) -> None:
        def respond(request: httpx.Request) -> httpx.Response:
            self.assertEqual("test-only", request.url.params["key"])
            return httpx.Response(200, json={"status": "1", "pois": [
                {"name": "故宫", "location": "116.1,39.9"}
            ]})

        with patch.dict(os.environ, {"AMAP_API_KEY": "test-only"}):
            with httpx.Client(transport=httpx.MockTransport(respond)) as client:
                adapter = AMapAdapter(client=client)
                self.assertEqual("test-only", adapter.key)
                self.assertEqual("故宫", adapter.search_poi("北京", "故宫")["name"])

    def test_transit_is_default_and_uses_citycode(self) -> None:
        requests = []

        def respond(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path == "/v3/place/text":
                name = request.url.params["keywords"]
                return httpx.Response(200, json={"status": "1", "pois": [
                    {"id": name, "name": name, "location": "116.1,39.9"}
                ]})
            return httpx.Response(200, json={"status": "1", "route": {
                "transits": [{"cost": {"duration": "3661"}}]
            }})

        catalog = {"city": "北京", "citycode": "010", "hubs": [
            {"id": "hub", "name": "北京南站"}
        ], "attractions": [{"id": "palace", "name": "故宫"}]}
        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            routes, evidence = AMapAdapter(key="test-only", client=client).route_matrix(
                catalog, {"palace"}
            )
        self.assertEqual(62, routes["hub"]["palace"])
        self.assertEqual("transit", evidence["mode"])
        transit_calls = [r for r in requests if r.url.path.endswith("transit/integrated")]
        self.assertEqual(2, len(transit_calls))
        self.assertEqual("010", transit_calls[0].url.params["city1"])
        self.assertEqual("010", transit_calls[0].url.params["city2"])
        self.assertEqual("7", transit_calls[0].url.params["strategy"])
        self.assertEqual("cost", transit_calls[0].url.params["show_fields"])

    def test_unavailable_transit_does_not_silently_drive(self) -> None:
        def respond(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v3/place/text":
                name = request.url.params["keywords"]
                return httpx.Response(200, json={"status": "1", "pois": [
                    {"id": name, "name": name, "location": "116.1,39.9"}
                ]})
            self.assertEqual("/v5/direction/transit/integrated", request.url.path)
            return httpx.Response(200, json={"status": "1", "route": {"transits": []}})

        catalog = {"city": "北京", "citycode": "010", "hubs": [
            {"id": "hub", "name": "北京南站"}
        ], "attractions": [{"id": "palace", "name": "故宫"}]}
        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            routes, _ = AMapAdapter(key="test-only", client=client).route_matrix(
                catalog, {"palace"}
            )
        self.assertEqual({}, routes["hub"])

    def test_desktop_mcp_registers_travel_and_weather(self) -> None:
        from desktop_assistant.serve import handle_call_tool, handle_list_tools

        listed = asyncio.run(handle_list_tools())
        names = {tool.name for tool in listed}
        self.assertIn("travel-plan-trip", names)
        self.assertTrue(any(name.startswith("weather-") for name in names))
        result = asyncio.run(handle_call_tool(
            "travel-plan-trip", {"query": "北京一日游，想去故宫和景山公园"}
        ))
        self.assertIn("模拟数据", result[0].text)
        self.assertIn("故宫", result[0].text)

    def test_weather_mcp_result_is_scoped_to_date(self) -> None:
        async def fake_tool(*_args, **_kwargs):
            return [SimpleNamespace(type="text", text=(
                "发布时间: 2026-09-28 08:00\n"
                "2026-09-28 1\n白天: 晴 25°C\n---\n"
                "2026-09-29 2\n白天: 小雨 20°C\n---"
            ))]

        with patch("weather.weather_serve.call_weather_tool", fake_tool):
            result = asyncio.run(forecast_from_weather_mcp("北京", "2026-09-29"))
        self.assertEqual("小雨", result["condition"])
        self.assertEqual("2026-09-28 08:00", result["report_time"])


class DesktopMcpProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_travel_tool_over_stdio(self) -> None:
        server_path = (
            Path(__file__).resolve().parents[1]
            / "DesktopAssistant/src/desktop_assistant/serve.py"
        )
        params = StdioServerParameters(command=sys.executable, args=[str(server_path)])
        async with asyncio.timeout(20):
            async with stdio_client(params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    self.assertIn("travel-plan-trip", {tool.name for tool in listed.tools})
                    result = await session.call_tool(
                        "travel-plan-trip", {"query": "北京一日游，想去故宫"}
                    )
                    self.assertFalse(result.isError)
                    self.assertIn("模拟数据", result.content[0].text)


if __name__ == "__main__":
    unittest.main()
