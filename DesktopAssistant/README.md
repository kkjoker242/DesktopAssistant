# Desktop Assistant

一个用 Python 和 PySide6 编写的桌面助手，以鲸鱼娘桌宠为交互入口。目前具备：

- 透明异形桌宠、缩小的圆润气泡和鲸鱼娘动画素材
- 随机发呆、散步、休息
- 左键点击互动
- 右键打开“动作”子菜单，查看并播放待机、眨眼、散步、挥手、思考、休息六种动画；播放后恢复自动行为
- 右键打开会话窗口，按会话浏览、创建、切换、重命名和删除本地记录；较长气泡内容可双击查看完整回复
- 旅行工具执行时显示进度，等待完整结果后再回复；首次 MCP 连接在窗口绘制后进行
- 成功问答按会话保存在本地 SQLite，关闭后可继续查看；历史上下文与摘要的对外发送尚待明确授权，见[对话历史设计](CHAT_HISTORY.md)
- 通过 `MessageSink` 将消息交给 MCP 客户端与外部 LLM
- MCP 服务注册天气工具（`get-alerts` 当前实际返回实况）和 `travel-plan-trip` 旅行示例规划工具
- 使用 `PySide6` 绘制透明桌面窗口、气泡与动画

## 环境要求

- Python 3.12 或更高版本

## 运行方式

在项目根目录使用唯一的 `DesktopAssistant` uv 环境安装依赖并运行：

```powershell
uv sync --project DesktopAssistant
$env:DEEPSEEK_API_KEY = "你的模型密钥"
uv run --project DesktopAssistant python DesktopAssistant/main.py
```

旅行 RAG 示例也使用同一环境：`uv run --project DesktopAssistant python -m RAGServe.demo`。需要实时天气或高德路线时，再设置 `$env:AMAP_API_KEY = "你的高德密钥"`。无模型密钥时桌宠仍可显示，但聊天后端不可用。

## LLM 接口

当前 `llm_interface.py` 会创建 `MCPClient`，后者使用外部模型接口并发现 `serve.py` 注册的天气和旅行工具。旅行工具默认使用北京模拟数据，可选高德公交/地铁优先路线与天气预报；没有真实跨城班次时不能确认当天往返。

- 接口文件：`src/desktop_assistant/llm_interface.py`
- 默认类：`MessageSink`
- 对外方法：`submit(query: str) -> Future[str]`

模型与天气凭据分别从 `DEEPSEEK_API_KEY`、`AMAP_API_KEY` 环境变量读取。曾在本地文件或源码中使用的旧凭据应在服务控制台轮换；不要把 `.env`、`api_key.md`、聊天数据库提交到仓库。

旅行 RAG 的设计与实施阶段见项目根目录的 [README](../README.md) 和 [架构说明](../RAGServe/TRAVEL_RAG_ARCHITECTURE.md)。

## 当前结构

```text
DesktopAssistant/
├─ PROJECT_PLAN.md
├─ README.md
├─ pyproject.toml
├─ uv.lock
├─ main.py
├─ assets/animated/whale-girl/   # 当前六组角色帧
└─ src/
   └─ desktop_assistant/
      ├─ __init__.py
      ├─ app.py
      ├─ config.py
      ├─ chat_history.py
      ├─ client.py
      ├─ conversation_dialog.py
      ├─ llm_interface.py
      ├─ serve.py
      └─ qt_pet_window.py
```
