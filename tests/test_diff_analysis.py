"""Unit tests for the diff analyzer."""

from __future__ import annotations

from qreviews.diff_analysis import (
    DiffStats,
    _is_test_path,
    analyze_diff,
    format_test_signal_block,
)


def test_is_test_path_directories():
    assert _is_test_path("dom/base/test/test_thing.html")
    assert _is_test_path("browser/components/tests/browser_foo.js")
    assert _is_test_path("xpcshell/test_x.js")
    assert _is_test_path("toolkit/components/x/mochitest/browser_a.js")
    assert _is_test_path("gtest/gtest_runner.cpp")
    assert _is_test_path("layout/reftests/foo.html")


def test_is_test_path_filenames():
    assert _is_test_path("dom/base/test_focus.py")
    assert _is_test_path("modules/libpref/some_test.cpp")
    assert _is_test_path("browser/Foo.test.jsm")
    assert _is_test_path("browser/components/places/tests/head_bookmarks.js")


def test_is_test_path_non_tests():
    assert not _is_test_path("dom/base/Document.cpp")
    assert not _is_test_path("README.md")
    assert not _is_test_path("toolkit/components/x/Manager.sys.mjs")
    # Path containing the substring "test" but not in a test convention.
    assert not _is_test_path("browser/components/protest/Foo.cpp")


_SAMPLE_DOC_ONLY = """\
diff --git a/docs/intro.md b/docs/intro.md
--- a/docs/intro.md
+++ b/docs/intro.md
@@ -1,2 +1,3 @@
 # Intro
-old line
+new line
+second new line
"""


def test_analyze_doc_only_change():
    stats = analyze_diff(_SAMPLE_DOC_ONLY)
    assert stats.files_changed == 1
    assert stats.non_test_files_changed == 1
    assert stats.test_files_changed == 0
    assert stats.lines_added == 2
    assert stats.in_diff_test_signal == "absent"
    assert stats.non_test_paths == ["docs/intro.md"]


_SAMPLE_TESTS_ONLY = """\
diff --git a/dom/base/test/test_focus.html b/dom/base/test/test_focus.html
--- a/dom/base/test/test_focus.html
+++ b/dom/base/test/test_focus.html
@@ -10,3 +10,4 @@
 keep
+added
+added2
 keep2
"""


def test_analyze_tests_only_change():
    stats = analyze_diff(_SAMPLE_TESTS_ONLY)
    assert stats.test_files_changed == 1
    assert stats.non_test_files_changed == 0
    assert stats.in_diff_test_signal == "tests_only"
    assert stats.non_test_paths == []


_SAMPLE_MIXED_ADEQUATE = """\
diff --git a/dom/base/Document.cpp b/dom/base/Document.cpp
--- a/dom/base/Document.cpp
+++ b/dom/base/Document.cpp
@@ -100,3 +100,4 @@
 keep
-old
+new
+also new
diff --git a/dom/base/test/test_doc.cpp b/dom/base/test/test_doc.cpp
--- a/dom/base/test/test_doc.cpp
+++ b/dom/base/test/test_doc.cpp
@@ -1,3 +1,5 @@
 keep
+t1
+t2
+t3
 keep2
"""


def test_analyze_mixed_adequate():
    stats = analyze_diff(_SAMPLE_MIXED_ADEQUATE)
    assert stats.files_changed == 2
    assert stats.test_files_changed == 1
    assert stats.non_test_files_changed == 1
    assert stats.non_test_lines_added == 2
    assert stats.test_lines_added == 3
    assert stats.in_diff_test_signal == "adequate"
    assert stats.non_test_paths == ["dom/base/Document.cpp"]


_SAMPLE_MIXED_SPARSE = """\
diff --git a/dom/base/Document.cpp b/dom/base/Document.cpp
--- a/dom/base/Document.cpp
+++ b/dom/base/Document.cpp
@@ -100,5 +100,15 @@
 keep
+l1
+l2
+l3
+l4
+l5
+l6
+l7
+l8
+l9
+l10
 keep2
diff --git a/dom/base/test/test_doc.cpp b/dom/base/test/test_doc.cpp
--- a/dom/base/test/test_doc.cpp
+++ b/dom/base/test/test_doc.cpp
@@ -1,2 +1,3 @@
 keep
+t1
 keep2
"""


def test_analyze_mixed_sparse():
    stats = analyze_diff(_SAMPLE_MIXED_SPARSE)
    assert stats.non_test_lines_added == 10
    assert stats.test_lines_added == 1
    assert stats.in_diff_test_signal == "sparse"


def test_legal_anchors_track_both_sides():
    stats = analyze_diff(_SAMPLE_DOC_ONLY)
    # The new-side hunk starts at line 1 with `+`/` ` markers, so the
    # added lines are at new-side 2 and 3 (the first body line is the
    # unchanged " # Intro" at new-line 1).
    new_anchors = {(p, ln) for (p, ln, is_new) in stats.legal_anchors if is_new}
    assert ("docs/intro.md", 2) in new_anchors
    assert ("docs/intro.md", 3) in new_anchors
    # The removed line was at old-side line 2.
    old_anchors = {(p, ln) for (p, ln, is_new) in stats.legal_anchors if not is_new}
    assert ("docs/intro.md", 2) in old_anchors


def test_no_code_change_signal_on_empty_input():
    stats = analyze_diff("")
    assert stats == DiffStats(
        files_changed=0,
        test_files_changed=0,
        non_test_files_changed=0,
        lines_added=0,
        test_lines_added=0,
        non_test_lines_added=0,
        in_diff_test_signal="no_code_change",
        non_test_paths=[],
        legal_anchors=frozenset(),
    )


def test_format_test_signal_block_renders_both_layers():
    stats = analyze_diff(_SAMPLE_MIXED_ADEQUATE)
    block = format_test_signal_block(
        stats,
        coverage_block="coverage_signal=covered\n  dom/base/Document.cpp <- 3 hits",
    )
    assert block.startswith("<test_signals>")
    assert block.endswith("</test_signals>")
    assert "in_diff_test_signal=adequate" in block
    assert "coverage_signal=covered" in block


def test_format_test_signal_block_omits_coverage_when_none():
    stats = analyze_diff(_SAMPLE_DOC_ONLY)
    block = format_test_signal_block(stats, coverage_block=None)
    assert "coverage_signal" not in block
    assert "in_diff_test_signal=absent" in block
