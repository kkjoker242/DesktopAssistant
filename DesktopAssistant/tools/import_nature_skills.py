from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path


SKIP_NAMES = {"README.md", "evals.json", "marketplace.json"}
SKIP_DIRS = {".git", ".github", ".claude-plugin"}


def parse_frontmatter(skill_md: str) -> tuple[dict[str, str], str]:
    if not skill_md.startswith("---"):
        raise ValueError("SKILL.md is missing YAML frontmatter")
    parts = skill_md.split("---", 2)
    if len(parts) < 3:
        raise ValueError("SKILL.md frontmatter is not closed")

    raw = parts[1].strip("\n")
    body = parts[2].lstrip("\n")
    data: dict[str, str] = {}
    lines = raw.splitlines()
    i = 0

    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.startswith(" ") or line.startswith("\t") or ":" not in line:
            i += 1
            continue

        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        i += 1

        if value in {">", ">-", "|", "|-"}:
            chunks: list[str] = []
            while i < len(lines):
                nxt = lines[i]
                if nxt.startswith(" ") or nxt.startswith("\t"):
                    chunks.append(nxt.strip())
                    i += 1
                    continue
                break
            data[key] = " ".join(part for part in chunks if part).strip()
            continue

        data[key] = value.strip("\"'")

    return data, body


def build_frontmatter(name: str, description: str) -> str:
    description = re.sub(r"\s+", " ", description).strip()
    return (
        "---\n"
        f"name: {name}\n"
        "description: >-\n"
        f"  {description}\n"
        "---\n\n"
    )


def should_skip(path: Path) -> bool:
    if path.name in SKIP_DIRS:
        return True
    if path.name in SKIP_NAMES:
        return True
    return False


def copy_tree(src: Path, dst: Path) -> None:
    for item in src.iterdir():
        if should_skip(item):
            continue
        target = dst / item.name
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            copy_tree(item, target)
        else:
            shutil.copy2(item, target)


def normalize_skill(src_dir: Path, dst_dir: Path) -> None:
    dst_dir.mkdir(parents=True, exist_ok=True)
    copy_tree(src_dir, dst_dir)

    src_skill_md = (src_dir / "SKILL.md").read_text(encoding="utf-8")
    meta, body = parse_frontmatter(src_skill_md)
    name = meta.get("name")
    description = meta.get("description")
    if not name or not description:
        raise ValueError(f"{src_dir} is missing name or description")

    normalized = build_frontmatter(name, description) + body
    (dst_dir / "SKILL.md").write_text(normalized, encoding="utf-8")


def validate_skill(skill_dir: Path) -> list[str]:
    problems: list[str] = []
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.exists():
        return [f"{skill_dir.name}: missing SKILL.md"]

    text = skill_file.read_text(encoding="utf-8")
    meta, _ = parse_frontmatter(text)
    keys = set(meta.keys())
    if keys != {"name", "description"}:
        problems.append(
            f"{skill_dir.name}: frontmatter keys must be name,description; got {sorted(keys)}"
        )
    if not re.fullmatch(r"[a-z0-9-]{1,63}", meta["name"]):
        problems.append(f"{skill_dir.name}: invalid skill name {meta['name']!r}")
    if skill_dir.name != meta["name"]:
        problems.append(
            f"{skill_dir.name}: folder name does not match skill name {meta['name']!r}"
        )
    if not meta["description"].strip():
        problems.append(f"{skill_dir.name}: description is empty")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    src_root = Path(args.source)
    out_root = Path(args.output)
    out_root.mkdir(parents=True, exist_ok=True)

    shared_src = src_root / "_shared"
    if shared_src.exists():
        shared_dst = out_root / "_shared"
        if shared_dst.exists():
            shutil.rmtree(shared_dst)
        shared_dst.mkdir(parents=True, exist_ok=True)
        copy_tree(shared_src, shared_dst)

    skill_dirs = sorted(
        path for path in src_root.iterdir() if path.is_dir() and path.name.startswith("nature-")
    )

    for skill_dir in skill_dirs:
        dst_dir = out_root / skill_dir.name
        if dst_dir.exists():
            shutil.rmtree(dst_dir)
        normalize_skill(skill_dir, dst_dir)

    problems: list[str] = []
    for skill_dir in sorted(out_root.iterdir()):
        if skill_dir.is_dir() and skill_dir.name.startswith("nature-"):
            problems.extend(validate_skill(skill_dir))

    if problems:
        print("VALIDATION_FAILED")
        for problem in problems:
            print(problem)
        return 1

    print(f"Imported {len(skill_dirs)} skills into {out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
