from dataclasses import dataclass, field


@dataclass(slots=True)
class AppConfig:
    width: int = 240
    height: int = 270
    outline_color: str = "#2E3340"
    bubble_color: str = "#FFF9EA"
    bubble_text_color: str = "#202632"
    title: str = "Desktop Assistant"
    model_scale: float = 0.28
    model_base_height: int = 400
    move_step: int = 6
    tick_ms: int = 120
    min_idle_ticks: int = 16
    max_idle_ticks: int = 30
    min_walk_ticks: int = 14
    max_walk_ticks: int = 30
    min_rest_ticks: int = 14
    max_rest_ticks: int = 26
    bubble_rect: tuple[int, int, int, int] = (8, 4, 88, 72)
    bubble_tail: tuple[tuple[int, int], tuple[int, int], tuple[int, int]] = ((28, 82), (44, 82), (36, 98))
    messages: list[str] = field(
        default_factory=lambda: [
            "你好，我在桌面上。",
            "右键我可以聊天或退出。",
            "有事就直接叫我。",
        ]
    )
    reaction_messages: list[str] = field(
        default_factory=lambda: [
            "我在听。",
            "收到。",
            "今天也一起工作。",
            "别戳脸。",
        ]
    )
    idle_message: str = "我会自己待机。"
    walk_message: str = "我会自己散步。"
    rest_message: str = "我会自己休息。"
    think_message: str = "正在思考…"
    backend_offline_message: str = "后端未连接，当前只能显示桌宠。"
