"""Skills: standard SKILL.md directories on disk, our config in the database.

The format is Agent Skills' ``SKILL.md`` and we follow it exactly -- no extra
frontmatter keys. The spec allows two required fields and nothing else:

    name         <=64 chars, lowercase letters / digits / hyphens only
    description  non-empty, <=1024 chars, must say both what it does and
                 when to use it (this is what the model matches against)

Our own settings -- which scopes a skill applies to, whether it's enabled,
what sandbox level the user granted -- deliberately do **not** live in that
file. Two reasons:

1. The spec has no extension mechanism. Inventing keys makes a dialect, and
   then third-party skills don't drop in and ours don't travel.
2. They aren't properties of the skill anyway. Which scopes it applies to is
   how *we* use it -- one user may want it for drafting, another for
   polishing. Sandbox permission is something the user *grants*; an app
   doesn't get to declare it has camera access.

So: content on disk, untouched; configuration in ``skill_config``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config import get_settings

NAME_RE = re.compile(r"^[a-z0-9-]{1,64}$")
MAX_DESCRIPTION = 1024

# Level 2 of progressive disclosure has a budget; a skill body that blows
# past it defeats the point of loading on demand.
MAX_BODY_CHARS = 20_000

# How many skills the model may pull in during one run. Without a ceiling it
# will happily load five and fill the window. Same reasoning as the chart
# tools refusing to draw uninformative charts: a tool that says no is more
# reliable than an instruction to show restraint.
MAX_LOADED_SKILLS = 3


@dataclass(frozen=True)
class Skill:
    """A parsed SKILL.md plus the config we keep alongside it."""

    slug: str                       # directory name == frontmatter ``name``
    name: str
    description: str
    body: str
    path: Path
    # -- our config, from the database, not from the file --
    enabled: bool = True
    scopes: tuple[str, ...] = ()
    sandbox: str = "none"           # none | compute | files
    source: str = "user"            # builtin | user | imported


class SkillFormatError(ValueError):
    """SKILL.md violates the spec. Raised at import time, never at run time --
    a malformed skill must be rejected when the user adds it, not silently
    skipped later when they wonder why it never fires."""


def parse_skill_md(text: str) -> tuple[str, str, str]:
    """Split a SKILL.md into (name, description, body). Validates the spec.

    Only ``name`` and ``description`` are read. Any other frontmatter key is
    ignored rather than rejected -- a third-party skill carrying keys some
    other tool understands is still perfectly usable here.
    """
    match = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n?(.*)$", text.strip(), re.S)
    if not match:
        raise SkillFormatError("SKILL.md must start with YAML frontmatter")
    front, body = match.group(1), match.group(2).strip()

    fields = _parse_frontmatter(front)
    name = fields.get("name", "").strip()
    description = fields.get("description", "").strip()

    if not NAME_RE.match(name):
        raise SkillFormatError(
            f"name {name!r} is invalid: at most 64 characters, lowercase "
            f"letters, digits and hyphens only")
    if "anthropic" in name or "claude" in name:
        raise SkillFormatError(f"name {name!r} may not contain reserved words")
    if not description:
        raise SkillFormatError("description is required")
    if len(description) > MAX_DESCRIPTION:
        raise SkillFormatError(
            f"description is {len(description)} characters, limit is {MAX_DESCRIPTION}")
    if "<" in name or "<" in description:
        raise SkillFormatError("name and description may not contain XML tags")

    return name, description, body


def _parse_frontmatter(text: str) -> dict[str, str]:
    """Minimal YAML: ``key: value`` plus folded/literal block scalars.

    Not a real YAML parser and doesn't need to be -- we read exactly two
    string fields. Block scalars *are* handled because real SKILL.md files
    routinely write ``description: >`` with the text on following lines, and
    a parser that misses that returns a lone ``>``, which is worse than
    returning nothing.
    """
    fields: dict[str, str] = {}
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", lines[i])
        if not m:
            i += 1
            continue
        key, rest = m.group(1), m.group(2).strip()
        if re.fullmatch(r"[|>][+-]?", rest):
            folded = rest[0] == ">"
            parts: list[str] = []
            i += 1
            while i < len(lines) and (not lines[i].strip() or re.match(r"^\s+\S", lines[i])):
                parts.append(lines[i].strip())
                i += 1
            fields[key] = (" " if folded else "\n").join(p for p in parts if p)
            continue
        fields[key] = rest.strip("'\"")
        i += 1
    return fields


def skills_root(user: str) -> Path:
    return Path(get_settings().kite_data_dir) / user / "skills"


def load_all(user: str) -> list[Skill]:
    """Every installed skill, with config merged in.

    A directory that fails to parse is skipped rather than raised -- one bad
    skill must not stop the other twelve from working. Import-time validation
    is where malformed input gets rejected loudly.
    """
    from . import store

    root = skills_root(user)
    if not root.is_dir():
        return []
    config = store.skill_configs(user)
    out: list[Skill] = []
    for directory in sorted(root.iterdir()):
        md = directory / "SKILL.md"
        if not directory.is_dir() or not md.is_file():
            continue
        try:
            name, description, body = parse_skill_md(md.read_text(encoding="utf-8"))
        except (SkillFormatError, OSError, UnicodeDecodeError):
            continue
        cfg = config.get(directory.name, {})
        out.append(Skill(
            slug=directory.name, name=name, description=description,
            body=body[:MAX_BODY_CHARS], path=directory,
            enabled=bool(cfg.get("enabled", True)),
            scopes=tuple(cfg.get("scopes") or ()),
            sandbox=str(cfg.get("sandbox") or "none"),
            source=str(cfg.get("source") or "user"),
        ))
    return out


def for_scope(user: str, scope: str) -> tuple[list[Skill], list[Skill]]:
    """Split enabled skills into (inject directly, list in the menu).

    Reading of the rule: **having scopes configured means the user has said
    "I know when this applies"**. Those get injected when they match and
    stay out of the way when they don't. Skills with no scopes -- which is
    what a freshly installed third-party skill looks like -- go in the menu
    and the model decides.

    The two lists are disjoint on purpose: a skill already in the prompt must
    not also be offered for loading, or the model burns a tool call fetching
    what it has.
    """
    enabled = [s for s in load_all(user) if s.enabled]
    injected = [s for s in enabled if s.scopes and scope and scope in s.scopes]
    listed = [s for s in enabled if not s.scopes]
    return injected, listed


def read_body(user: str, slug: str) -> str | None:
    for skill in load_all(user):
        if skill.slug == slug or skill.name == slug:
            return skill.body
    return None


def read_reference(user: str, slug: str, relative: str) -> str | None:
    """Read one bundled file (level 3 of progressive disclosure).

    Path traversal is rejected: the model chooses this argument, and a skill
    body is untrusted text that could ask for ``../../../etc/passwd``.
    """
    root = skills_root(user) / slug
    try:
        target = (root / relative).resolve()
        target.relative_to(root.resolve())
    except (ValueError, OSError):
        return None
    if not target.is_file() or target.suffix.lower() not in {".md", ".txt", ".json", ".csv"}:
        return None
    try:
        return target.read_text(encoding="utf-8")[:MAX_BODY_CHARS]
    except (OSError, UnicodeDecodeError):
        return None
