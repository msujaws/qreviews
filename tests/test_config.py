"""Config loading + threshold fallback."""

from __future__ import annotations

from pathlib import Path

import pytest

from qreviews.config import Config, load_config, load_secrets


def test_load_real_config():
    """The repo's own config.yaml should parse."""
    repo_root = Path(__file__).parent.parent
    cfg = load_config(repo_root / "config.yaml")
    assert cfg.phabricator.base_url.startswith("https://phabricator.services.mozilla.com")
    assert cfg.phabricator.base_url.endswith("/")
    assert cfg.defaults.risk_threshold == 3
    assert cfg.defaults.complexity_threshold == 3
    slugs = [g.slug for g in cfg.reviewer_groups]
    assert "ip-protection-reviewers" in slugs
    assert "home-newtab-reviewers" in slugs


def test_threshold_fallback(config: Config):
    g = config.group_by_slug("ip-protection-reviewers")
    assert g.effective_risk_threshold(config.defaults) == 2
    g.risk_threshold = 5
    assert g.effective_risk_threshold(config.defaults) == 5


def test_secrets_required(tmp_path, monkeypatch):
    monkeypatch.delenv("PHABRICATOR_API_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="PHABRICATOR_API_TOKEN"):
        load_secrets(tmp_path / "nonexistent.env")


def test_secrets_loads_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("PHABRICATOR_API_TOKEN", "api-test-token")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    s = load_secrets(tmp_path / "nonexistent.env")
    assert s.phabricator_api_token == "api-test-token"
    assert s.anthropic_api_key == "sk-ant-test"


def test_enabled_groups(config: Config):
    enabled = config.enabled_groups()
    assert len(enabled) == 1
    assert enabled[0].slug == "ip-protection-reviewers"


def test_dashboard_public_url_env_override(tmp_path, monkeypatch):
    """QREVIEWS_DASHBOARD_URL overrides dashboard.public_url at load time."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "phabricator:\n"
        "  base_url: https://phab.example.test/api/\n"
        "anthropic:\n"
        "  scoring_model: claude-haiku-4-5\n"
        "  review_model: claude-sonnet-4-6\n"
    )
    monkeypatch.setenv("QREVIEWS_DASHBOARD_URL", "https://qreviews.example")
    cfg = load_config(cfg_path)
    assert cfg.dashboard.public_url == "https://qreviews.example"


def test_secure_revision_project_slug_default(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "phabricator:\n"
        "  base_url: https://phab.example.test/api/\n"
        "anthropic:\n"
        "  scoring_model: claude-haiku-4-5\n"
        "  review_model: claude-sonnet-4-6\n"
    )
    cfg = load_config(cfg_path)
    assert cfg.phabricator.secure_revision_project_slug == "secure-revision"


def test_secure_revision_project_slug_overridable(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "phabricator:\n"
        "  base_url: https://phab.example.test/api/\n"
        "  secure_revision_project_slug: mozilla-secure\n"
        "anthropic:\n"
        "  scoring_model: claude-haiku-4-5\n"
        "  review_model: claude-sonnet-4-6\n"
    )
    cfg = load_config(cfg_path)
    assert cfg.phabricator.secure_revision_project_slug == "mozilla-secure"


def test_dashboard_public_url_defaults_none(tmp_path, monkeypatch):
    """Without the env var or yaml field, public_url stays None."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "phabricator:\n"
        "  base_url: https://phab.example.test/api/\n"
        "anthropic:\n"
        "  scoring_model: claude-haiku-4-5\n"
        "  review_model: claude-sonnet-4-6\n"
    )
    monkeypatch.delenv("QREVIEWS_DASHBOARD_URL", raising=False)
    cfg = load_config(cfg_path)
    assert cfg.dashboard.public_url is None
