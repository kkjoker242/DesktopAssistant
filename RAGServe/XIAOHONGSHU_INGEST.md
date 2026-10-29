# 西安景点笔记入库方案（试采记录）

本文件记录 2026-10-22 的西安试采。2026-10-24 起全省采集以 [SHAANXI_COLLECTION_PLAN.md](SHAANXI_COLLECTION_PLAN.md) 为准，命令默认数据库已改为 `RAGServe/data/shaanxi.sqlite3`，默认索引为 `RAGServe/data/shaanxi_faiss`。下文的“只收西安”和旧默认路径仅描述当时的测试阶段。

## 当前采集边界

2026-10-12 查询 `https://www.xiaohongshu.com/robots.txt`：通用 `User-agent: *` 是 `Disallow: /`。`/explore` 的例外只授予列出的搜索引擎。`crawl` 命令每次先取 robots 文件，当前会退出且不会访问页面；没有实现登录、签名、接口逆向或验证码绕过。获得平台许可及可用的数据接口后，可以在此入口接入经核验的采集适配器。现在可用 `import-jsonl` 导入有权保存和处理的笔记导出。

2026-10-22 使用用户已登录的浏览器会话，人工式搜索并打开了四篇西安景点笔记，页面未要求重新登录。样本逐篇核对后保存为 `RAGServe/data/xian_xhs_sample.jsonl`，再通过 `import-jsonl` 导入。这是浏览器会话中的小规模试采，不代表 `crawl` 命令已能批量访问站点。URL 只保存笔记的 `/explore/ID` 路径，不保存会话查询参数或登录凭据。

## RAG 数据模型

按 `陕西省 → 西安 → 景点 → 来源笔记 → 检索块` 组织。SQLite 的 `xhs_notes` 保存每篇笔记的标题、正文、URL、发布时间、导入时间、内容哈希和景点归属；`attraction_chunks` 复用现有 RAG 表结构，保存可检索块及元数据。`source_note_id`、`source` URL、`published_at`、`verification_status=unverified` 进入每个块，回答时可回溯原笔记。笔记 ID 从 URL 路径提取；重新导入相同内容不重复写入，更新正文则原子替换该笔记的块。

一篇笔记若明确指定 `attraction_name`，按该景点归档；否则只有命中**恰好一个**景点别名才自动归档。命中多个景点、没有命中景点的笔记保留为 `unassigned`，不进入索引。这样跨景点行程笔记不会被错误地作为单个景点的证据。当前小词表只用于西安试采，可在脚本中的 `ATTRACTIONS` 扩充；别名需要人工检查以防歧义。

切块从“景点资料章节 450 字、50 字重叠”调整为“单篇笔记内 420 字、40 字重叠，优先按段落和中文句末切开”。短笔记保持一块；每块加景点名和笔记标题，避免脱离上下文。不同笔记和不同景点绝不拼接。现有北京示例切块参数不变。保存的 `chunk_id` 包含来源笔记、景点、块位置和文本；内容变化会重建对应块。现有 `DataPreparationModule.load_chunks_from_sqlite`、`IndexConstructionModule`、`RetrievalOptimizationModule` 可以直接读取这些块。

游客笔记属于经验性、未经核验的材料。`fact_type=visitor_experience` 和 `source_type=user_generated_note` 将其与官方开放、预约、票价、实时交通等事实区分。后者应继续从官方或实时数据源查询，不从游记推断。当前不存作者账号、评论、图片或互动数据。

当前试采样本覆盖华清宫、大雁塔、西安城墙和秦始皇帝陵博物院，共四篇笔记、九个检索块。图文笔记仅保存页面可见的正文，没有识别图片中的文字；带有相对日期的笔记未猜测发布日期。样本里历史叙述和游玩建议均保持 `unverified`，尤其不能直接用于回答当前票务、开放时间或预约政策。

## 导入格式与命令

每行一个 UTF-8 JSON 对象。必需字段：`source_url`、`city`（必须为 `西安`）、`title`、`content`。可选：`region`（默认 `陕西省`）、`published_at`（建议 ISO 8601）、`attraction_name`（使用脚本词表中的正式名称）。示意：

```json
{"source_url":"https://www.xiaohongshu.com/explore/NOTE_ID","city":"西安","region":"陕西省","attraction_name":"大雁塔","title":"游览记录","content":"这里放有权处理的笔记正文。","published_at":"2026-10-01"}
```

在项目根目录执行：

```powershell
uv run --project DesktopAssistant python -m RAGServe.xiaohongshu_ingest crawl
uv run --project DesktopAssistant python -m RAGServe.xiaohongshu_ingest import-jsonl .\RAGServe\data\xian_xhs_sample.jsonl
uv run --project DesktopAssistant python -m RAGServe.xiaohongshu_ingest build-index
```

默认数据库为 `RAGServe/data/xian.sqlite3`，索引为 `RAGServe/data/xian_faiss`。`build-index` 用现有 `DemoHashEmbeddings`，仅用于本地端到端验证；正式语义检索须更换为合适的中文 embedding，并用同一模型重建索引。索引不要从不可信位置加载，因为现有 FAISS docstore 反序列化依赖 pickle。后续若要让桌宠直接规划西安行程，还需提供西安行程 catalog、实时开放信息和交通数据；本次入库不会把北京模拟行程当成西安结果。
