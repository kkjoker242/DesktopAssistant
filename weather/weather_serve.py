from __future__ import annotations

import asyncio
import os
import zipfile
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
import mcp.server.stdio
import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions


AMAP_API_KEY = os.getenv("AMAP_API_KEY", "")
AMAP_WEATHER_API = f"https://restapi.amap.com/v3/weather/weatherInfo?key={AMAP_API_KEY}&output=json"
USER_AGENT = "weather-app/1.0"
ADCODE_XLSX_PATH = Path(__file__).with_name("AMap_adcode_citycode.xlsx")

server = Server("weather")


def _weather_tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": "get-alerts",
            "description": "Get active Chinese weather alerts.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "state": {
                        "type": "string",
                        "description": "Location name, preferably detailed to city or district.",
                    }
                },
                "required": ["state"],
            },
        },
        {
            "name": "get-forecast",
            "description": "Get Chinese weather forecast by district name.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "province": {
                        "type": "string",
                        "description": "Province or municipality name mentioned by the user.",
                    },
                    "district": {
                        "type": "string",
                        "description": "District or city name used to look up adcode from the xlsx file.",
                    },
                },
                "required": ["district"],
            },
        },
    ]


def list_weather_tools(prefix: str = "") -> list[types.Tool]:
    return [
        types.Tool(
            name=f"{prefix}{item['name']}",
            description=item["description"],
            inputSchema=item["inputSchema"],
        )
        for item in _weather_tool_definitions()
    ]


@lru_cache(maxsize=1)
def load_adcode_map() -> dict[str, str]:
    if not ADCODE_XLSX_PATH.exists():
        raise FileNotFoundError(f"Adcode xlsx not found: {ADCODE_XLSX_PATH}")

    ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    adcode_map: dict[str, str] = {}

    with zipfile.ZipFile(ADCODE_XLSX_PATH) as zf:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            shared_root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for item in shared_root.findall("a:si", ns):
                text = "".join(node.text or "" for node in item.findall(".//a:t", ns))
                shared_strings.append(text)

        workbook_root = ET.fromstring(zf.read("xl/workbook.xml"))
        first_sheet = workbook_root.find("a:sheets/a:sheet", ns)
        if first_sheet is None:
            return adcode_map

        sheet_rel_id = first_sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        rel_root = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        sheet_target = None
        for rel in rel_root:
            if rel.attrib.get("Id") == sheet_rel_id:
                sheet_target = rel.attrib.get("Target")
                break
        if not sheet_target:
            return adcode_map

        sheet_root = ET.fromstring(zf.read(f"xl/{sheet_target}"))
        rows = sheet_root.findall(".//a:sheetData/a:row", ns)
        if not rows:
            return adcode_map

        header = [_xlsx_cell_value(cell, shared_strings, ns) for cell in rows[0].findall("a:c", ns)]
        try:
            district_index = header.index("中文名")
            adcode_index = header.index("adcode")
        except ValueError as exc:
            raise ValueError("Expected columns '中文名' and 'adcode' were not found in the xlsx file.") from exc

        for row in rows[1:]:
            values = [_xlsx_cell_value(cell, shared_strings, ns) for cell in row.findall("a:c", ns)]
            if district_index >= len(values) or adcode_index >= len(values):
                continue
            district = values[district_index].strip()
            adcode = values[adcode_index].strip()
            if district and adcode:
                adcode_map[district] = adcode

    return adcode_map


def _xlsx_cell_value(cell: ET.Element, shared_strings: list[str], ns: dict[str, str]) -> str:
    value_node = cell.find("a:v", ns)
    if value_node is None or value_node.text is None:
        return ""
    if cell.attrib.get("t") == "s":
        return shared_strings[int(value_node.text)]
    return value_node.text


def lookup_adcode(district: str) -> str | None:
    normalized = district.strip()
    if not normalized:
        return None

    adcode_map = load_adcode_map()
    if normalized in adcode_map:
        return adcode_map[normalized]

    for name, adcode in adcode_map.items():
        if normalized in name or name in normalized:
            return adcode

    return None


async def make_request(client: httpx.AsyncClient, url: str) -> dict[str, Any] | None:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }

    try:
        response = await client.get(url, headers=headers, timeout=30.0)
        response.raise_for_status()
        return response.json()
    except Exception:
        return None


def _text_result(text: str) -> list[types.TextContent]:
    return [types.TextContent(type="text", text=text)]


def format_live_weather(live: dict[str, Any]) -> str:
    return (
        f"城市: {live.get('city', '未知')}\n"
        f"天气: {live.get('weather', '未知')}\n"
        f"温度: {live.get('temperature', '未知')}°C\n"
        f"风向: {live.get('winddirection', '未知')}\n"
        f"风力: {live.get('windpower', '未知')}\n"
        f"湿度: {live.get('humidity', '未知')}\n"
        f"发布时间: {live.get('reporttime', '未知')}"
    )


def format_forecast(forecast: dict[str, Any]) -> str:
    city = forecast.get("city", "未知")
    province = forecast.get("province", "未知")
    report_time = forecast.get("reporttime", "未知")
    casts = forecast.get("casts", [])

    lines = [f"{province}{city} 未来天气", f"发布时间: {report_time}", ""]
    for cast in casts:
        lines.append(
            (
                f"{cast.get('date', '未知')} {cast.get('week', '')}\n"
                f"白天: {cast.get('dayweather', '未知')} {cast.get('daytemp', '未知')}°C {cast.get('daywind', '')}风 {cast.get('daypower', '')}级\n"
                f"夜间: {cast.get('nightweather', '未知')} {cast.get('nighttemp', '未知')}°C {cast.get('nightwind', '')}风 {cast.get('nightpower', '')}级\n"
                "---"
            )
        )
    return "\n".join(lines)


async def call_weather_tool(
    name: str,
    arguments: dict[str, Any] | None,
    prefix: str = "",
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    if not arguments:
        raise ValueError("Missing tool arguments.")

    local_name = name[len(prefix):] if prefix and name.startswith(prefix) else name

    if local_name == "get-alerts":
        state = str(arguments.get("state", "")).strip()
        if not state:
            raise ValueError("Missing required argument: state")

        adcode = lookup_adcode(state)
        if not adcode:
            return _text_result(f"未在 adcode 表中找到地点: {state}")

        async with httpx.AsyncClient() as client:
            url = f"{AMAP_WEATHER_API}&city={adcode}&extensions=base"
            weather_data = await make_request(client, url)

        if not weather_data:
            return _text_result("获取天气实况失败。")

        lives = weather_data.get("lives", [])
        if not lives:
            return _text_result(f"{state} 没有可用的天气实况数据。")

        return _text_result(format_live_weather(lives[0]))

    if local_name == "get-forecast":
        district = str(arguments.get("district", "")).strip()
        if not district:
            raise ValueError("Missing required argument: district")

        lookup_name = district
        adcode = lookup_adcode(lookup_name)
        if not adcode:
            return _text_result(f"未在 adcode 表中找到 district 对应的 adcode: {district}")

        async with httpx.AsyncClient() as client:
            url = f"{AMAP_WEATHER_API}&city={adcode}&extensions=all"
            forecast_data = await make_request(client, url)


        if not forecast_data:
            return _text_result(f"获取 {district} 的天气预报失败。")

        forecasts = forecast_data.get("forecasts", [])
        if not forecasts:
            return _text_result(f"{district} 没有可用的天气预报数据。")

        return _text_result(format_forecast(forecasts[0]))

    raise ValueError(f"Unknown weather tool: {local_name}")


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return list_weather_tools()


@server.call_tool()
async def handle_call_tool(
    name: str,
    arguments: dict[str, Any] | None,
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    return await call_weather_tool(name, arguments)


async def main() -> None:
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="weather",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
