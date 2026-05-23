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
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass
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


class ConduitError(RuntimeError):
    """Raised when Conduit returns a non-empty `error_code`."""

    def __init__(self, code: str, info: str, method: str):
        super().__init__(f"Conduit {method} failed: {code} — {info}")
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

    @property
    def display_id(self) -> str:
        return f"D{self.id}"

    @classmethod
    def from_search_result(cls, item: dict[str, Any]) -> Revision:
        fields = item.get("fields", {})
        bug = fields.get("bugzilla.bug-id")
        reviewers = []
        attachments = item.get("attachments") or {}
        reviewer_block = attachments.get("reviewers") or {}
        for r in reviewer_block.get("reviewers", []) or []:
            phid = r.get("reviewerPHID")
            if phid:
                reviewers.append(phid)
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
        self.session.headers.update({"User-Agent": user_agent})
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
            "attachments": {"reviewers": True},
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
            "attachments": {"reviewers": True},
            "limit": len(phid_list),
        }
        result = self.call("differential.revision.search", params)
        return [Revision.from_search_result(item) for item in result.get("data", [])]

    def get_revision_by_id(self, revision_id: int) -> Revision | None:
        params = {
            "constraints": {"ids": [int(revision_id)]},
            "attachments": {"reviewers": True},
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

    def post_comment(self, revision_phid: str, body: str) -> dict[str, Any]:
        """Post a single non-blocking `comment` transaction to a revision."""
        params = {
            "objectIdentifier": revision_phid,
            "transactions": [{"type": "comment", "value": body}],
        }
        return self.call("differential.revision.edit", params)

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
