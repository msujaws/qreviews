"""Skill loading and supplemental-skill discovery."""

from __future__ import annotations

from pathlib import Path

from qreviews.skills import _strip_frontmatter, discover_skill_dirs, load_skill


def test_strip_frontmatter_removes_yaml_block():
    text = "---\nname: foo\ndescription: bar\n---\n# Heading\nbody"
    out = _strip_frontmatter(text)
    assert out.startswith("# Heading")
    assert "description" not in out


def test_strip_frontmatter_passthrough_without_block():
    text = "# Heading\nno frontmatter here"
    assert _strip_frontmatter(text) == text


def test_load_skill_reads_and_strips(tmp_path: Path):
    p = tmp_path / "SKILL.md"
    p.write_text("---\ndescription: x\n---\n# Real content\nblah")
    # Bypass lru_cache cross-test pollution by using a unique path each test.
    body = load_skill(str(p))
    assert body.startswith("# Real content")


def test_discover_skill_dirs_derives_slugs(tmp_path: Path):
    (tmp_path / "desktop-theme-review").mkdir()
    (tmp_path / "desktop-theme-review" / "SKILL.md").write_text("content")
    (tmp_path / "accessibility-frontend-review").mkdir()
    (tmp_path / "accessibility-frontend-review" / "SKILL.md").write_text("content")
    # Dir without SKILL.md should be ignored.
    (tmp_path / "empty-dir").mkdir()
    # Non-dir entry should be ignored.
    (tmp_path / "stray.txt").write_text("nope")

    out = discover_skill_dirs(tmp_path)
    assert out == {
        "desktop-theme-reviewers": tmp_path / "desktop-theme-review" / "SKILL.md",
        "accessibility-frontend-reviewers": tmp_path
        / "accessibility-frontend-review"
        / "SKILL.md",
    }


def test_discover_skill_dirs_missing_root_returns_empty(tmp_path: Path):
    assert discover_skill_dirs(tmp_path / "does-not-exist") == {}
