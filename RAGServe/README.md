# 旅行 RAG 与行程规划

本模块提供北京一日游的离线示例：读取模拟景点资料，分块后建立 FAISS 索引，结合中文 BM25 与 RRF 融合检索，最后生成受时间窗约束的行程。桌面助手通过 `travel-plan-trip` MCP 工具调用同一规划逻辑。

## 运行

在项目根目录执行：

```powershell
uv sync --project DesktopAssistant
uv run --project DesktopAssistant python -m RAGServe.demo
```

默认使用 `sample_data/beijing.json`，不访问外网。可选参数：`--live-routes` 查询高德 POI 与市内路线，`--route-mode driving` 选驾车，`--weather-date YYYY-MM-DD` 查询指定日期天气。实时选项需要环境变量 `AMAP_API_KEY` 以及相应的高德服务权限。

## 范围与数据

- 目前 MCP 行程工具只支持北京；跨城班次、到返时刻、景区开放和基础知识库仍为模拟数据，结果不能作为实际订票依据。
- `data_preparation.py`、`index_construction.py`、`retrieval_optimization.py`、`generation_integration.py` 分别负责资料准备、索引、检索和规划。
- 陕西资料采集与入库工具仍是独立实验流程，尚未接入北京桌宠行程。`data/` 下的笔记、数据库与索引为本地数据，不随仓库发布；相关命令需要自备有权处理的资料。

详细设计见 [旅行架构](TRAVEL_RAG_ARCHITECTURE.md)，陕西资料流程见 [采集计划](SHAANXI_COLLECTION_PLAN.md) 和 [笔记入库说明](XIAOHONGSHU_INGEST.md)。
