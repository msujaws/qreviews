"""Phabricator Conduit API client.

Conduit uses POST form encoding with the API token as a form field
(`api.token=api-xxx…`), NOT a header.

Mozilla Phabricator REQUIRES PHP-bracket form encoding for nested parameters
(`constraints[slugs][0]=foo`); JSON-encoded form values are rejected with
"Session key is not present." Lesson learned from
hnt-review-turnaround-time's CLAUDE.md.

The client also self-throttles (5s minimum interval) and retries on 429 with
the `Retry-After` header so we stay under Phabricator's opaque per-session
rate limit.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import requests

log = logging.getLogger(__name__)


MIN_CALL_INTERVAL_SECONDS = 5.0
MAX_RETRY_AFTER_SECONDS = 180.0


def _flatten_params(params: dict[str, Any]) -> list[tuple[str, str]]:
    """Convert nested dict/list params into PHP-bracket form pairs.

    Examples:
        {"limit": 1} → [("limit", "1")]
        {"constraints": {"slugs": ["foo"]}} → [("constraints[slugs][0]", "foo")]
        {"transactions": [{"type": "comment", "value": "hi"}]} →
            [("transactions[0][type]", "comment"), ("transactions[0][value]", "hi")]
    """
    out: list[tuple[str, str]] = []

    def walk(prefix: str, value: Any) -> None:
        if value is None:
            return
        if isinstance(value, dict):
            for k, v in value.items():
                walk(f"{prefix}[{k}]", v)
        elif isinstance(value, (list, tuple)):
            for i, v in enumerate(value):
                walk(f"{prefix}[{i}]", v)
        elif isinstance(value, bool):
            out.append((prefix, "true" if value else "false"))
        else:
            out.append((prefix, str(value)))

    for key, value in params.items():
        walk(key, value)
    return out


_TOKEN_RE = re.compile(r"api-[A-Za-z0-9]+")


class ConduitError(RuntimeError):
    """Raised when Conduit returns a non-empty `error_code`."""

    def __init__(self, code: str, info: str, method: str):
        # Phabricator echoes the submitted token back in `error_info` for
        # ERR-INVALID-AUTH, so redact any `api-…` token before it lands in logs.
        safe_info = _TOKEN_RE.sub("api-‹redacted›", info)
        super().__init__(f"Conduit {method} failed: {code} — {safe_info}")
        self.code = code
        self.info = info
        self.method = method


@dataclass(frozen=True)
class Revision:
    phid: str
    id: int
    title: str
    summary: str
    status: str
    author_phid: str
    repository_phid: str | None
    bug_id: str | None
    date_created: int
    date_modified: int
    reviewer_phids: list[str]
    project_phids: list[str]
    # reviewer PHID -> reviewer status ("blocking", "added", "accepted", …).
    # A round-robin "rotation" group never appears here while a revision is in
    # needs-review; instead it is replaced by a single rotated member carrying
    # the group's "blocking" slot, which `blocking_reviewer_phids` surfaces.
    reviewer_status: dict[str, str] = field(default_factory=dict)

    @property
    def display_id(self) -> str:
        return f"D{self.id}"

    def blocking_reviewer_phids(self) -> set[str]:
        """Reviewer PHIDs whose status is `blocking`."""
        return {phid for phid, status in self.reviewer_status.items() if status == "blocking"}

    @classmethod
    def from_search_result(cls, item: dict[str, Any]) -> Revision:
        fields = item.get("fields", {})
        bug = fields.get("bugzilla.bug-id")
        reviewers = []
        reviewer_status: dict[str, str] = {}
        attachments = item.get("attachments") or {}
        reviewer_block = attachments.get("reviewers") or {}
        for r in reviewer_block.get("reviewers", []) or []:
            phid = r.get("reviewerPHID")
            if phid:
                reviewers.append(phid)
                status = r.get("status")
                if status:
                    reviewer_status[phid] = status
        projects_block = attachments.get("projects") or {}
        project_phids = [p for p in (projects_block.get("projectPHIDs") or []) if p]
        return cls(
            phid=item["phid"],
            id=int(item["id"]),
            title=fields.get("title", "") or "",
            summary=fields.get("summary", "") or "",
            status=(fields.get("status") or {}).get("value", "unknown"),
            author_phid=fields.get("authorPHID", "") or "",
            repository_phid=fields.get("repositoryPHID"),
            bug_id=str(bug) if bug else None,
            date_created=int(fields.get("dateCreated") or 0),
            date_modified=int(fields.get("dateModified") or 0),
            reviewer_phids=reviewers,
            project_phids=project_phids,
            reviewer_status=reviewer_status,
        )


@dataclass(frozen=True)
class Diff:
    phid: str
    id: int
    revision_phid: str
    date_created: int

    @classmethod
    def from_search_result(cls, item: dict[str, Any]) -> Diff:
        fields = item.get("fields", {})
        return cls(
            phid=item["phid"],
            id=int(item["id"]),
            revision_phid=fields.get("revisionPHID", "") or "",
            date_created=int(fields.get("dateCreated") or 0),
        )


class ConduitClient:
    def __init__(
        self,
        base_url: str,
        api_token: str,
        user_agent: str = "qreviews-bot/0.1",
        timeout: float = 30.0,
        max_retries: int = 5,
        min_call_interval: float = MIN_CALL_INTERVAL_SECONDS,
        session: requests.Session | None = None,
    ):
        if not base_url.endswith("/"):
            base_url += "/"
        self.base_url = base_url
        self.api_token = api_token
        self.timeout = timeout
        self.max_retries = max_retries
        self.min_call_interval = min_call_interval
        self.session = session or requests.Session()
        # Disable HTTP keep-alive: the poller makes only a handful of calls per
        # cycle, then idles for an hour, during which the server drops the
        # pooled connection. Reusing that dead socket stalls the next cycle's
        # first call for the full read timeout before the retry recovers. With
        # Connection: close there is no idle socket to go stale.
        self.session.headers.update({"User-Agent": user_agent, "Connection": "close"})
        self._throttle_lock = threading.Lock()
        self._last_call_ts = 0.0

    # ------------------------------------------------------------ throttle

    def _throttle(self) -> None:
        with self._throttle_lock:
            elapsed = time.monotonic() - self._last_call_ts
            wait = self.min_call_interval - elapsed
            if wait > 0:
                time.sleep(wait)
            self._last_call_ts = time.monotonic()

    # ------------------------------------------------------------ low-level

    def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """POST to a Conduit method and return the unwrapped `result`.

        Params (including nested dicts/lists) are sent as PHP-bracket form-
        encoded pairs, which is what Mozilla Phabricator requires.
        """
        url = self.base_url + method
        data: list[tuple[str, str]] = [("api.token", self.api_token)]
        if params:
            data.extend(_flatten_params(params))

        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            self._throttle()
            try:
                resp = self.session.post(url, data=data, timeout=self.timeout)
                # 429: respect Retry-After.
                if resp.status_code == 429:
                    retry_after_hdr = resp.headers.get("Retry-After", "")
                    try:
                        wait = float(retry_after_hdr)
                    except ValueError:
                        wait = min(2 ** (attempt + 1), 30.0)
                    wait = min(wait, MAX_RETRY_AFTER_SECONDS)
                    log.warning(
                        "conduit %s rate-limited; retry in %.1fs (attempt %d/%d)",
                        method,
                        wait,
                        attempt + 1,
                        self.max_retries,
                    )
                    time.sleep(wait)
                    last_exc = ConduitError("http_429", "rate limited", method)
                    continue
                if resp.status_code >= 500:
                    log.warning(
                        "conduit %s returned %d, retrying (attempt %d/%d)",
                        method,
                        resp.status_code,
                        attempt + 1,
                        self.max_retries,
                    )
                    last_exc = ConduitError("http_5xx", resp.text[:200], method)
                    time.sleep(min(2**attempt, 16))
                    continue
                resp.raise_for_status()
                payload = resp.json()
                if payload.get("error_code"):
                    raise ConduitError(
                        payload["error_code"],
                        payload.get("error_info", ""),
                        method,
                    )
                return payload["result"]
            except (requests.ConnectionError, requests.Timeout) as e:
                last_exc = e
                log.warning(
                    "conduit %s connection error: %s (attempt %d/%d)",
                    method,
                    e,
                    attempt + 1,
                    self.max_retries,
                )
                time.sleep(min(2**attempt, 16))
                continue
        assert last_exc is not None
        raise last_exc

    # ------------------------------------------------------------ projects

    def resolve_project_phid(self, slug: str) -> str | None:
        result = self.call(
            "project.search",
            {"constraints": {"slugs": [slug]}, "limit": 1},
        )
        data = result.get("data") or []
        if not data:
            return None
        return data[0].get("phid")

    def resolve_project_phids(self, slugs: Iterable[str]) -> dict[str, str]:
        """Resolve multiple project slugs to PHIDs.

        Tries a single batched `project.search` first and matches results by
        `fields.slug` (Phabricator's primary slug). For input slugs that
        don't appear as a primary slug in the response — they may be
        secondary hashtags — falls back to one `resolve_project_phid` call
        per unmatched slug. Slugs with no matching project are omitted.
        """
        slug_list = list(dict.fromkeys(s for s in slugs if s))
        if not slug_list:
            return {}
        result = self.call(
            "project.search",
            {"constraints": {"slugs": slug_list}, "limit": len(slug_list)},
        )
        data = result.get("data") or []
        by_slug: dict[str, str] = {}
        wanted = set(slug_list)
        for item in data:
            phid = item.get("phid")
            fields = item.get("fields") or {}
            primary = fields.get("slug")
            if phid and primary and primary in wanted:
                by_slug[primary] = phid
        for slug in slug_list:
            if slug in by_slug:
                continue
            phid = self.resolve_project_phid(slug)
            if phid:
                by_slug[slug] = phid
        return by_slug

    def project_members(self, project_phid: str) -> set[str]:
        """Return PHIDs of users who are members of the given Phabricator project."""
        result = self.call(
            "project.search",
            {
                "constraints": {"phids": [project_phid]},
                "attachments": {"members": True},
                "limit": 1,
            },
        )
        items = result.get("data") or []
        if not items:
            return set()
        members_block = (items[0].get("attachments") or {}).get("members") or {}
        return {m["phid"] for m in (members_block.get("members") or []) if m.get("phid")}

    # ------------------------------------------------------------ revisions

    def search_revisions(
        self,
        reviewer_phids: Iterable[str],
        statuses: Iterable[str] = ("needs-review",),
        modified_since: int | None = None,
        limit: int = 100,
    ) -> list[Revision]:
        """Find revisions where any of the given reviewer PHIDs are reviewers."""
        constraints: dict[str, Any] = {
            "reviewerPHIDs": list(reviewer_phids),
            "statuses": list(statuses),
        }
        if modified_since is not None:
            constraints["modifiedStart"] = int(modified_since)

        params = {
            "constraints": constraints,
            "attachments": {"reviewers": True, "projects": True},
            "order": "newest",
            "limit": limit,
        }
        result = self.call("differential.revision.search", params)
        return [Revision.from_search_result(item) for item in result.get("data", [])]

    def search_revisions_by_phids(self, phids: Iterable[str]) -> list[Revision]:
        phid_list = list(phids)
        if not phid_list:
            return []
        params = {
            "constraints": {"phids": phid_list},
            "attachments": {"reviewers": True, "projects": True},
            "limit": len(phid_list),
        }
        result = self.call("differential.revision.search", params)
        return [Revision.from_search_result(item) for item in result.get("data", [])]

    def get_revision_by_id(self, revision_id: int) -> Revision | None:
        params = {
            "constraints": {"ids": [int(revision_id)]},
            "attachments": {"reviewers": True, "projects": True},
            "limit": 1,
        }
        result = self.call("differential.revision.search", params)
        items = result.get("data", [])
        if not items:
            return None
        return Revision.from_search_result(items[0])

    # ------------------------------------------------------------ diffs

    def latest_diff(self, revision_phid: str) -> Diff | None:
        params = {
            "constraints": {"revisionPHIDs": [revision_phid]},
            "order": "newest",
            "limit": 1,
        }
        result = self.call("differential.diff.search", params)
        items = result.get("data", [])
        if not items:
            return None
        return Diff.from_search_result(items[0])

    def get_raw_diff(self, diff_id: int) -> str:
        return self.call("differential.getrawdiff", {"diffID": int(diff_id)})

    # ------------------------------------------------------------ comments

    def post_comment(self, revision_id: int, body: str) -> dict[str, Any]:
        """Post a summary comment to a revision (no inline drafts attached).

        Thin shim around `publish_review` for callers that only need a
        top-level comment. The inline-finding flow goes through
        `create_inline` + `publish_review`; both end up in the same
        `differential.createcomment` call so any pending drafts the bot
        has accumulated will be flushed either way.
        """
        return self.publish_review(revision_id, body)

    def create_inline(
        self,
        *,
        diff_id: int,
        file_path: str,
        line: int,
        is_new_file: bool,
        content: str,
        length: int = 1,
    ) -> str | None:
        """Create a DRAFT inline comment via `differential.createinline`.

        The draft is bound to the bot's API-token user and remains
        unpublished until a subsequent `differential.createcomment` call
        with `attach_inlines=1` by the same user, which is what
        `publish_review` does.

        Returns the inline's PHID on success, or `None` if Conduit didn't
        include one (e.g. older Phabricator). Raises on Conduit-level error.
        """
        params = {
            "diffID": int(diff_id),
            "filePath": file_path,
            # Phabricator writes isNewFile into an integer column and does no
            # coercion on form-encoded scalars; the strings "true"/"false"
            # both become 0 (the base side). Send 1/0 so the new-side flag
            # survives.
            "isNewFile": 1 if is_new_file else 0,
            "lineNumber": int(line),
            "lineLength": max(1, int(length)),
            "content": content,
        }
        result = self.call("differential.createinline", params)
        if isinstance(result, dict):
            phid = result.get("phid") or result.get("inlinePHID")
            if isinstance(phid, str):
                return phid
        return None

    def publish_review(self, revision_id: int, summary_body: str) -> dict[str, Any]:
        """Publish the summary comment and flush pending inline drafts.

        Calls `differential.createcomment` with `attach_inlines=1`, which
        publishes every inline draft the bot user has created on this
        revision (via prior `create_inline` calls) atomically alongside
        the summary `message`. `differential.revision.edit` with a
        `comment` transaction does NOT auto-publish drafts over the
        Conduit path — drafts stay invisible until a separate
        `createcomment` call attaches them. mozilla/bugbug's
        `services/reviewhelper-api/app/review_processor.py` uses the
        same pattern.

        `differential.createcomment` is documented as deprecated, but
        Mozilla's Phabricator still serves it and it is the only
        Conduit method that publishes pending inline drafts.
        """
        params = {
            "revision_id": int(revision_id),
            "message": summary_body,
            "attach_inlines": True,
        }
        return self.call("differential.createcomment", params)

    # ------------------------------------------------------------ misc

    def ping(self) -> dict[str, Any]:
        """Phabricator `conduit.ping` — returns the server hostname when healthy."""
        return self.call("conduit.ping")

    def human_commenter_phids(
        self,
        revision_id: int,
        *,
        author_phid: str,
        ignore_phids: set[str] | None = None,
    ) -> set[str]:
        """Return PHIDs of non-author, non-application users who have left a
        comment (top-level or inline) on D<revision_id>.

        Filters out:
        - the revision's own author
        - any `authorPHID` starting with `PHID-APPL-` (Phabricator marks
          application-issued transactions like Herald with this prefix)
        - any PHID in `ignore_phids` (caller-supplied bot allowlist)
        - transactions whose `comments` array is empty (deleted/placeholder)
        """
        ignore = ignore_phids or set()
        params = {
            "objectIdentifier": f"D{revision_id}",
            "limit": 100,
        }
        result = self.call("transaction.search", params)
        commenters: set[str] = set()
        for tx in result.get("data", []) or []:
            if tx.get("type") not in ("comment", "inline"):
                continue
            if not tx.get("comments"):
                continue
            phid = tx.get("authorPHID") or ""
            if not phid or phid == author_phid:
                continue
            if phid.startswith("PHID-APPL-"):
                continue
            if phid in ignore:
                continue
            commenters.add(phid)
        return commenters
