"""Webhook signature verification and routing."""

from __future__ import annotations

import hashlib
import hmac
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from qreviews.dashboard.app import create_app
from qreviews.webhook import _verify_signature


def test_verify_signature_accepts_bare_hex():
    secret = "supersecret"
    body = b'{"x":1}'
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert _verify_signature(body, secret, sig) is True


def test_verify_signature_accepts_prefixed():
    secret = "supersecret"
    body = b'{"x":1}'
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert _verify_signature(body, secret, sig) is True


def test_verify_signature_rejects_bad():
    assert _verify_signature(b"hello", "secret", "deadbeef") is False
    assert _verify_signature(b"hello", "secret", None) is False


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PHABRICATOR_API_TOKEN", "api-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("PHABRICATOR_WEBHOOK_SECRET", "")  # accept unsigned in tests

    # Write a minimal config.yaml.
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        """
phabricator:
  base_url: https://phab.example.test/api/
anthropic:
  scoring_model: claude-haiku-4-5
  review_model: claude-sonnet-4-6
defaults:
  risk_threshold: 2
  complexity_threshold: 2
storage:
  db_path: {db}
reviewer_groups:
  - slug: ip-protection-reviewers
    enabled: true
""".format(db=str(tmp_path / "test.db"))
    )
    app = create_app(config_path=str(cfg_path))
    return TestClient(app)


def test_webhook_ignores_non_revision_payload(client):
    r = client.post("/phabricator/herald", json={"objectPHID": "PHID-USER-1"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "non-revision" in body["ignored"]


def test_webhook_invalid_json(client):
    r = client.post(
        "/phabricator/herald", content=b"not json", headers={"content-type": "application/json"}
    )
    assert r.status_code == 400


def test_webhook_rejects_bad_signature(client, monkeypatch):
    monkeypatch.setenv("PHABRICATOR_WEBHOOK_SECRET", "real-secret")
    r = client.post(
        "/phabricator/herald",
        json={"objectPHID": "PHID-DREV-1"},
        headers={"X-Phabricator-Webhook-Signature": "deadbeef"},
    )
    assert r.status_code == 401


def test_webhook_routes_revision_to_poller(client, monkeypatch):
    """When a DREV payload arrives, the webhook calls Poller.process_revision."""
    from qreviews import webhook as wh

    fake_rev = MagicMock()
    fake_rev.phid = "PHID-DREV-42"
    fake_rev.display_id = "D42"
    fake_rev.reviewer_phids = ["PHID-PROJ-ip"]

    fake_poller = MagicMock()
    fake_poller.conduit.search_revisions_by_phids.return_value = [fake_rev]
    fake_poller.resolve_group_phid.return_value = "PHID-PROJ-ip"
    fake_poller.process_revision.return_value = MagicMock(
        revision_id=42, posted=True, skipped_reason=None, risk=1, complexity=1
    )

    with patch.object(wh, "Poller", return_value=fake_poller):
        r = client.post("/phabricator/herald", json={"objectPHID": "PHID-DREV-42"})

    assert r.status_code == 200
    body = r.json()
    assert body["posted"] is True
    assert body["revision"] == "D42"
    fake_poller.process_revision.assert_called_once()
