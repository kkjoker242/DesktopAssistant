# 旅行规划 RAG 架构（设计稿）

## 目标与边界

输入出发地、目的地、日期、可用时间、返程要求与偏好，输出可执行的一日游方案。先比较高铁站与机场的落地方案，再确定景区顺序，最后从本地知识库补足景区内打卡点、人文背景和游览提示。

当前仓库已有四模块旅行 RAG 离线示例、模拟北京资料和天气 MCP。可选适配器支持高德 POI/公交地铁优先或驾车路线与指定日期天气预报；桌宠 MCP 已注册 `travel-plan-trip`。真实车次/航班、景区知识库、开放/预约信息与景区识图仍是目标架构。

## 数据职责

| 数据 | 建议来源 | 用途 | 更新策略 |
| --- | --- | --- | --- |
| 高铁站、机场、景区入口、景点 POI | 高德 POI 搜索；必要时人工核对 | 坐标、候选落地点和入口 | 查询时获取并短期缓存 |
| 落地点到景区、市内景区间路线 | 高德路径规划 2.0 | 步行/公交/驾车耗时、换乘、费用估计 | 规划时查询，展示查询时间 |
| 跨城车次/航班、到发时刻和票价 | 经授权的铁路/航班数据源或用户提供的票单 | 判断能否当天到达和返程 | 临近出行重新核验 |
| 天气 | 已有 `weather-get-forecast` 预报工具；`weather-get-alerts` 当前实际返回实况 | 室内外景点和备用方案 | 每次规划时查询，记录发布时间；预警能力待补 |
| 景区开放、预约、门票、临时关闭 | 景区官方公告或经核验的数据源 | 硬约束 | 按日期核验；无法核验则标记待确认 |
| 景区内打卡点、人文介绍、游览建议 | 本地旅行知识库 | 增强说明和景区内次序 | 入库时记录来源、日期和版本 |

高德 Web 服务可提供 POI 和市内多种路径规划，不能据此推断真实跨城班次、票额或景区内部通道一定可达。景区内部路径若无可靠步行路线和入口/出口坐标，只能给建议顺序并标记为估计。

## 分层与数据流

```text
PySide6 桌宠/未来行程界面
  -> TravelPlanner（编排；结构化行程与来源）
     -> TripRequest 解析（出发地、日期、可用时间、返程、预算、偏好）
     -> IntercityProvider（车次/航班候选与到发时刻）
     -> AMapAdapter（POI、入口、市内路线）
     -> WeatherAdapter（现有 MCP 预报/预警）
     -> AttractionFactsProvider（开放/预约/票价）
     -> ItinerarySolver（时间窗、交通、停留时长、天气、返程缓冲）
     -> TravelRetriever（LangChain Document -> FAISS + 中文关键词 -> 融合）
     -> LLMAdapter（只解释候选行程和检索证据，不生成虚构时刻）
  -> 带时间轴、来源、待核验事项和备用方案的结果
```

模型可以解释、归纳和润色，但时间窗约束与交通耗时由代码校验。生成后再对每段路线的开始/结束、开放时间和返程缓冲做一次机器检查。

## 规划顺序

1. **补齐输入**：缺少出发地、旅行日期或当天可用时段时，先询问；用户暂不提供时可给明确标为假设的示意方案。区分“目的地一日游”和“当天往返”。
2. **跨城到达候选**：列出可用的高铁站/机场组合，读取真实到发时刻；没有班次数据时只比较站点位置与市内接驳，不声称某趟车/飞机可买或能准时到达。
3. **城市内候选**：查询景区和具体入口 POI，按落地点分别计算到第一站及景点间路线。计算接驳、安检、出站、行李和返程的缓冲；比较总可游玩时间，而非仅比较落地点到市中心的距离。
4. **天气和开放约束**：查询目的地及日期的预报/预警；把强降雨、大风等作为户外方案调整依据。开放时间、预约和临时关闭必须用可核验来源，不用旧知识库内容替代实时公告。
5. **求解行程**：生成少量候选顺序，以到达时间、景点停留时长、路程、费用、偏好和天气风险评分。剔除超出营业时间、赶不上返程或跨城接驳过紧的方案。明确展示被排除的原因。
6. **RAG 增强**：按 `city + attraction_id + entrance_id` 过滤资料，再检索景区内打卡点、背景和实用提示。资料缺失时保持简短，不补造景点事实。
7. **生成与校验**：输出带来源的时间轴、站点选择理由、景区内路线、天气备选和待核验事项；确认叙述与结构化行程一致。

## FAISS、LangChain 与数据库

- **文档摄取**：使用 LangChain `Document`，按景区/分区/打卡点标题分块；长段落再按长度切分。保留景区名、城市、入口、来源 URL/文件、更新时间及可靠性等级。
- **稳定 ID**：`document_id = hash(source_uri)`；`chunk_id = hash(document_id + section + normalized_text)`。避免当前食谱代码中的随机块 ID 造成重复索引。
- **持久化**：FAISS 保存向量和 LangChain docstore；SQLite 保存文档主数据、景点/入口坐标、来源、`chunk_id`、内容哈希、embedding 模型/版本、索引构建记录、会话与行程。两者通过 `chunk_id` 对齐。索引更新失败时不切换活动版本。
- **检索**：小规模 MVP 可在 FAISS 中扩大候选数，再做城市/景区元数据过滤；数据量增长后按城市或景区拆分索引，避免全局 top-k 结果把目标景区挤掉。并行做中文分词后的 BM25/FTS 检索，用 RRF 融合、去重并按证据质量重排。中文 BM25 必须有合适的分词预处理，不能直接套英文按空格分词。
- **安全边界**：只加载自己构建且可验证来源的 FAISS 索引。现有 `IndexConstructionModule.load_index()` 允许危险反序列化，不能用于不受信任的下载索引。
- **生成上下文**：只传最终候选片段及来源、查询时间和事实类型。把动态字段（天气、交通、营业状态）放在独立结构化上下文中，避免旧游记覆盖实时事实。

建议的最小表：`documents`、`chunks`、`attractions`、`entrances`、`sources`、`index_versions`、`trip_requests`、`itineraries`。`chunks` 至少有 `chunk_id`、`document_id`、`city`、`attraction_id`、`section`、`content`、`source_id`、`updated_at`；`index_versions` 至少有 embedding 模型、维度、构建时间和状态。

## 与现有代码的关系

- `RAGServe/data_preparation.py` 已从示例 JSON 生成稳定 ID 的旅行资料块，并可用 SQLite 存取；真实资料需要补充来源核验和增量更新。
- `RAGServe/index_construction.py` 已使用 FAISS 和离线哈希 embedding 跑通示例；正式语义检索应注入训练好的中文 embedding 模型。
- `RAGServe/retrieval_optimization.py` 已做 FAISS + 中文分词 BM25 + RRF；`generation_integration.py` 已按时间窗和接驳数据求出可行时间轴，可注入 `travel_services.py` 获取的公交/地铁优先或驾车耗时与天气。跨城到发时刻仍使用模拟值。
- `DesktopAssistant/src/desktop_assistant/serve.py` 已注册 `travel-plan-trip`，由 `RAGServe/mcp_tools.py` 编排离线或可选实时规划；桌宠界面无需直接依赖地图或向量库。
- `DesktopAssistant/src/desktop_assistant/client.py` 当前为单轮问答。多轮旅行规划需保存请求状态，才能在用户补充出发地、日期和偏好后继续同一个方案。

## 建议接口

```python
TripRequest(origin_city, destination_city, travel_date, available_window,
            return_same_day, budget, pace, interests, transport_preferences)

IntercityProvider.search(request) -> list[IntercityOption]
AMapAdapter.search_pois(city, keywords) -> list[Place]
AMapAdapter.route(origin, destination, mode, departure_time) -> RouteEstimate
WeatherAdapter.forecast(city, date) -> WeatherEvidence
TravelRetriever.search(city, attraction_id, topics) -> list[EvidenceChunk]
TravelPlanner.plan(request) -> TripPlan
```

每个事实对象带 `source` 和 `retrieved_at`；路线估计带出行方式、距离、耗时和不可用原因。`departure_time` 是规划上下文，具体高德端点若不支持未来时刻算路，结果必须标记为当前路况/静态估计，不能表述成未来时段的精确耗时。`TripPlan` 包含主方案、备选方案、假设、待核验事项和引用。以上是目标接口，不是已存在的 Python 类型。

## 验收样例

- **北京一日游，上海出发，当天往返**：未提供日期时不编造班次；日期给定后比较高铁站和机场落地方案，若时间窗不可行应直说。
- **北京一日游，已在北京西站**：跳过跨城阶段，按北京西站出发计算第一站和景区间路线。
- **雨天故宫周边**：依据天气发布时间调整户外停留和备用室内点；故宫预约/开放状态未核实时标记待核验。
- **景区资料缺失**：照常给交通与时间安排，景区内解说仅输出已核实内容。
- **未来识图**：图像模型返回候选打卡点及置信度，再结合用户所在景区/位置交叉验证；低置信度请求用户确认，不能直接写成已识别事实。

## 实施顺序

1. 北京少量景区的可信资料、SQLite 元数据与离线 FAISS 索引。
2. 高德 POI/路径、天气 MCP、时间窗求解与结构化行程；先用用户提供的班次测试跨城流程。
3. 授权的跨城班次数据源、缓存和定时刷新；补充真实车次/航班验证。
4. 带来源回答、桌宠调用入口已实现；未来可补多轮请求状态和 UI 展示。
5. 有标注数据后实现景区识图，单独评估误识别风险。

## 接口依据

- [高德搜索 POI](https://lbs.amap.com/api/webservice/guide/api/search/)
- [高德路径规划 2.0](https://lbs.amap.com/api/webservice/guide/api/newroute)
- [高德天气查询](https://lbs.amap.com/api/webservice/guide/api/weatherinfo)
