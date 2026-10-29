"""Normalize generated three-pose strips into aligned desktop-pet frames."""

from __future__ import annotations

from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1] / "assets" / "animated" / "v2"
ACTIONS = ("idle", "blink", "walk", "wave", "think", "rest")
FRAME_SIZE = (256, 512)


def _split_strip(strip: Image.Image) -> list[Image.Image]:
    alpha = strip.getchannel("A")
    columns = [sum(value > 20 for value in alpha.crop((x, 0, x + 1, strip.height)).getdata())
               for x in range(strip.width)]
    cuts = [0]
    for nominal in (strip.width // 3, strip.width * 2 // 3):
        start, end = nominal - 60, nominal + 60
        cut = min(range(start, end), key=lambda x: (columns[x], abs(x - nominal)))
        cuts.append(cut)
    cuts.append(strip.width)
    return [strip.crop((cuts[i], 0, cuts[i + 1], strip.height)) for i in range(3)]


def main() -> None:
    cropped: dict[str, list[Image.Image]] = {}
    for action in ACTIONS:
        with Image.open(ROOT / "source" / f"{action}.png") as image:
            strips = _split_strip(image.convert("RGBA"))
        frames = []
        for strip in strips:
            bounds = strip.getchannel("A").point(lambda value: 255 if value > 3 else 0).getbbox()
            if bounds is None:
                raise ValueError(f"Empty {action} frame")
            frames.append(strip.crop(bounds))
        cropped[action] = frames

    largest_width = max(frame.width for frames in cropped.values() for frame in frames)
    largest_height = max(frame.height for frames in cropped.values() for frame in frames)
    scale = min(236 / largest_width, 496 / largest_height)

    for action, frames in cropped.items():
        output_dir = ROOT / action
        output_dir.mkdir(parents=True, exist_ok=True)
        for index, frame in enumerate(frames):
            size = (round(frame.width * scale), round(frame.height * scale))
            sprite = frame.resize(size, Image.Resampling.LANCZOS)
            canvas = Image.new("RGBA", FRAME_SIZE)
            canvas.alpha_composite(sprite, ((FRAME_SIZE[0] - size[0]) // 2, 504 - size[1]))
            canvas.save(output_dir / f"{index:02d}.png", optimize=True)


if __name__ == "__main__":
    main()
