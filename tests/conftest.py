"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from qreviews.config import (
    AnthropicConfig,
    Config,
    DashboardConfig,
    Defaults,
    PhabricatorConfig,
    ReviewerGroup,
    StorageConfig,
)
from qreviews.state import Store


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def store(tmp_db: Path) -> Store:
    s = Store(tmp_db)
    s.init_schema()
    yield s
    s.close()


@pytest.fixture
def config(tmp_db: Path) -> Config:
    return Config(
        phabricator=PhabricatorConfig(
            base_url="https://phab.example.test/api/",
            poll_interval_seconds=60,
            user_agent="qreviews-test/0.1",
            max_diff_bytes=200_000,
        ),
        anthropic=AnthropicConfig(
            scoring_model="claude-haiku-4-5",
            review_model="claude-sonnet-4-6",
        ),
        defaults=Defaults(risk_threshold=2, complexity_threshold=2),
        dashboard=DashboardConfig(),
        storage=StorageConfig(db_path=str(tmp_db)),
        reviewer_groups=[
            ReviewerGroup(
                slug="ip-protection-reviewers",
                enabled=True,
                skill_path=None,  # tests stub skills
            ),
            ReviewerGroup(slug="home-newtab-reviewers", enabled=False),
        ],
    )
