"""Conduit client — verifies request shape (api.token as form field, PHP-bracket encoded params)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import requests

from qreviews.conduit import ConduitClient, ConduitError, Diff, Revision, _flatten_params


def _make_client(session, **overrides) -> ConduitClient:
    kw = {
        "base_url": "https://phab.example.test/api/",
        "api_token": "api-test-token",
        "session": session,
        "min_call_interval": 0.0,  # disable throttle in tests
    }
    kw.update(overrides)
    return ConduitClient(**kw)


@pytest.fixture
def fake_session():
    s = MagicMock(spec=requests.Session)
    s.headers = {}
    return s


def _ok_response(payload) -> MagicMock:
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = {"result": payload, "error_code": None, "error_info": None}
    r.raise_for_status = MagicMock()
    r.headers = {}
    return r


def _err_response(status: int = 200, code: str = "ERR-CONDUIT", info: str = "broken") -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json.return_value = {"result": None, "error_code": code, "error_info": info}
    r.raise_for_status = MagicMock()
    r.headers = {}
    return r


def test_flatten_params_scalar():
    assert _flatten_params({"limit": 1}) == [("limit", "1")]


def test_flatten_params_nested_dict_and_list():
    out = _flatten_params({"constraints": {"slugs": ["foo", "bar"]}})
    assert ("constraints[slugs][0]", "foo") in out
    assert ("constraints[slugs][1]", "bar") in out


def test_flatten_params_transactions():
    out = _flatten_params(
        {"transactions": [{"type": "comment", "value": "hi"}]}
    )
    assert ("transactions[0][type]", "comment") in out
    assert ("transactions[0][value]", "hi") in out


def test_flatten_params_drops_none():
    out = _flatten_params({"a": None, "b": 1})
    assert ("a", "1") not in out
    assert ("b", "1") in out


def test_flatten_params_bool():
    assert ("x", "true") in _flatten_params({"x": True})
    assert ("y", "false") in _flatten_params({"y": False})


def test_call_uses_php_bracket_encoding(fake_session):
    fake_session.post.return_value = _ok_response({"data": []})
    c = _make_client(fake_session)
    c.call("project.search", {"constraints": {"slugs": ["foo"]}, "limit": 1})

    fake_session.post.assert_called_once()
    args, kwargs = fake_session.post.call_args
    assert args[0] == "https://phab.example.test/api/project.search"
    data = kwargs["data"]
    # data is a list of (key, value) tuples now (PHP-bracket encoded).
    assert ("api.token", "api-test-token") in data
    assert ("constraints[slugs][0]", "foo") in data
    assert ("limit", "1") in data


def test_call_raises_on_conduit_error(fake_session):
    fake_session.post.return_value = _err_response(code="ERR-INVALID-AUTH", info="bad token")
    c = _make_client(fake_session)
    with pytest.raises(ConduitError, match="ERR-INVALID-AUTH"):
        c.call("project.search")


def test_resolve_project_phid(fake_session):
    fake_session.post.return_value = _ok_response(
        {"data": [{"phid": "PHID-PROJ-abc123"}]}
    )
    c = _make_client(fake_session)
    assert c.resolve_project_phid("ip-protection-reviewers") == "PHID-PROJ-abc123"


def test_search_revisions_parses_response(fake_session):
    fake_session.post.return_value = _ok_response(
        {
            "data": [
                {
                    "phid": "PHID-DREV-1",
                    "id": 555,
                    "fields": {
                        "title": "Fix the thing",
                        "summary": "It was broken.",
                        "status": {"value": "needs-review"},
                        "authorPHID": "PHID-USER-1",
                        "repositoryPHID": "PHID-REPO-1",
                        "bugzilla.bug-id": "12345",
                        "dateCreated": 1716000000,
                        "dateModified": 1716000100,
                    },
                    "attachments": {
                        "reviewers": {
                            "reviewers": [
                                {"reviewerPHID": "PHID-PROJ-newtab"},
                                {"reviewerPHID": "PHID-USER-bob"},
                            ]
                        }
                    },
                }
            ]
        }
    )
    c = _make_client(fake_session)
    revs = c.search_revisions(reviewer_phids=["PHID-PROJ-newtab"])
    assert len(revs) == 1
    r: Revision = revs[0]
    assert r.id == 555
    assert r.display_id == "D555"
    assert r.bug_id == "12345"
    assert r.reviewer_phids == ["PHID-PROJ-newtab", "PHID-USER-bob"]


def test_get_raw_diff(fake_session):
    fake_session.post.return_value = _ok_response("diff --git a/foo b/foo\n@@ -1 +1 @@\n-old\n+new")
    c = _make_client(fake_session)
    text = c.get_raw_diff(42)
    assert "diff --git" in text


def test_post_comment_sends_transaction(fake_session):
    fake_session.post.return_value = _ok_response({"object": {"id": 555}, "transactions": []})
    c = _make_client(fake_session)
    c.post_comment("PHID-DREV-1", "hello")
    data = fake_session.post.call_args[1]["data"]
    # PHP-bracket-encoded fields:
    assert ("objectIdentifier", "PHID-DREV-1") in data
    assert ("transactions[0][type]", "comment") in data
    assert ("transactions[0][value]", "hello") in data


def test_retry_after_on_429(fake_session, monkeypatch):
    """429 with Retry-After should be respected; subsequent 200 succeeds."""
    rate_limited = MagicMock()
    rate_limited.status_code = 429
    rate_limited.headers = {"Retry-After": "0"}
    fake_session.post.side_effect = [rate_limited, _ok_response({"data": []})]
    sleeps: list[float] = []
    monkeypatch.setattr("qreviews.conduit.time.sleep", lambda s: sleeps.append(s))
    c = _make_client(fake_session)
    c.call("project.search")
    assert fake_session.post.call_count == 2
    assert 0.0 in sleeps  # honored Retry-After: 0


def test_diff_from_search_result():
    d = Diff.from_search_result(
        {"phid": "PHID-DIFF-7", "id": 7, "fields": {"revisionPHID": "PHID-DREV-1", "dateCreated": 1}}
    )
    assert d.id == 7
    assert d.revision_phid == "PHID-DREV-1"
