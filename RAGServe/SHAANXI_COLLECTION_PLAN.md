# 陕西省知名景点首轮采集计划与进度

更新：2026-10-24。范围按 `陕西省 → 地区 → 景点 → 来源记录 → 检索块` 管理；杨凌示范区作为单独地区。先做知名景点，县区级小景点留给后续专项采集。

下述 `data/` 文件是本地采集与构建产物，不随公开仓库提交。复现入库命令前需准备有权处理的 JSONL 资料。

## 任务划分

| 地区 | 第一批已入库 | 下一批待补 |
| --- | --- | --- |
| 西安 | 秦始皇帝陵博物院、钟楼、鼓楼、大唐芙蓉园、陕西历史博物馆的来源卡；原有华清宫、大雁塔、西安城墙、兵马俑游客笔记 | 为华清宫、大雁塔、西安城墙补官方介绍；大明宫 |
| 宝鸡 | 法门寺文化景区、太白山 | 太白山分主题路线卡 |
| 咸阳 | 乾陵、袁家村 | 汉阳陵、郑国渠 |
| 铜川 | 照金革命纪念地、药王山 | 耀州窑博物馆 |
| 渭南 | 华山 | 华山分峰和步道资料、天气及索道实时接口 |
| 延安 | 黄帝陵、延安革命纪念馆 | 壶口瀑布陕西侧、乾坤湾 |
| 榆林 | 红石峡 | 镇北台、红碱淖 |
| 汉中 | 青木川古镇 | 武侯祠、石门栈道 |
| 安康 | 瀛湖 | 南宫山 |
| 商洛 | 金丝峡 | 牛背梁 |
| 杨凌示范区 | 杨凌农林博物院 | 现代农业示范园区创新园 |

第一批优先级按省级文旅规划中的传统优势目的地与各市代表性资源确定。候选目录在 `shaanxi_catalog.py`，含 22 个景点；22 个景点均已有内容入库，其中 19 个有官方或政府来源卡，4 个有游客笔记，秦始皇帝陵博物院两类来源都有。华清宫、大雁塔、西安城墙目前只有游客笔记，仍须补官方介绍。

## 已执行的采集与入库

- `data/shaanxi_source_cards.jsonl`：19 张逐页核对、用自己的文字概括的来源卡，覆盖上述 11 个地区。每张保存景点、地区、原始页面、来源类型、核对日期、简短介绍；不复制整篇网页。
- `data/shaanxi.sqlite3`：从原 `xian.sqlite3` 复制此前 4 篇西安小红书笔记及 9 个块，再导入来源卡。现有 19 张来源卡、4 篇游客笔记、28 个检索块。原西安数据库仍可单独使用。
- `data/shaanxi_faiss`：28 个块的本地演示索引。`DemoHashEmbeddings` 只能用于流程验证；正式中文语义检索须换用合适模型并重建索引。

来源卡的 `source_type` 为 `government_page`、`scenic_official` 或 `museum_official`，`verification_status=source_reviewed`、`fact_type=static_description`。游客笔记仍为 `source_type=user_generated_note`、`verification_status=unverified`、`fact_type=visitor_experience`。`source_reviewed` 只表示已核对原页面，不表示可将来源中的运营信息当作实时事实。票价、开放时间、预约名额、天气、索道和道路情况应在行前查询实时来源。

### 更新命令

在项目根目录执行：

```powershell
uv run --project DesktopAssistant python -m RAGServe.shaanxi_source_ingest RAGServe/data/shaanxi_source_cards.jsonl
uv run --project DesktopAssistant python -m RAGServe.xiaohongshu_ingest import-jsonl RAGServe/data/xian_xhs_sample.jsonl
uv run --project DesktopAssistant python -m RAGServe.xiaohongshu_ingest build-index
```

两类导入均可重复运行；来源卡修改后只替换对应卡的检索块。新小红书笔记须填陕西省目录中对应的 `city` 和正式 `attraction_name`，并保留原笔记链接。跨景点笔记若无法唯一归属会保留在原始表中，不进入景点索引。

## 下一步采集标准

1. 每个待补景点优先找景区、博物馆或地方政府的介绍页面，写一张可回溯的静态景点卡。
2. 再补游客体验：路线、体力要求、典型停留点；区分经验与事实，不自动接受笔记中的票务或历史断言。
3. 对路线复杂的景区（华山、太白山、壶口瀑布等）另建分主题来源卡，分别写地形/文化、线路选择和实时信息入口，不将多种信息混在同一检索块。
4. 每批入库后核对城市和景点归属、去重结果、来源链接及块数，再重建省级索引。

当前不具备直接操控用户登录浏览器会话的工具；本批以可公开查验的景区和政府页面完成。小红书自动抓取命令仍受其 robots 策略限制，未在本批运行或绕过。若后续提供合规导出或可操作的登录浏览器会话，可继续追加游客笔记。
