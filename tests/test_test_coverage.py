"""Unit tests for the searchfox-backed existing-coverage lookup."""

from __future__ import annotations

import pytest

from qreviews import searchfox, test_coverage


@pytest.fixture(autouse=True)
def _force_searchfox_available(monkeypatch):
    monkeypatch.setattr(searchfox, "has_searchfox", lambda: True)


def _set_run(monkeypatch, responses: dict[str, str]) -> list[list[str]]:
    """Patch searchfox._run with a canned-response lookup keyed on the
    query string passed via `-q`. Returns the list of recorded calls.
    """
    calls: list[list[str]] = []

    def fake_run(args, *, timeout=None):
        calls.append(list(args))
        try:
            q_idx = args.index("-q") + 1
        except ValueError:
            q_idx = -1
        key = args[q_idx] if q_idx >= 0 else ""
        return responses.get(key, "")

    monkeypatch.setattr(searchfox, "_run", fake_run)
    return calls


def test_skips_when_no_non_test_files():
    res = test_coverage.lookup_existing_coverage([])
    assert res.coverage_signal == "no_non_test_files"
    assert res.candidate_count == 0


def test_skips_when_searchfox_missing(monkeypatch):
    monkeypatch.setattr(searchfox, "has_searchfox", lambda: False)
    res = test_coverage.lookup_existing_coverage(["dom/base/Document.cpp"])
    assert res.coverage_signal == "skipped_no_searchfox"
    assert res.candidate_count == 1


def test_all_files_covered(monkeypatch):
    _set_run(
        monkeypatch,
        {
            "Document": "dom/base/test/test_doc.html:42: ...\n"
            "dom/base/test/browser_doc.js:10: ...\n",
            "Manager": "toolkit/components/x/tests/test_manager.js:1: ...\n",
        },
    )
    res = test_coverage.lookup_existing_coverage(
        ["dom/base/Document.cpp", "toolkit/components/x/Manager.sys.mjs"]
    )
    assert res.coverage_signal == "covered"
    assert "dom/base/Document.cpp" in res.covered_paths
    assert res.covered_paths["dom/base/Document.cpp"] == [
        "dom/base/test/test_doc.html",
        "dom/base/test/browser_doc.js",
    ]
    assert res.uncovered_paths == []


def test_partial_coverage(monkeypatch):
    _set_run(
        monkeypatch,
        {
            "Document": "dom/base/test/test_doc.html:42: ...\n",
            "Manager": "",  # no hits
        },
    )
    res = test_coverage.lookup_existing_coverage(
        ["dom/base/Document.cpp", "toolkit/components/x/Manager.sys.mjs"]
    )
    assert res.coverage_signal == "partial"
    assert list(res.covered_paths) == ["dom/base/Document.cpp"]
    assert res.uncovered_paths == ["toolkit/components/x/Manager.sys.mjs"]


def test_fully_uncovered(monkeypatch):
    _set_run(monkeypatch, {"Document": "", "Manager": ""})
    res = test_coverage.lookup_existing_coverage(
        ["dom/base/Document.cpp", "toolkit/components/x/Manager.sys.mjs"]
    )
    assert res.coverage_signal == "uncovered"
    assert res.covered_paths == {}
    assert res.uncovered_paths == [
        "dom/base/Document.cpp",
        "toolkit/components/x/Manager.sys.mjs",
    ]


def test_skips_short_basenames(monkeypatch):
    calls = _set_run(monkeypatch, {})
    res = test_coverage.lookup_existing_coverage(["x/y/a.js"])
    # a.js → basename "a" → 1 char, skipped without a searchfox call.
    assert calls == []
    assert res.uncovered_paths == ["x/y/a.js"]


def test_searchfox_error_returns_no_hits(monkeypatch):
    _set_run(
        monkeypatch,
        {"Document": "ERROR: searchfox-cli failed: bad index"},
    )
    res = test_coverage.lookup_existing_coverage(["dom/base/Document.cpp"])
    assert res.coverage_signal == "uncovered"
    assert res.uncovered_paths == ["dom/base/Document.cpp"]


def test_cap_signals_skipped_large_diff(monkeypatch):
    _set_run(monkeypatch, {})
    many = [f"dir/File{i}.cpp" for i in range(15)]
    res = test_coverage.lookup_existing_coverage(many, file_cap=10)
    assert res.coverage_signal == "skipped_large_diff"
    assert res.candidate_count == 15


def test_self_reference_filtered(monkeypatch):
    # The lookup file would never appear in test paths in practice, but
    # guard against it anyway.
    _set_run(
        monkeypatch,
        {"Document": "dom/base/Document.cpp:1: ...\ndom/base/test/test_doc.html:2:"},
    )
    res = test_coverage.lookup_existing_coverage(["dom/base/Document.cpp"])
    # Only the test path remains after self-filter.
    assert res.covered_paths["dom/base/Document.cpp"] == ["dom/base/test/test_doc.html"]


def test_format_coverage_block_renders_uncovered(monkeypatch):
    _set_run(monkeypatch, {"Document": ""})
    res = test_coverage.lookup_existing_coverage(["dom/base/Document.cpp"])
    block = test_coverage.format_coverage_block(res)
    assert block is not None
    assert "coverage_signal=uncovered" in block
    assert "dom/base/Document.cpp" in block


def test_format_coverage_block_none_when_no_files():
    res = test_coverage.lookup_existing_coverage([])
    assert test_coverage.format_coverage_block(res) is None
