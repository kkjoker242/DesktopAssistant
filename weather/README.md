# 天气 MCP 工具

`weather_serve.py` 使用高德天气接口提供中国城市和区县的实况、预报查询，并由桌面助手的 MCP 服务统一注册。地点名称通过 `AMap_adcode_citycode.xlsx` 查找 adcode。

| 工具 | 输入 | 当前行为 |
| --- | --- | --- |
| `get-alerts` | `state` | 返回该地点天气实况；名称沿用旧接口，目前尚未查询气象预警 |
| `get-forecast` | `district`，可选 `province` | 返回该地点未来天气预报 |

## 使用

在项目根目录运行桌宠前，设置 `AMAP_API_KEY` 环境变量：

```powershell
$env:AMAP_API_KEY = "你的高德密钥"
uv run --project DesktopAssistant python DesktopAssistant/main.py
```

桌宠通过同级的 `DesktopAssistant/src/desktop_assistant/serve.py` 暴露天气工具。旅行规划的实时路线也可复用该 Key，但需要在高德控制台分别核对天气、POI 与路线服务权限和配额。未设置 Key 时，本地桌宠与离线旅行示例仍可运行，实时天气请求无法成功。

接口细节见 [weather_api.md](weather_api.md)；完整项目说明见 [根目录 README](../README.md)。
