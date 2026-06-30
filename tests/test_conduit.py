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


def test_conduit_error_redacts_token():
    """Phabricator echoes the token in error_info; it must not reach logs."""
    err = ConduitError(
        "ERR-INVALID-AUTH",
        'API token "api-deadbeef1234567890abcdef" is not valid.',
        "project.search",
    )
    assert "api-deadbeef1234567890abcdef" not in str(err)
    assert "api-‹redacted›" in str(err)
    # The raw info is still available for programmatic inspection.
    assert "api-deadbeef1234567890abcdef" in err.info


def test_session_disables_keep_alive():
    """The poller idles for an hour between bursts; a pooled keep-alive socket
    goes stale and stalls the next call for the full read timeout. Connection:
    close means there is never an idle socket to reuse."""
    c = ConduitClient(base_url="https://phab.example.test/api/", api_token="api-test-token")
    assert c.session.headers["Connection"] == "close"
    assert c.session.headers["User-Agent"]


def test_call_retries_after_timeout(fake_session, monkeypatch):
    """A single read timeout (the symptom of a stale socket) is retried on a
    fresh connection and recovers — the safety net behind the keep-alive fix."""
    monkeypatch.setattr("qreviews.conduit.time.sleep", lambda *a, **k: None)
    fake_session.post.side_effect = [
        requests.Timeout("read timed out"),
        _ok_response({"data": [1]}),
    ]
    c = _make_client(fake_session)
    assert c.call("differential.revision.search") == {"data": [1]}
    assert fake_session.post.call_count == 2


def test_resolve_project_phid(fake_session):
    fake_session.post.return_value = _ok_response(
        {"data": [{"phid": "PHID-PROJ-abc123"}]}
    )
    c = _make_client(fake_session)
    assert c.resolve_project_phid("ip-protection-reviewers") == "PHID-PROJ-abc123"


def test_resolve_project_phids_batched(fake_session):
    fake_session.post.return_value = _ok_response(
        {
            "data": [
                {"phid": "PHID-PROJ-a", "fields": {"slug": "alpha-reviewers"}},
                {"phid": "PHID-PROJ-b", "fields": {"slug": "beta-reviewers"}},
            ]
        }
    )
    c = _make_client(fake_session)
    out = c.resolve_project_phids(["alpha-reviewers", "beta-reviewers"])
    assert out == {
        "alpha-reviewers": "PHID-PROJ-a",
        "beta-reviewers": "PHID-PROJ-b",
    }
    # One batched call, no fallback needed.
    assert fake_session.post.call_count == 1
    _, kwargs = fake_session.post.call_args
    data = kwargs["data"]
    assert ("constraints[slugs][0]", "alpha-reviewers") in data
    assert ("constraints[slugs][1]", "beta-reviewers") in data


def test_resolve_project_phids_falls_back_for_unmatched(fake_session):
    # First call: batch search returns alpha but not gamma (e.g. gamma
    # is a secondary hashtag, not a primary slug).
    batch_response = _ok_response(
        {"data": [{"phid": "PHID-PROJ-a", "fields": {"slug": "alpha-reviewers"}}]}
    )
    # Second call: per-slug fallback for gamma succeeds.
    gamma_response = _ok_response({"data": [{"phid": "PHID-PROJ-g"}]})
    fake_session.post.side_effect = [batch_response, gamma_response]
    c = _make_client(fake_session)
    out = c.resolve_project_phids(["alpha-reviewers", "gamma-reviewers"])
    assert out == {
        "alpha-reviewers": "PHID-PROJ-a",
        "gamma-reviewers": "PHID-PROJ-g",
    }
    assert fake_session.post.call_count == 2


def test_resolve_project_phids_empty():
    c = _make_client(MagicMock(spec=requests.Session, headers={}))
    assert c.resolve_project_phids([]) == {}


def test_project_members_returns_phids(fake_session):
    fake_session.post.return_value = _ok_response(
        {
            "data": [
                {
                    "phid": "PHID-PROJ-abc",
                    "attachments": {
                        "members": {
                            "members": [
                                {"phid": "PHID-USER-1"},
                                {"phid": "PHID-USER-2"},
                            ]
                        }
                    },
                }
            ]
        }
    )
    c = _make_client(fake_session)
    assert c.project_members("PHID-PROJ-abc") == {"PHID-USER-1", "PHID-USER-2"}
    data = fake_session.post.call_args[1]["data"]
    assert ("constraints[phids][0]", "PHID-PROJ-abc") in data
    assert ("attachments[members]", "true") in data


def test_project_members_empty_when_project_not_found(fake_session):
    fake_session.post.return_value = _ok_response({"data": []})
    c = _make_client(fake_session)
    assert c.project_members("PHID-PROJ-missing") == set()


def test_project_members_empty_when_no_members_attachment(fake_session):
    fake_session.post.return_value = _ok_response(
        {"data": [{"phid": "PHID-PROJ-abc", "attachments": {}}]}
    )
    c = _make_client(fake_session)
    assert c.project_members("PHID-PROJ-abc") == set()


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
                        },
                        "projects": {
                            "projectPHIDs": [
                                "PHID-PROJ-newtab",
                                "PHID-PROJ-secure-revision",
                            ]
                        },
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
    assert r.project_phids == ["PHID-PROJ-newtab", "PHID-PROJ-secure-revision"]
    # Each search variant must request the projects attachment so
    # process_revision can read project tags off the result.
    data = fake_session.post.call_args[1]["data"]
    assert ("attachments[projects]", "true") in data
    assert ("attachments[reviewers]", "true") in data


def test_revision_from_search_result_defaults_project_phids_to_empty():
    r = Revision.from_search_result(
        {
            "phid": "PHID-DREV-2",
            "id": 999,
            "fields": {
                "title": "t",
                "summary": "",
                "status": {"value": "needs-review"},
                "authorPHID": "PHID-USER-1",
                "dateCreated": 0,
                "dateModified": 0,
            },
            # No attachments at all — defensive default.
        }
    )
    assert r.project_phids == []
    assert r.reviewer_phids == []
    assert r.reviewer_status == {}
    assert r.blocking_reviewer_phids() == set()


def test_revision_from_search_result_parses_reviewer_status():
    r = Revision.from_search_result(
        {
            "phid": "PHID-DREV-3",
            "id": 1001,
            "fields": {
                "title": "t",
                "summary": "",
                "status": {"value": "needs-review"},
                "authorPHID": "PHID-USER-1",
                "dateCreated": 0,
                "dateModified": 0,
            },
            "attachments": {
                "reviewers": {
                    "reviewers": [
                        # A rotation assigns one member the group's blocking slot.
                        {"reviewerPHID": "PHID-USER-rotated", "status": "blocking"},
                        {"reviewerPHID": "PHID-USER-extra", "status": "added"},
                    ]
                }
            },
        }
    )
    assert r.reviewer_status == {
        "PHID-USER-rotated": "blocking",
        "PHID-USER-extra": "added",
    }
    assert r.blocking_reviewer_phids() == {"PHID-USER-rotated"}


def test_search_revisions_by_phids_requests_projects_attachment(fake_session):
    fake_session.post.return_value = _ok_response({"data": []})
    c = _make_client(fake_session)
    c.search_revisions_by_phids(["PHID-DREV-1"])
    data = fake_session.post.call_args[1]["data"]
    assert ("attachments[projects]", "true") in data


def test_get_revision_by_id_requests_projects_attachment(fake_session):
    fake_session.post.return_value = _ok_response({"data": []})
    c = _make_client(fake_session)
    c.get_revision_by_id(123)
    data = fake_session.post.call_args[1]["data"]
    assert ("attachments[projects]", "true") in data


def test_get_raw_diff(fake_session):
    fake_session.post.return_value = _ok_response("diff --git a/foo b/foo\n@@ -1 +1 @@\n-old\n+new")
    c = _make_client(fake_session)
    text = c.get_raw_diff(42)
    assert "diff --git" in text


def test_post_comment_calls_createcomment_with_attach_inlines(fake_session):
    fake_session.post.return_value = _ok_response({"phid": "PHID-XACT-1"})
    c = _make_client(fake_session)
    c.post_comment(302879, "hello")
    args, kwargs = fake_session.post.call_args
    assert args[0] == "https://phab.example.test/api/differential.createcomment"
    data = kwargs["data"]
    assert ("revision_id", "302879") in data
    assert ("message", "hello") in data
    assert ("attach_inlines", "true") in data


def test_create_inline_sends_correct_params(fake_session):
    fake_session.post.return_value = _ok_response({"phid": "PHID-XCMT-77"})
    c = _make_client(fake_session)
    phid = c.create_inline(
        diff_id=42,
        file_path="dom/foo/Bar.cpp",
        line=117,
        is_new_file=True,
        content="Fix the unused param.",
    )
    assert phid == "PHID-XCMT-77"
    args, kwargs = fake_session.post.call_args
    assert args[0] == "https://phab.example.test/api/differential.createinline"
    data = kwargs["data"]
    assert ("diffID", "42") in data
    assert ("filePath", "dom/foo/Bar.cpp") in data
    assert ("lineNumber", "117") in data
    assert ("lineLength", "1") in data
    assert ("isNewFile", "1") in data
    assert ("content", "Fix the unused param.") in data


def test_create_inline_returns_none_when_no_phid(fake_session):
    fake_session.post.return_value = _ok_response({})
    c = _make_client(fake_session)
    phid = c.create_inline(
        diff_id=1,
        file_path="a.cpp",
        line=1,
        is_new_file=True,
        content="x",
    )
    assert phid is None


def test_publish_review_calls_createcomment_with_attach_inlines(fake_session):
    fake_session.post.return_value = _ok_response({"phid": "PHID-XACT-1"})
    c = _make_client(fake_session)
    c.publish_review(302879, "summary body")
    args, kwargs = fake_session.post.call_args
    assert args[0] == "https://phab.example.test/api/differential.createcomment"
    data = kwargs["data"]
    assert ("revision_id", "302879") in data
    assert ("message", "summary body") in data
    assert ("attach_inlines", "true") in data


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


def _tx(
    *,
    type: str = "comment",
    author: str = "PHID-USER-x",
    with_comment: bool = True,
) -> dict:
    return {
        "type": type,
        "authorPHID": author,
        "comments": [{"content": {"raw": "hi"}}] if with_comment else [],
    }


def test_human_commenter_phids_filters_author_apps_and_ignored(fake_session):
    fake_session.post.return_value = _ok_response(
        {
            "data": [
                # Author's own comment — filtered.
                _tx(author="PHID-USER-author"),
                # Herald (application) — filtered: not a PHID-USER- account.
                # Mozilla's real Herald PHID is PHID-APPS-, not PHID-APPL-.
                _tx(author="PHID-APPS-PhabricatorHeraldApplication"),
                # In ignore list — filtered.
                _tx(author="PHID-USER-landobot"),
                # Empty comments array — filtered.
                _tx(author="PHID-USER-deletedcomment", with_comment=False),
                # Status-change transaction (not a comment) — filtered.
                {"type": "status", "authorPHID": "PHID-USER-other", "comments": []},
                # Real reviewer comment — kept.
                _tx(author="PHID-USER-alice"),
                # Real reviewer inline comment — kept (different author).
                _tx(type="inline", author="PHID-USER-bob"),
                # Duplicate reviewer comment — still just one PHID.
                _tx(author="PHID-USER-alice"),
            ]
        }
    )
    c = _make_client(fake_session)
    result = c.human_commenter_phids(
        555,
        author_phid="PHID-USER-author",
        ignore_phids={"PHID-USER-landobot"},
    )
    assert result == {"PHID-USER-alice", "PHID-USER-bob"}


def test_human_commenter_phids_empty_when_only_author_and_herald(fake_session):
    # A revision with only the author's comment and Herald's automated comment
    # has no human reviewer engaged. This is the common state for review-rotation
    # revisions, which always carry a Herald comment from creation.
    fake_session.post.return_value = _ok_response(
        {
            "data": [
                _tx(author="PHID-USER-author"),
                _tx(author="PHID-APPS-PhabricatorHeraldApplication"),
            ]
        }
    )
    c = _make_client(fake_session)
    assert (
        c.human_commenter_phids(555, author_phid="PHID-USER-author") == set()
    )


def test_human_commenter_phids_sends_correct_params(fake_session):
    fake_session.post.return_value = _ok_response({"data": []})
    c = _make_client(fake_session)
    c.human_commenter_phids(555, author_phid="PHID-USER-author")
    args, kwargs = fake_session.post.call_args
    assert args[0] == "https://phab.example.test/api/transaction.search"
    data = kwargs["data"]
    assert ("objectIdentifier", "D555") in data
    assert ("limit", "100") in data


def test_diff_from_search_result():
    d = Diff.from_search_result(
        {"phid": "PHID-DIFF-7", "id": 7, "fields": {"revisionPHID": "PHID-DREV-1", "dateCreated": 1}}
    )
    assert d.id == 7
    assert d.revision_phid == "PHID-DREV-1"
