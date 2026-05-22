"""Phabricator Herald webhook receiver.

Mount this router on the dashboard FastAPI app so a single uvicorn process
serves both the dashboard and the webhook. Phabricator's Herald can be
configured (via Config → Webhooks + a Herald rule with the "Call webhooks"
action) to POST a JSON payload here whenever a revision transitions; we
authenticate the POST with HMAC-SHA256 and hand the work off to the same
`Poller.process_revision()` codepath used by the polling loop.

Out of scope for v0:

- Bidirectional handshake/probe response — Phabricator's webhook probe is a
  simple POST; we accept it.
- Per-route auth for the dashboard itself (the dashboard is intended for
  local use; if you expose it, add auth in a reverse proxy).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os

from fastapi import APIRouter, Header, HTTPException, Request

from qreviews.config import Config, ReviewerGroup, load_secrets
from qreviews.poller import Poller
from qreviews.state import Store

log = logging.getLogger(__name__)


def _verify_signature(body: bytes, secret: str, signature_header: str | None) -> bool:
    """Constant-time check of HMAC-SHA256(body, secret) against the header.

    Phabricator Herald sends a hex digest in `X-Phabricator-Webhook-Signature`.
    """
    if not signature_header:
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    # Accept either bare hex or "sha256=<hex>" prefix.
    if signature_header.startswith("sha256="):
        signature_header = signature_header.split("=", 1)[1]
    return hmac.compare_digest(expected, signature_header.strip())


def build_router(config: Config, store: Store) -> APIRouter:
    """Build the webhook router. Secrets are read lazily at request time."""

    router = APIRouter(prefix="/phabricator", tags=["webhook"])

    @router.post("/herald")
    async def receive_herald(
        request: Request,
        x_phabricator_webhook_signature: str | None = Header(default=None),
    ) -> dict:
        body = await request.body()

        webhook_secret = os.environ.get("PHABRICATOR_WEBHOOK_SECRET", "").strip()
        if webhook_secret:
            if not _verify_signature(body, webhook_secret, x_phabricator_webhook_signature):
                log.warning("webhook: HMAC mismatch")
                raise HTTPException(status_code=401, detail="bad signature")
        else:
            log.warning(
                "webhook: PHABRICATOR_WEBHOOK_SECRET not set — accepting unsigned payload"
            )

        try:
            payload = await request.json()
        except Exception as e:
            raise HTTPException(status_code=400, detail="invalid JSON body") from e

        # Phabricator's payload shape varies per event; the most useful fields
        # are `object.phid` and `triggers[].kind`. We accept either a top-level
        # `objectPHID` or a nested `object.phid`.
        object_phid = payload.get("objectPHID") or (payload.get("object") or {}).get("phid")
        if not object_phid or not object_phid.startswith("PHID-DREV-"):
            # Not a Differential event — e.g. a probe or a non-revision object.
            return {"ok": True, "ignored": "non-revision payload"}

        # Resolve the revision and the matching configured group, then process.
        secrets = load_secrets(".env")
        poller = Poller(config, secrets, store)

        rev = poller.conduit.search_revisions_by_phids([object_phid])
        if not rev:
            return {"ok": True, "ignored": "revision not found"}
        revision = rev[0]

        group: ReviewerGroup | None = None
        for g in config.enabled_groups():
            try:
                phid = poller.resolve_group_phid(g.slug)
            except Exception:
                continue
            if phid in revision.reviewer_phids:
                group = g
                break

        if not group:
            return {
                "ok": True,
                "revision": revision.display_id,
                "ignored": "revision not tagged with a configured enabled group",
            }

        result = poller.process_revision(revision, group, dry_run=False)
        return {
            "ok": True,
            "revision": revision.display_id,
            "group": group.slug,
            "posted": result.posted,
            "skipped_reason": result.skipped_reason,
            "risk": result.risk,
            "complexity": result.complexity,
        }

    return router
