"""Probe mozilla-central via searchfox-cli for existing tests of the files
in a revision's diff.

This complements `qreviews.diff_analysis`. The diff analyzer tells us whether
the patch itself includes test changes; this module tells us whether existing
tests in the tree already reference the touched non-test files, even when
the patch doesn't add tests.

The signal is intentionally a hint, not a guarantee — basename queries can
hit unrelated same-named files. Risk scoring treats it as one input among
many.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from qreviews import searchfox

log = logging.getLogger(__name__)


# Cap how many non-test files we look up per revision. searchfox-cli is
# local but not free; large refactors would otherwise issue dozens of
# subprocess calls.
DEFAULT_FILE_CAP = 10

# Path regex used as `-p` for searchfox-cli — restricts results to test
# locations only. Matches `qreviews.diff_analysis._TEST_DIR_RE`.
TEST_PATH_REGEX = (
    r"(^|/)(tests?|xpcshell|mochitests?|gtests?|reftests?|crashtests?|"
    r"jsapi-tests?|web-platform/tests?|googletest)/"
)

# Per-query hit cap. We only need to know "are there any tests" — a small
# limit keeps output bounded.
PER_QUERY_LIMIT = 5


@dataclass(frozen=True)
class ExistingCoverage:
    covered_paths: dict[str, list[str]] = field(default_factory=dict)
    uncovered_paths: list[str] = field(default_factory=list)
    coverage_signal: str = "skipped_no_searchfox"
    # Total non-test files in the diff, regardless of cap.
    candidate_count: int = 0


def _basename_no_ext(path: str) -> str:
    """Strip up to two extensions so Mozilla suffixes like `.sys.mjs` collapse
    to their bare module name. Stops at two so single-dot module names
    (`some.module.cpp`) don't lose more than the trailing kind."""
    base = os.path.basename(path)
    for _ in range(2):
        name, ext = os.path.splitext(base)
        if not ext:
            break
        base = name
    return base


def _parse_hits(output: str) -> list[str]:
    """Pull plausible file paths out of searchfox-cli output.

    searchfox-cli prints matches as `path:line:content` lines; the empty
    result is either truly empty or a "no matches" message. We only need a
    sample of paths for the model to see — a handful is enough.
    """
    if not output or output.startswith("ERROR:"):
        return []
    hits: list[str] = []
    seen: set[str] = set()
    for line in output.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        path = line.split(":", 1)[0].strip()
        if not path or path in seen:
            continue
        # Skip lines that don't look like file paths (truncation footer, etc.).
        if path.startswith("["):
            continue
        seen.add(path)
        hits.append(path)
        if len(hits) >= PER_QUERY_LIMIT:
            break
    return hits


def lookup_existing_coverage(
    non_test_paths: list[str],
    *,
    file_cap: int = DEFAULT_FILE_CAP,
) -> ExistingCoverage:
    """Run a small searchfox query per non-test path and aggregate.

    Returns an ExistingCoverage describing the per-file hit lists and an
    overall `coverage_signal`. If searchfox-cli is not installed on the
    host, returns the default skipped value.
    """
    if not non_test_paths:
        return ExistingCoverage(coverage_signal="no_non_test_files", candidate_count=0)

    if not searchfox.has_searchfox():
        log.info("searchfox-cli unavailable; skipping existing-coverage lookup")
        return ExistingCoverage(
            coverage_signal="skipped_no_searchfox",
            candidate_count=len(non_test_paths),
        )

    paths = list(non_test_paths)
    candidate_count = len(paths)
    skipped_large = False
    if candidate_count > file_cap:
        paths = paths[:file_cap]
        skipped_large = True

    covered: dict[str, list[str]] = {}
    uncovered: list[str] = []

    for path in paths:
        query = _basename_no_ext(path)
        if not query or len(query) < 3:
            # Generic single-character names like 'x' or 'i' produce too
            # much noise to be useful. Skip them.
            uncovered.append(path)
            continue
        try:
            output = searchfox._run(
                [
                    "-q",
                    query,
                    "-p",
                    TEST_PATH_REGEX,
                    "-r",
                    "-l",
                    str(PER_QUERY_LIMIT),
                ]
            )
        except searchfox.SearchfoxUnavailable:
            # Vanished mid-run. Give up but report what we already have.
            log.warning("searchfox-cli vanished mid-lookup at %s", path)
            return ExistingCoverage(
                covered_paths=covered,
                uncovered_paths=uncovered + paths[len(covered) + len(uncovered):],
                coverage_signal="skipped_no_searchfox",
                candidate_count=candidate_count,
            )
        hits = _parse_hits(output)
        # Drop self-references — the file we're looking up will appear in
        # the search results if it shares a basename with a test file path
        # by sheer regex (unlikely for non-test paths, but the basename
        # could match path components).
        hits = [h for h in hits if h != path]
        if hits:
            covered[path] = hits
        else:
            uncovered.append(path)

    if skipped_large:
        signal = "skipped_large_diff"
    elif not covered and uncovered:
        signal = "uncovered"
    elif covered and uncovered:
        signal = "partial"
    elif covered and not uncovered:
        signal = "covered"
    else:
        # Defensive — paths was non-empty so one of the above must hold.
        signal = "uncovered"

    return ExistingCoverage(
        covered_paths=covered,
        uncovered_paths=uncovered,
        coverage_signal=signal,
        candidate_count=candidate_count,
    )


def format_coverage_block(coverage: ExistingCoverage) -> str | None:
    """Render the layer-2 block for the `<test_signals>` prompt section.

    Returns None when there's nothing meaningful to show (e.g. searchfox
    was unavailable AND no diff files needed looking up).
    """
    if coverage.coverage_signal == "no_non_test_files":
        return None
    lines = [
        "Existing tests referencing changed non-test files (searchfox lookup):",
        f"  coverage_signal={coverage.coverage_signal}",
        f"  candidate_files={coverage.candidate_count}",
    ]
    if coverage.covered_paths:
        lines.append("  covered:")
        for src, tests in coverage.covered_paths.items():
            sample = ", ".join(tests[:3])
            more = "" if len(tests) <= 3 else f" (+{len(tests) - 3} more)"
            lines.append(f"    - {src} <- {sample}{more}")
    if coverage.uncovered_paths:
        lines.append("  uncovered:")
        for src in coverage.uncovered_paths:
            lines.append(f"    - {src}")
    return "\n".join(lines)
