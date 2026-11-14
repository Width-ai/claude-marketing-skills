#!/usr/bin/env python3
"""Validate the claude-marketing-skills repo.

Checks every marketing area, skill, and guide, and the README indexes that
list them.

Dependency-free, so it runs anywhere with Python 3.9 or later:

    python3 scripts/validate.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Top-level folders that are not marketing areas. Hidden folders are skipped too.
NOT_AREAS = {"guides", "templates", "scripts", "node_modules"}

SKILL_LINE_BUDGET = 500
MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
RESERVED_WORDS = ("claude", "anthropic")
NONPORTABLE_KEYS = ("allowed-tools", "compatibility")
GUIDE_SECTIONS = [
    "## What it's used for",
    "## At a glance",
    "## How it works",
    "## Setup",
    "## Using it",
    "## Troubleshooting",
]
# Paths to bundled files, such as references/rules.md. The lookbehind skips URLs.
BUNDLED_PATH_RE = re.compile(
    r"(?<![\w/.-])(?:references|scripts|assets)/[A-Za-z0-9_./-]*[A-Za-z0-9_-]"
)
VERSION_ROW_RE = re.compile(r"(?m)^\|\s*\*\*Version\*\*\s*\|\s*([^|]*?)\s*\|\s*$")
IGNORED_FILES = {".DS_Store", "Thumbs.db"}
EM_DASH = "\u2014"
PLACEHOLDER = "TODO:"

errors: list[str] = []


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def error(path: Path, message: str) -> None:
    errors.append(f"{rel(path)}: {message}")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse_frontmatter(text: str) -> dict:
    """Parse the small YAML subset skills use: scalars, block scalars, and one nested map."""
    match = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        raise ValueError("must start with YAML frontmatter between --- lines")
    lines = match.group(1).split("\n")
    data: dict = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key_match = re.match(r"^([A-Za-z0-9_-]+):(?:\s+(.*))?$", line)
        if not key_match:
            raise ValueError(f"can't read frontmatter line {line!r}")
        key, value = key_match.group(1), (key_match.group(2) or "").strip()
        if key in data:
            raise ValueError(f"duplicate frontmatter key {key!r}")

        block: list[str] = []
        while i < len(lines) and (lines[i].startswith((" ", "\t")) or not lines[i].strip()):
            block.append(lines[i])
            i += 1
        while block and not block[-1].strip():
            block.pop()

        if value[:1] in ("|", ">"):
            stripped = [b.strip() for b in block]
            joiner = "\n" if value.startswith("|") else " "
            data[key] = joiner.join(s for s in stripped if s)
        elif not value and block:
            nested = {}
            for b in block:
                if not b.strip():
                    continue
                nested_match = re.match(r"^\s+([A-Za-z0-9_-]+):(?:\s+(.*))?$", b)
                if not nested_match:
                    raise ValueError(f"can't read nested frontmatter line {b!r} under {key!r}")
                nested[nested_match.group(1)] = unquote((nested_match.group(2) or "").strip())
            data[key] = nested
        else:
            quoted = len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'"
            if not quoted and ": " in value:
                raise ValueError(
                    f"{key!r} has ': ' in an unquoted value, which breaks YAML. "
                    "Quote it or use the '>' block form."
                )
            if block:
                value = " ".join([value] + [b.strip() for b in block if b.strip()])
            data[key] = unquote(value)
    return data


def check_text_rules(path: Path, text: str, placeholders: bool, em_dashes: bool) -> None:
    if placeholders and PLACEHOLDER in text:
        line = text[: text.index(PLACEHOLDER)].count("\n") + 1
        error(path, f"has a leftover {PLACEHOLDER} placeholder (line {line})")
    if em_dashes and EM_DASH in text:
        line = text[: text.index(EM_DASH)].count("\n") + 1
        error(path, f"has an em dash (line {line}). Use a comma, colon, parentheses, or two sentences.")


def check_skill(area: Path, skill_dir: Path, seen_names: dict[str, Path]) -> str | None:
    """Validate one skill folder. Returns its metadata.version when readable."""
    skill_md = skill_dir / "SKILL.md"
    text = read(skill_md)
    check_text_rules(skill_md, text, placeholders=True, em_dashes=False)

    line_count = len(text.splitlines())
    if line_count > SKILL_LINE_BUDGET:
        error(skill_md, f"has {line_count} lines, over the {SKILL_LINE_BUDGET}-line limit. Move detail into references/.")

    # Every bundled file must be mentioned in SKILL.md, or Claude won't know to read it.
    for path in sorted(skill_dir.rglob("*")):
        if not path.is_file() or path == skill_md or path.name in IGNORED_FILES:
            continue
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue  # Python's own cache, ignored by .gitignore
        relpath = path.relative_to(skill_dir).as_posix()
        if path.name.lower() == "readme.md":
            error(path, "skill folders hold only what Claude needs. Put docs for people in the guide.")
        elif relpath not in text:
            error(path, "isn't mentioned in SKILL.md, so Claude won't know to read it")

    # Every bundled path SKILL.md mentions must exist.
    for mentioned in sorted(set(BUNDLED_PATH_RE.findall(text))):
        if not (skill_dir / mentioned).exists():
            error(skill_md, f"mentions {mentioned}, which doesn't exist in the skill folder")

    try:
        meta = parse_frontmatter(text)
    except ValueError as exc:
        error(skill_md, f"frontmatter: {exc}")
        return None

    name = meta.get("name", "")
    if not isinstance(name, str) or not name:
        error(skill_md, "frontmatter is missing name")
    else:
        if name != skill_dir.name:
            error(skill_md, f"name {name!r} must match its folder name {skill_dir.name!r}")
        if not NAME_RE.match(name):
            error(skill_md, f"name {name!r} must be lowercase kebab-case")
        if len(name) > MAX_NAME_LENGTH:
            error(skill_md, f"name is {len(name)} characters, over the {MAX_NAME_LENGTH}-character limit")
        for word in RESERVED_WORDS:
            if word in name:
                error(skill_md, f"name can't contain the reserved word {word!r}")
        if name in seen_names:
            error(skill_md, f"name {name!r} is already used by {rel(seen_names[name])}. Names must be unique across the repo.")
        else:
            seen_names[name] = skill_dir

    description = meta.get("description", "")
    if not isinstance(description, str) or not description.strip():
        error(skill_md, "frontmatter is missing description")
    else:
        if len(description) > MAX_DESCRIPTION_LENGTH:
            error(skill_md, f"description is {len(description)} characters, over the {MAX_DESCRIPTION_LENGTH}-character limit")
        if "<" in description or ">" in description:
            error(skill_md, "description can't contain angle brackets")

    for key in NONPORTABLE_KEYS:
        if key in meta:
            error(skill_md, f"remove the {key!r} frontmatter key. Other skill hosts don't support it.")

    if "version" in meta:
        error(skill_md, "put version under metadata (metadata.version), not at the top level")
    metadata = meta.get("metadata")
    version = metadata.get("version", "") if isinstance(metadata, dict) else ""
    if not SEMVER_RE.match(version):
        error(skill_md, 'frontmatter needs metadata.version as semver, such as "1.0.0"')
        return None
    return version


def check_guide(area: Path, skill_dir: Path, version: str | None) -> None:
    name = skill_dir.name
    guide = ROOT / "guides" / area.name / f"{name}.md"
    if not guide.exists():
        error(skill_dir, f"has no guide. Create {rel(guide)} from templates/guide-template.md.")
        return
    text = read(guide)
    check_text_rules(guide, text, placeholders=True, em_dashes=True)

    if not text.lstrip().startswith("# "):
        error(guide, "must start with a # title")
    if f"](../../{area.name}/{name}/)" not in text:
        error(guide, f"is missing the **Skill folder:** link to ../../{area.name}/{name}/")

    positions = []
    for heading in GUIDE_SECTIONS:
        found = re.search(rf"(?m)^{re.escape(heading)}\s*$", text)
        if not found:
            error(guide, f"is missing the section {heading!r}")
        else:
            positions.append(found.start())
    if len(positions) == len(GUIDE_SECTIONS) and positions != sorted(positions):
        error(guide, "sections are out of order. Follow templates/guide-template.md.")

    row = VERSION_ROW_RE.search(text)
    if not row:
        error(guide, "is missing the **Version** row in At a glance")
    elif version and row.group(1) != version:
        error(guide, f"Version row says {row.group(1)!r} but SKILL.md metadata.version is {version!r}")


def main() -> int:
    root_readme_path = ROOT / "README.md"
    root_readme = read(root_readme_path) if root_readme_path.exists() else ""
    if not root_readme:
        errors.append("README.md: missing")
    check_text_rules(root_readme_path, root_readme, placeholders=True, em_dashes=True)

    for path in sorted((ROOT / "templates").glob("*.md")):
        check_text_rules(path, read(path), placeholders=False, em_dashes=True)
    guides_readme = ROOT / "guides" / "README.md"
    if guides_readme.exists():
        check_text_rules(guides_readme, read(guides_readme), placeholders=True, em_dashes=True)

    areas = [
        p for p in sorted(ROOT.iterdir())
        if p.is_dir() and not p.name.startswith(".") and p.name not in NOT_AREAS
    ]
    skills: list[tuple[Path, Path]] = []
    seen_names: dict[str, Path] = {}

    for area in areas:
        if not NAME_RE.match(area.name):
            error(area, "area folder names must be lowercase kebab-case")
        if f"]({area.name}/)" not in root_readme:
            error(area, f"isn't linked from the root README's areas table as ]({area.name}/)")
        area_readme_path = area / "README.md"
        if not area_readme_path.exists():
            error(area, "has no README.md")
            area_readme = ""
        else:
            area_readme = read(area_readme_path)
            check_text_rules(area_readme_path, area_readme, placeholders=True, em_dashes=True)

        for child in sorted(area.iterdir()):
            if child.name in IGNORED_FILES or child == area_readme_path:
                continue
            if child.is_file():
                error(child, "only README.md and skill folders belong in an area folder")
                continue
            if not (child / "SKILL.md").exists():
                error(child, "has no SKILL.md. Skills go directly inside an area folder: <area>/<skill-name>/SKILL.md.")
                continue
            skills.append((area, child))

            version = check_skill(area, child, seen_names)
            check_guide(area, child, version)

            name = child.name
            if f"({name}/)" not in area_readme or f"../guides/{area.name}/{name}.md" not in area_readme:
                error(area_readme_path, f"must list {name} with links to ({name}/) and (../guides/{area.name}/{name}.md)")
            if f"guides/{area.name}/{name}.md" not in root_readme:
                error(root_readme_path, f"must list {name} in the Skills section with a link to guides/{area.name}/{name}.md")

    # A SKILL.md anywhere else won't be found by the indexes or installed the way the guides describe.
    skill_files = {child / "SKILL.md" for _, child in skills}
    for path in sorted(ROOT.rglob("SKILL.md")):
        if any(part.startswith(".") or part == "node_modules" for part in path.relative_to(ROOT).parts):
            continue
        if path not in skill_files:
            error(path, "is in the wrong place. Skills live at <area>/<skill-name>/SKILL.md.")

    # Every guide needs a skill.
    guides_dir = ROOT / "guides"
    skill_keys = {(a.name, s.name) for a, s in skills}
    if guides_dir.exists():
        for path in sorted(guides_dir.rglob("*")):
            if path.is_dir() or path.name in IGNORED_FILES or path == guides_readme:
                continue
            parts = path.relative_to(guides_dir).parts
            if len(parts) != 2 or path.suffix != ".md":
                error(path, "guides go at guides/<area>/<skill-name>.md")
            elif (parts[0], path.stem) not in skill_keys:
                error(path, f"has no matching skill at {parts[0]}/{path.stem}/SKILL.md")

    if errors:
        print(f"Found {len(errors)} problem(s):\n")
        for message in errors:
            print(f"  - {message}")
        return 1

    print(f"OK: {len(areas)} areas, {len(skills)} skills, all valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
