# 对话历史与上下文预算

桌宠将成功完成的用户提问与最终回复按会话写入本地 SQLite：`DesktopAssistant/data/chat_history.sqlite3`。关闭后重新打开“对话”窗口，可按会话查看全部已保存消息，并新建、切换、重命名或删除会话。旧版未分会话的消息会自动迁入“历史对话”，原文不删；删除会话则会删除其中的消息。进行中的提问只在窗口中临时显示，成功收到回复后成对保存。`DesktopAssistant/.gitignore` 忽略数据目录；可用 `DESKTOP_CHAT_DB_PATH` 改变存储位置。SQLite 文件为明文，可能包含个人信息或用户主动输入的密钥，应按敏感文件管理。

**当前隐私边界：** 不同会话的历史只用于本地浏览与管理，暂不发送给外部 DeepSeek API，也不调用外部模型生成摘要。当前回答仍仅使用当轮输入；启用历史上下文和摘要发送需要用户明确授权。

## 长度依据

项目当前使用 `deepseek-v4-flash`。据[DeepSeek 模型与价格文档](https://api-docs.deepseek.com/quick_start/pricing/)，该旧名称当前映射到 V4.1 Flash，文档列出 1M token 上下文；这只是模型能力上限，不适合当作每轮实际使用目标。DeepSeek 的 [token 用量说明](https://api-docs.deepseek.com/quick_start/token_usage/)指出，中英文字符到 token 的换算只是近似，实际用量以 API 的 `usage` 为准。

本项目默认把**发给模型的历史部分**限制为 24 KiB UTF-8 字节，可用 `DESKTOP_HISTORY_BUDGET_BYTES` 调整，最小 8 KiB。24 KiB 约能容纳 8,000 个常见汉字，按官方约 0.6 token/汉字的参考比例约为 4,800 token；这是偏保守的成本与延迟预算，远低于 1M 上限，并为工具定义、实时路线/天气数据、当前问题和回复预留空间。字节数并非精确 token 计数；上线后可根据 API 返回的 `usage` 校准。

预算触发时，保留最近 2 轮完整问答；更早内容按不超过 12 KiB 的块滚动摘要，目标摘要不超过 4 KiB。摘要失败时仍保留 SQLite 原文，当前请求只选取预算内的完整近期轮次，不会无界追加历史。当前超长用户问题不截断，但可能挤出所有历史上下文。摘要生成与对外使用尚未启用。
