"""searchfox-cli wrapper — subprocess mocking + path safety."""

from __future__ import annotations

import os
import subprocess

from qreviews import searchfox


def _completed(stdout: str = "", stderr: str = "", returncode: int = 0):
    cp = subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)
    return cp


def test_read_file_rejects_absolute_paths():
    out = searchfox.read_file("/etc/passwd")
    assert out.startswith("ERROR:")


def test_read_file_rejects_dotdot():
    out = searchfox.read_file("foo/../../../etc/passwd")
    assert out.startswith("ERROR:")


def test_read_file_passes_repo_relative(mocker):
    mocker.patch("shutil.which", return_value="/fake/searchfox-cli")
    run = mocker.patch("subprocess.run", return_value=_completed("   1: hello\n"))
    out = searchfox.read_file("browser/foo.cpp", "1-5")
    assert "hello" in out
    args = run.call_args[0][0]
    assert args[1:] == ["--get-file", "browser/foo.cpp", "--lines", "1-5"]


def test_search_code_builds_flags(mocker):
    mocker.patch("shutil.which", return_value="/fake/searchfox-cli")
    run = mocker.patch("subprocess.run", return_value=_completed("file:1: hit\n"))
    searchfox.search_code(
        "AudioStream",
        path="^dom/media",
        regex=True,
        language="cpp",
        exclude_tests=True,
        limit=5,
    )
    args = run.call_args[0][0]
    assert "-q" in args and "AudioStream" in args
    assert "-p" in args and "^dom/media" in args
    assert "-r" in args
    assert "--exclude-tests" in args
    assert "--cpp" in args
    assert "-l" in args and "5" in args


def test_search_code_rejects_bad_language(mocker):
    mocker.patch("shutil.which", return_value="/fake/searchfox-cli")
    out = searchfox.search_code("foo", language="cobol")
    assert "unsupported language" in out


def test_run_handles_nonzero_exit(mocker):
    mocker.patch("shutil.which", return_value="/fake/searchfox-cli")
    mocker.patch(
        "subprocess.run",
        return_value=_completed("", "fatal: nope", returncode=1),
    )
    out = searchfox.find_definition("Nope::Bogus")
    assert out.startswith("ERROR:")
    assert "fatal: nope" in out


def test_run_handles_timeout(mocker):
    mocker.patch("shutil.which", return_value="/fake/searchfox-cli")
    mocker.patch(
        "subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["x"], timeout=30)
    )
    out = searchfox.read_file("a/b.cpp")
    assert out.startswith("ERROR:") and "timed out" in out


def test_truncate():
    big = "x" * (searchfox.MAX_OUTPUT_BYTES + 1000)
    assert "[... truncated" in searchfox._truncate(big)


def test_execute_tool_dispatch(mocker):
    mocker.patch("shutil.which", return_value="/fake/searchfox-cli")
    mocker.patch("subprocess.run", return_value=_completed("   1: ok\n"))
    result = searchfox.execute_tool("read_file", {"path": "a/b.cpp", "lines": "1-3"})
    assert "ok" in result


def test_execute_tool_unknown():
    assert searchfox.execute_tool("not_a_tool", {}).startswith("ERROR:")


def test_execute_tool_bad_args(mocker):
    # `read_file` requires `path`. Calling without it should map to a friendly ERROR.
    out = searchfox.execute_tool("read_file", {"oops": 1})
    assert out.startswith("ERROR:")


def test_unavailable_searchfox(mocker):
    mocker.patch("shutil.which", return_value=None)
    mocker.patch("qreviews.searchfox._FALLBACK_BIN_DIRS", ())
    out = searchfox.execute_tool("read_file", {"path": "a/b.cpp"})
    assert out.startswith("ERROR:") and "searchfox-cli not found" in out


def test_resolver_falls_back_to_cargo_bin(mocker):
    """When PATH is bare (e.g. launchd), resolver checks ~/.cargo/bin etc."""
    mocker.patch("shutil.which", return_value=None)
    mocker.patch(
        "qreviews.searchfox._FALLBACK_BIN_DIRS",
        ("~/.cargo/bin",),
    )
    expected = os.path.expanduser("~/.cargo/bin/searchfox-cli")
    mocker.patch(
        "os.access",
        side_effect=lambda p, mode: p == expected,
    )
    run = mocker.patch("subprocess.run", return_value=_completed("ok\n"))
    searchfox.find_definition("Foo::Bar")
    args = run.call_args[0][0]
    assert args[0] == expected


def test_has_searchfox_true_when_resolvable(mocker):
    mocker.patch("shutil.which", return_value="/somewhere/searchfox-cli")
    assert searchfox.has_searchfox() is True


def test_has_searchfox_false_when_unresolvable(mocker):
    mocker.patch("shutil.which", return_value=None)
    mocker.patch("qreviews.searchfox._FALLBACK_BIN_DIRS", ())
    assert searchfox.has_searchfox() is False
