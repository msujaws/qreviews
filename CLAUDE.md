# Claude working notes for qreviews

## Commit hygiene

**Commit as you work — don't batch up a single huge commit at the end of a
session.** Each commit should represent one self-contained change a reviewer
can read in isolation.

- After finishing a discrete unit of work (a bug fix, a single feature, a
  refactor, a test addition), stage the relevant files and commit before
  starting the next unit.
- Group related files together: the code change and its tests belong in
  the same commit. The README hunk that documents a new flag belongs with
  the commit that adds the flag.
- Use `git add <specific-files>` rather than `git add -A` or `git add .`
  so that unrelated working-tree changes don't sneak into the commit.
- Write commit messages in the imperative mood ("Add X", "Fix Y", "Drop
  Z") and explain the *why* in the body when it isn't obvious from the
  diff. Subject line ≤ 72 characters.
- **Do not include any Claude / Anthropic attribution in commit messages
  or PR descriptions.** No `Co-Authored-By: Claude`, no
  "🤖 Generated with Claude Code" footers, no mention of Claude in the
  body. Commits are authored by the user.
- Only commit when the task is at a clean stopping point — tests pass,
  no half-written code, no debug prints.
- Never commit secrets (`.env`, API tokens, credentials). The repo
  `.gitignore` already excludes `.env*`; double-check before staging
  anything new.
- Never amend or force-push commits that have already landed on `main`
  without explicit user confirmation.

## Repo layout (quick reference)

- `qreviews/` — Python package: poller, conduit client, scoring/review
  pipeline, FastAPI dashboard, webhook receiver, SQLite store.
- `qreviews/dashboard/web/` — Vite + React + Mantine source for the
  dashboard SPA.
- `qreviews/dashboard/web_dist/` — committed build output served by
  FastAPI's `StaticFiles` mount. Rebuild with
  `npm --prefix qreviews/dashboard/web run build` after editing the SPA.
- `skills/<group>/SKILL.md` — per-reviewer-group rubric loaded into the
  Claude review prompt.
- `tests/` — pytest suite. Run with `pytest -q` from the repo root.
- `deploy/` — launchd plist + install/uninstall scripts for autonomous
  polling on macOS.

## Before considering a task done

- `pytest -q` passes.
- `ruff check .` is clean.
- If the change touches the dashboard SPA, the bundle under
  `qreviews/dashboard/web_dist/` is rebuilt and committed alongside the
  source change.
- Changes are committed in logical chunks per the rules above.
