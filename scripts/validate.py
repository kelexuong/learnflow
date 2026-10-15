#!/usr/bin/env python3
"""Validate the LearnFlow package; this does not evaluate teaching behavior."""

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml


def validate(root: Path) -> list[str]:
    root = root.resolve()
    errors = []
    skill_file = root / "SKILL.md"
    if not skill_file.is_file():
        return ["SKILL.md is missing"]
    content = skill_file.read_text(encoding="utf-8")
    frontmatter = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", content, re.S)
    if frontmatter is None:
        return ["SKILL.md must start with YAML frontmatter"]
    try:
        meta = yaml.safe_load(frontmatter.group(1))
    except yaml.YAMLError:
        return ["SKILL.md frontmatter is invalid YAML"]
    if not isinstance(meta, dict):
        return ["SKILL.md frontmatter must be a mapping"]
    allowed = {"name", "description", "license", "allowed-tools", "metadata"}
    if set(meta) - allowed:
        errors.append("SKILL.md has unsupported frontmatter keys")
    name = meta.get("name")
    if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) or len(name) > 64:
        errors.append("Skill name must use lowercase hyphenated words, at most 64 characters")
    elif name != root.name:
        errors.append("Skill name must match its directory name")
    description = meta.get("description")
    if not isinstance(description, str) or not description.strip() or len(description) > 1024 or "<" in description or ">" in description:
        errors.append("Skill description must contain 1-1024 characters without angle brackets")
    if re.search(r"(?m)^\s*\[TODO:[^\n]*\]\s*$", content):
        errors.append("SKILL.md contains an unfinished scaffold placeholder")

    def local_target(source: Path, target: str):
        parts = urlsplit(target)
        if parts.scheme or parts.netloc or not parts.path:
            return None
        resolved = (source.parent / unquote(parts.path)).resolve()
        if not resolved.is_relative_to(root):
            errors.append(f"{source.relative_to(root)}: reference leaves skill directory")
        elif not resolved.is_file():
            errors.append(f"{source.relative_to(root)}: missing local file {target}")
        return resolved

    for md in sorted(root.rglob("*.md")):
        if any(part.startswith(".") for part in md.relative_to(root).parts):
            continue
        for target in re.findall(r"!?\[[^\]\n]*\]\(([^)\s]+)\)", md.read_text(encoding="utf-8")):
            local_target(md, target)

    config_file = root / "agents" / "openai.yaml"
    try:
        config = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        errors.append("agents/openai.yaml is missing or invalid YAML")
        return errors
    if not isinstance(config, dict) or not isinstance(config.get("interface"), dict):
        errors.append("agents/openai.yaml must contain an interface mapping")
        return errors
    interface = config["interface"]
    if not isinstance(interface.get("display_name"), str) or not interface["display_name"].strip():
        errors.append("interface.display_name must be a nonempty string")
    short = interface.get("short_description")
    if not isinstance(short, str) or not 25 <= len(short) <= 64:
        errors.append("interface.short_description must contain 25-64 characters")
    for key in ("icon_small", "icon_large"):
        path = interface.get(key)
        if path is None:
            continue
        if not isinstance(path, str) or urlsplit(path).scheme or urlsplit(path).netloc or Path(path).is_absolute():
            errors.append(f"interface.{key} must be a local relative asset path")
            continue
        icon = local_target(root / "SKILL.md", path)
        if icon and icon.is_relative_to(root) and icon.is_file() and icon.suffix == ".svg":
            try:
                svg = ET.parse(icon).getroot()
                if svg.tag != "{http://www.w3.org/2000/svg}svg":
                    errors.append(f"{path} is not an SVG document")
            except ET.ParseError:
                errors.append(f"{path} is invalid SVG XML")
    policy = config.get("policy", {})
    if not isinstance(policy, dict):
        errors.append("policy must be a mapping")
    elif "allow_implicit_invocation" in policy and not isinstance(policy["allow_implicit_invocation"], bool):
        errors.append("policy.allow_implicit_invocation must be boolean")
    return errors


if __name__ == "__main__":
    skill_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
    issues = validate(skill_root)
    for issue in issues:
        print(f"FAIL: {issue}")
    if not issues:
        print("PASS: LearnFlow metadata, local references, interface and icons are valid.")
    sys.exit(bool(issues))
