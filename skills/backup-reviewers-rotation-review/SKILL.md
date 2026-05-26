---
description: Review guidance for the Firefox Backup component, covering process boundaries, session/cookie interactions, test hygiene, and cross-platform desktop scope.
---

# Backup Reviewers Rotation

The corpus is thin; many comments are cross-module sign-offs. Standing conventions below combine the Backup-specific signals with Mozilla JS house style that reviewers will reliably enforce.

## Standing Conventions

### Process model
1. Keep parent-only work out of `*Child` actors. Operations that touch app lifecycle, profile management, OS-level foregrounding, or anything that must run in the parent process belong in `BackupUIParent` (or equivalent parent actor), because child actors can be instantiated in content processes such as `about:welcome`.
2. When a backup flow launches or switches the running Firefox instance, account for OS-specific foreground/activation behavior (notably macOS opens new instances in the background). Restoration UX is not done until the recovered profile is actually frontmost.

### Cross-module changes
3. Backup is desktop-only. Test manifests for `browser/components/backup/**` should not need Android skip-ifs; do not add or carry forward platform guards that the resolution of platform-scoping bugs has made unnecessary.
4. When a Backup patch also touches sessionstore, cookies, newtab, or other shared subsystems, request the relevant module's reviewer group in addition to backup-reviewers — backup-reviewers will explicitly scope their r+ to "the backup parts."

### JS style & APIs
5. Follow Mozilla JS house style: `camelCase` methods, `aFoo` argument prefix, `_foo` private members, double-quoted strings, prefer `["a","b"]` and object literals, no `== true`/`== false`. Constants use `kFoo` or `ALL_CAPS`.
6. Prefer `ChromeUtils.now()` over `Cu.now()` in new code, but feature-detect when the code may ride trains to older branches.
7. In tests, prefer `sinon.stub`/`sinon.spy` over hand-rolled method overwrites; restore state via the stub's own teardown, not ad-hoc cleanup.

## Common Pitfalls

- Placing logic that needs parent-process privileges (process launch, profile swap, quitting the app) inside a `BackupUIChild` actor.
- Forgetting macOS foreground/activation when programmatically launching another Firefox instance after restore.
- Hand-overwriting methods in tests instead of stubbing, leading to brittle cleanup.
- Landing Backup-touching patches without explicit sign-off from the other affected module (sessionstore-, newtab-, reusable-components-reviewers, etc.).
- Carrying stale `skip-if = ["os == 'android'"]` directives in Backup test manifests.
- Using `Cu.now()` in new telemetry/timing code without considering the `ChromeUtils.now()` migration and trainhop fallback.
- Landing without a bug number annotation when disabling or skipping a Backup test.
- Quietly changing the semantics of persisted values (defaults, enum mappings) without preserving backward compatibility for data written by older Firefox versions — grandfather existing data on first read.

## File-Glob Guidance

- `browser/components/backup/actors/*Child.sys.mjs` — verify each handler is safe in any content process the actor could attach to; push privileged work to the Parent actor.
- `browser/components/backup/actors/*Parent.sys.mjs` — confirm OS-level side effects (process launch, focus, profile switch) are gated and platform-correct.
- `browser/components/backup/tests/**` — prefer sinon; ensure manifests don't include needless platform skips; new disables carry a bug reference.
- `browser/components/backup/content/**` — follow standard JS style; keep UI strings localizable.
- Cross-cutting edits under `browser/components/sessionstore/**`, `browser/extensions/newtab/**`, etc. — Backup r+ only covers the backup-owned bits; require the owning group's sign-off for the rest.

## Review Checklist

- [ ] Does any new actor code assume parent-process context? If so, is it actually in the Parent actor?
- [ ] If the patch starts/switches Firefox instances, is foreground behavior correct on macOS, Windows, and Linux?
- [ ] Are all affected non-Backup modules represented in the reviewer set?
- [ ] Do tests use sinon stubs/spies rather than manual method replacement?
- [ ] Are test manifests free of obsolete platform skip-ifs, and do new skips cite a bug?
- [ ] Does the JS conform to house style (naming prefixes, quoting, no `== true`, etc.)?
- [ ] For timing APIs, is `ChromeUtils.now()` used with a `Cu.now()` fallback where trainhop matters?
- [ ] For any change to persisted/serialized data shape or defaults, is existing on-disk data still interpreted correctly?
- [ ] Are user-visible strings localized and routed through Fluent rather than hard-coded?
- [ ] Does the commit message and Phab title carry the bug number for any test annotation change?

## House style references

- [JavaScript Coding Style](https://firefox-source-docs.mozilla.org/code-quality/coding-style/coding_style_js.html)