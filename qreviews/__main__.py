"""qreviews CLI entrypoint.

Usage:
    python -m qreviews init-db
    python -m qreviews migrate
    python -m qreviews resolve-phids
    python -m qreviews poll [--dry-run]
    python -m qreviews review <Dxxxxx> [--post]
    python -m qreviews dashboard
    python -m qreviews status [--group SLUG]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from qreviews.config import Config, Secrets, load_config, load_secrets
from qreviews.metrics import compute_summary
from qreviews.state import Store


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )


def _parse_revision_id(value: str) -> int:
    v = value.strip()
    if v.lower().startswith("d"):
        v = v[1:]
    return int(v)


def _open_runtime(config_path: str, *, need_secrets: bool = True) -> tuple[Config, Secrets | None, Store]:
    config = load_config(config_path)
    secrets = load_secrets(".env") if need_secrets else None
    store = Store(config.storage.db_path)
    store.init_schema()
    return config, secrets, store


# --------------------------------------------------------------------- commands


def cmd_init_db(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    store = Store(config.storage.db_path)
    store.init_schema()
    print(f"initialized {config.storage.db_path}")
    return 0


def cmd_migrate(args: argparse.Namespace) -> int:
    from qreviews.state import SLUG_RENAMES

    config = load_config(args.config)
    store = Store(config.storage.db_path)
    store.init_schema()
    for old, new in SLUG_RENAMES:
        moved = store.rename_group_slug(old, new)
        print(f"  {old} → {new}: moved {moved} revision(s)")
    return 0


def _open_runtime_for_poll(config_path: str) -> tuple[Config, Secrets, Store]:
    """Convenience wrapper for callers that need secrets (poll, review, resolve-phids)."""
    cfg, secrets, store = _open_runtime(config_path, need_secrets=True)
    assert secrets is not None
    return cfg, secrets, store


def cmd_resolve_phids(args: argparse.Namespace) -> int:
    from qreviews.poller import Poller

    config, secrets, store = _open_runtime(args.config)
    poller = Poller(config, secrets, store)
    for group in config.reviewer_groups:
        try:
            phid = poller.resolve_group_phid(group.slug)
            print(f"  {group.slug:32s} → {phid}")
        except Exception as e:
            print(f"  {group.slug:32s} → ERROR: {e}", file=sys.stderr)
    return 0


def cmd_poll(args: argparse.Namespace) -> int:
    from qreviews.poller import Poller

    config, secrets, store = _open_runtime(args.config)
    poller = Poller(config, secrets, store)
    if args.once:
        for group in config.enabled_groups():
            results = poller.poll_group(group, dry_run=args.dry_run)
            print(f"[{group.slug}] processed {len(results)} revisions")
        poller.backfill_status()
    else:
        poller.run_forever(dry_run=args.dry_run)
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    from qreviews.poller import Poller

    config, secrets, store = _open_runtime(args.config)
    poller = Poller(config, secrets, store)

    revision_id = _parse_revision_id(args.revision)
    revision = poller.conduit.get_revision_by_id(revision_id)
    if not revision:
        print(f"revision D{revision_id} not found", file=sys.stderr)
        return 1

    # Decide which group to use: explicit --group, else the first enabled group
    # whose PHID is among the revision's reviewers.
    group = None
    if args.group:
        group = config.group_by_slug(args.group)
        if not group:
            print(f"group '{args.group}' not in config", file=sys.stderr)
            return 1
    else:
        for g in config.enabled_groups():
            try:
                phid = poller.resolve_group_phid(g.slug)
            except Exception:
                continue
            if phid in revision.reviewer_phids:
                group = g
                break
    if not group:
        print(
            f"D{revision_id} is not tagged with any configured (enabled) reviewer group; "
            "use --group SLUG to force one",
            file=sys.stderr,
        )
        return 1

    result = poller.process_revision(revision, group, dry_run=not args.post)
    payload = {
        "revision": revision.display_id,
        "group": group.slug,
        "posted": result.posted,
        "skipped_reason": result.skipped_reason,
        "risk": result.risk,
        "complexity": result.complexity,
    }
    print(json.dumps(payload, indent=2))
    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    import uvicorn

    from qreviews.dashboard.app import create_app

    config, _, _ = _open_runtime(args.config, need_secrets=False)
    app = create_app(config_path=args.config)
    host = args.host or config.dashboard.host
    port = args.port or config.dashboard.port
    print(f"dashboard at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0


def cmd_ping_anthropic(args: argparse.Namespace) -> int:
    from anthropic import Anthropic

    config, secrets, _ = _open_runtime(args.config, need_secrets=True)
    client = Anthropic(api_key=secrets.anthropic_api_key)
    response = client.messages.create(
        model=config.anthropic.scoring_model,
        max_tokens=32,
        messages=[{"role": "user", "content": "Reply with the single word: pong"}],
    )
    text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text").strip()
    out = {
        "ok": "pong" in text.lower(),
        "model": config.anthropic.scoring_model,
        "reply": text,
        "usage": {
            "input_tokens": getattr(response.usage, "input_tokens", 0),
            "output_tokens": getattr(response.usage, "output_tokens", 0),
        },
    }
    print(json.dumps(out, indent=2))
    return 0 if out["ok"] else 1


def cmd_ping_phabricator(args: argparse.Namespace) -> int:
    config, secrets, _ = _open_runtime(args.config, need_secrets=True)
    from qreviews.conduit import ConduitClient, ConduitError

    client = ConduitClient(
        base_url=config.phabricator.base_url,
        api_token=secrets.phabricator_api_token,
        user_agent=config.phabricator.user_agent,
        min_call_interval=0.0,
    )
    try:
        result = client.ping()
        print(json.dumps({"ok": True, "server": result}, indent=2))
        return 0
    except ConduitError as e:
        snippet = str(e)
        if "Can Not Connect to MySQL" in snippet:
            print(json.dumps({"ok": False, "reason": "phabricator_mysql_down"}, indent=2))
        else:
            print(json.dumps({"ok": False, "reason": "conduit_error", "detail": snippet[:200]}, indent=2))
        return 1


def cmd_status(args: argparse.Namespace) -> int:
    config, _, store = _open_runtime(args.config, need_secrets=False)
    rows = list(store.iter_for_metrics(group_slug=args.group))
    summary = compute_summary(rows, group_slug=args.group)
    print(json.dumps(summary.to_dict(), indent=2, default=str))
    return 0


# --------------------------------------------------------------------- argparse


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="qreviews")
    p.add_argument("--config", default="config.yaml", help="path to config.yaml")
    p.add_argument("-v", "--verbose", action="store_true")

    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db").set_defaults(func=cmd_init_db)
    sub.add_parser(
        "migrate", help="apply one-time reviewer-group slug rebinds (idempotent)"
    ).set_defaults(func=cmd_migrate)
    sub.add_parser("resolve-phids").set_defaults(func=cmd_resolve_phids)

    poll = sub.add_parser("poll", help="run the polling loop")
    poll.add_argument("--once", action="store_true", help="run one cycle and exit")
    poll.add_argument("--dry-run", action="store_true", help="do not post to Phabricator")
    poll.set_defaults(func=cmd_poll)

    review = sub.add_parser("review", help="review a single revision by D-id")
    review.add_argument("revision", help="e.g. D123456 or 123456")
    review.add_argument("--group", help="force a specific reviewer-group slug")
    review.add_argument("--post", action="store_true", help="actually post to Phabricator")
    review.set_defaults(func=cmd_review)

    dash = sub.add_parser("dashboard", help="serve the metrics dashboard")
    dash.add_argument("--host")
    dash.add_argument("--port", type=int)
    dash.set_defaults(func=cmd_dashboard)

    status = sub.add_parser("status", help="print summary metrics")
    status.add_argument("--group")
    status.set_defaults(func=cmd_status)

    sub.add_parser("ping-anthropic", help="verify ANTHROPIC_API_KEY works").set_defaults(
        func=cmd_ping_anthropic
    )
    sub.add_parser(
        "ping-phabricator", help="verify Phabricator + token (returns ok=false if MySQL is down)"
    ).set_defaults(func=cmd_ping_phabricator)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
