"""Configuration loading: config.yaml + .env."""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator


class PhabricatorConfig(BaseModel):
    base_url: str
    poll_interval_seconds: int = 3600
    user_agent: str = "qreviews-bot/0.1"
    watermark_overlap_seconds: int = 60
    max_diff_bytes: int = 200_000
    # PHIDs of user-account bots whose comments should not count as human
    # engagement (Lando, BMO-bot, internal CI, etc.). Only PHID-USER- accounts
    # count as human commenters, so application actors (Herald, etc.) are
    # filtered automatically and need not be listed here.
    ignore_commenter_phids: list[str] = Field(default_factory=list)
    # Project slug that Mozilla uses to mark security-sensitive revisions.
    # Revisions tagged with this project are skipped entirely — no diff
    # fetch, no scoring, no review. Exposed as config so a future rename on
    # Phabricator's side doesn't require a code change.
    secure_revision_project_slug: str = "secure-revision"

    @field_validator("base_url")
    @classmethod
    def _trailing_slash(cls, v: str) -> str:
        return v if v.endswith("/") else v + "/"


class AnthropicConfig(BaseModel):
    scoring_model: str
    review_model: str
    scoring_max_tokens: int = 1024
    review_max_tokens: int = 4096


class Defaults(BaseModel):
    risk_threshold: int = 3
    complexity_threshold: int = 3


class DashboardConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8765
    # Optional. When set, posted Phabricator comments include a link back to
    # this URL so reviewers can see live metrics for the bot. Override at
    # deploy time via the QREVIEWS_DASHBOARD_URL env var.
    public_url: str | None = None


class StorageConfig(BaseModel):
    db_path: str = "qreviews.db"


class ReviewerGroup(BaseModel):
    slug: str
    enabled: bool = False
    skill_path: str | None = None
    risk_threshold: int | None = None
    complexity_threshold: int | None = None
    # When true (default), only review revisions whose author is a member of
    # the Phabricator project corresponding to this group. Set to false to
    # open the group up to external authors.
    restrict_to_member_authors: bool = True
    # When true, treat this group as a Phabricator round-robin "rotation". For
    # such a group the group PHID is not held as a reviewer during needs-review
    # — Phabricator swaps in a single rotated member carrying the group's
    # blocking slot. The poller then discovers revisions by member PHID and
    # scopes to the rotation assignment (a member holding a blocking reviewer
    # slot) instead of by the group PHID, which never matches.
    rotation: bool = False

    def effective_risk_threshold(self, defaults: Defaults) -> int:
        return self.risk_threshold if self.risk_threshold is not None else defaults.risk_threshold

    def effective_complexity_threshold(self, defaults: Defaults) -> int:
        return (
            self.complexity_threshold
            if self.complexity_threshold is not None
            else defaults.complexity_threshold
        )


class Config(BaseModel):
    phabricator: PhabricatorConfig
    anthropic: AnthropicConfig
    defaults: Defaults = Field(default_factory=Defaults)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    reviewer_groups: list[ReviewerGroup] = Field(default_factory=list)

    def enabled_groups(self) -> list[ReviewerGroup]:
        return [g for g in self.reviewer_groups if g.enabled]

    def group_by_slug(self, slug: str) -> ReviewerGroup | None:
        for g in self.reviewer_groups:
            if g.slug == slug:
                return g
        return None


class Secrets(BaseModel):
    phabricator_api_token: str
    anthropic_api_key: str


def load_config(config_path: str | Path = "config.yaml") -> Config:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"config file not found: {path}")
    with path.open("r") as f:
        raw = yaml.safe_load(f)

    # Env-var overrides so containerized deployments (Railway, etc.) can point
    # the DB at a mounted volume and change polling cadence without forking
    # config.yaml.
    if env_db := os.environ.get("QREVIEWS_DB_PATH"):
        raw.setdefault("storage", {})["db_path"] = env_db
    if env_interval := os.environ.get("QREVIEWS_POLL_INTERVAL_SECONDS"):
        raw.setdefault("phabricator", {})["poll_interval_seconds"] = int(env_interval)
    if env_url := os.environ.get("QREVIEWS_DASHBOARD_URL"):
        raw.setdefault("dashboard", {})["public_url"] = env_url

    return Config.model_validate(raw)


# The .env.example placeholders are a real prefix followed by only `x`s
# (e.g. `api-xxxxxxxxxxxxxxxxxxxxxxxxxxxx`). A real token is random, so it never
# matches these — but a deploy that copied .env.example without filling it in
# would otherwise reach Conduit with invalid auth and spam Phabricator.
_PLACEHOLDER_PATTERNS = {
    "PHABRICATOR_API_TOKEN": re.compile(r"^api-x+$", re.IGNORECASE),
    "ANTHROPIC_API_KEY": re.compile(r"^sk-ant-x+$", re.IGNORECASE),
}


def load_secrets(env_path: str | Path | None = ".env") -> Secrets:
    """Load secrets from .env (if present) + the process environment.

    Process environment takes precedence over .env so deployments can override.
    """
    if env_path is not None and Path(env_path).exists():
        load_dotenv(env_path, override=False)

    token = os.environ.get("PHABRICATOR_API_TOKEN", "").strip()
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not token:
        raise RuntimeError("PHABRICATOR_API_TOKEN is not set (check .env or environment)")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set (check .env or environment)")
    if _PLACEHOLDER_PATTERNS["PHABRICATOR_API_TOKEN"].match(token):
        raise RuntimeError(
            "PHABRICATOR_API_TOKEN is the .env.example placeholder, not a real token"
        )
    if _PLACEHOLDER_PATTERNS["ANTHROPIC_API_KEY"].match(key):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is the .env.example placeholder, not a real key"
        )
    return Secrets(phabricator_api_token=token, anthropic_api_key=key)
