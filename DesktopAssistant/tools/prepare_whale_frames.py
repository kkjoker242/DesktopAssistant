"""Split the whale-girl pose strips into aligned transparent animation frames."""

from __future__ import annotations

from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1] / "assets" / "animated" / "whale-girl"
ACTIONS = ("idle", "blink", "walk", "wave", "think", "rest")
FRAME_SIZE = (384, 384)


def split_strip(image: Image.Image) -> list[Image.Image]:
    alpha = image.getchannel("A")
    counts = [sum(value > 20 for value in alpha.crop((x, 0, x + 1, image.height)).getdata())
              for x in range(image.width)]
    slot = image.width // 3
    cuts = [0]
    for nominal in (slot, slot * 2):
        cut = min(range(nominal - 55, nominal + 55),
                  key=lambda x: (counts[x], abs(x - nominal)))
        cuts.append(cut)
    cuts.append(image.width)
    return [image.crop((cuts[i], 0, cuts[i + 1], image.height)) for i in range(3)]


def main() -> None:
    cropped: dict[str, list[Image.Image]] = {}
    for action in ACTIONS:
        with Image.open(ROOT / "source" / f"{action}.png") as source:
            strips = split_strip(source.convert("RGBA"))
        frames = []
        for strip in strips:
            bounds = strip.getchannel("A").point(lambda value: 255 if value > 3 else 0).getbbox()
            if bounds is None:
                raise ValueError(f"Empty frame in {action}")
            frames.append(strip.crop(bounds))
        cropped[action] = frames

    width = max(frame.width for frames in cropped.values() for frame in frames)
    height = max(frame.height for frames in cropped.values() for frame in frames)
    scale = min((FRAME_SIZE[0] - 16) / width, (FRAME_SIZE[1] - 16) / height)

    for action, frames in cropped.items():
        output = ROOT / action
        output.mkdir(parents=True, exist_ok=True)
        for index, frame in enumerate(frames):
            size = (round(frame.width * scale), round(frame.height * scale))
            sprite = frame.resize(size, Image.Resampling.LANCZOS)
            canvas = Image.new("RGBA", FRAME_SIZE)
            canvas.alpha_composite(sprite, ((FRAME_SIZE[0] - size[0]) // 2,
                                            FRAME_SIZE[1] - 8 - size[1]))
            canvas.save(output / f"{index:02d}.png", optimize=True)


if __name__ == "__main__":
    main()
