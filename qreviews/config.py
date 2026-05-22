"""Configuration loading: config.yaml + .env."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator


class PhabricatorConfig(BaseModel):
    base_url: str
    poll_interval_seconds: int = 180
    user_agent: str = "qreviews-bot/0.1"
    watermark_overlap_seconds: int = 60
    max_diff_bytes: int = 200_000

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


class StorageConfig(BaseModel):
    db_path: str = "qreviews.db"


class ReviewerGroup(BaseModel):
    slug: str
    enabled: bool = False
    skill_path: str | None = None
    risk_threshold: int | None = None
    complexity_threshold: int | None = None

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

    return Config.model_validate(raw)


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
    return Secrets(phabricator_api_token=token, anthropic_api_key=key)
