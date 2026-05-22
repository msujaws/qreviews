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
