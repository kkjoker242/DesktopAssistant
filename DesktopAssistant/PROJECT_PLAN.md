# Desktop Assistant 项目现状与规划

## 已实现

- PySide6 透明置顶桌宠，支持拖拽、点击互动、圆润对话气泡和鲸鱼娘角色素材。
- 待机、眨眼、散步、挥手、思考、休息六种动画；右键“动作”菜单可手动播放。
- 多会话聊天窗口与本地 SQLite 历史，支持创建、切换、重命名和删除会话。
- `MessageSink`、`MCPClient` 与 stdio MCP 服务；已接入天气和北京一日游示例工具。
- 聊天后端在桌宠窗口首次绘制后连接，旅行工具运行期间显示进度。

## 技术与目录

- Python 3.12+，依赖由 `pyproject.toml` 和 `uv.lock` 管理。
- `src/desktop_assistant/qt_pet_window.py`：桌宠绘制、动画与交互。
- `src/desktop_assistant/conversation_dialog.py`、`chat_history.py`：会话界面和本地历史。
- `src/desktop_assistant/client.py`、`serve.py`：模型客户端和 MCP 工具服务。
- `assets/animated/whale-girl/`：当前角色的六组动画帧。
- 旅行检索与规划代码位于同级 `RAGServe/`；天气实现位于同级 `weather/`。

## 后续方向

1. 将模型与天气配置集中到可编辑设置界面，并增加启动诊断。
2. 增加系统托盘、快捷开关与更多角色素材。
3. 用经核验的景区资料、跨城班次和开放信息取代北京模拟数据。
4. 评估语音输入输出、提醒和 Windows 打包。

当前功能和运行方式见 [README.md](README.md)；旅行规划的数据边界见 [RAGServe 说明](../RAGServe/README.md)。
