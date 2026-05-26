"""Read SKILL.md content from configured paths and cache it.

Skills are normal Markdown files (with YAML frontmatter) authored for Claude
Code. For server-side review we strip the frontmatter and feed the body as a
system prompt — the same content Claude Code would have loaded.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)


def _strip_frontmatter(text: str) -> str:
    """Remove a leading `---\\n…\\n---\\n` YAML block, if present."""
    if not text.startswith("---"):
        return text
    lines = text.splitlines(keepends=True)
    if not lines or not lines[0].startswith("---"):
        return text
    for idx in range(1, len(lines)):
        if lines[idx].startswith("---"):
            return "".join(lines[idx + 1 :]).lstrip()
    return text


@lru_cache(maxsize=32)
def load_skill(skill_path: str) -> str:
    p = Path(skill_path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"skill not found: {skill_path}")
    raw = p.read_text()
    body = _strip_frontmatter(raw)
    log.info("loaded skill %s (%d chars)", skill_path, len(body))
    return body


def discover_skill_dirs(skills_root: Path) -> dict[str, Path]:
    """Scan a `skills/` root and return `{derived_slug: skill_md_path}`.

    A subdirectory `<name>/` with a `SKILL.md` inside maps to the
    Phabricator project slug `<name>.removesuffix("-review") + "-reviewers"`.
    This matches the directory-naming convention used by both
    qreviews/skills/ and the imported custom-module-reviewer outputs.
    Returns an empty dict if the root doesn't exist.
    """
    if not skills_root.exists() or not skills_root.is_dir():
        return {}
    out: dict[str, Path] = {}
    for child in sorted(skills_root.iterdir()):
        if not child.is_dir():
            continue
        skill_file = child / "SKILL.md"
        if not skill_file.is_file():
            continue
        slug = child.name.removesuffix("-review") + "-reviewers"
        out[slug] = skill_file
    return out
