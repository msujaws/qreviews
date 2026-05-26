---
description: Review guidance for Firefox's Application Update module, covering the updater binary, update service, multi-instance locking, installer/uninstaller helpers, and related telemetry.
---

## Standing Conventions

### Update locking and multi-instance coordination
- Treat the multi-instance lock and updater lock files as load-bearing concurrency primitives; any change to lock acquisition order, lock-byte semantics, or unlock paths needs an explicit deadlock/race analysis in the commit message. Locking here has repeatedly produced subtle bugs.
- When adding new lock bytes or new lock files, enforce a strict global acquisition order and document it in the code. Out-of-order acquisition is the standard way deadlocks slip in here.
- On Windows lock APIs (`LockFileEx`/`UnlockFileEx`), zero-initialize each `OVERLAPPED` before reuse and re-set `Offset`; the struct is in/out and prior calls can leave stale fields.
- On any failure path that could leave the process without an expected lock, set the "is another instance running" output conservatively to `true` so callers don't incorrectly conclude the process is alone.

### Elevation, privileges, and installer behavior
- Detect elevation by checking for the specific identities we actually grant ourselves (SYSTEM via the service, or an unrestricted-admin token via UAC) — not by enumerating arbitrary privileges or capabilities. We are not in the business of supporting arbitrary high-privilege launches.
- When changing what the updater does to the install directory (shortcuts, launchers, post-update steps), consider all four deployment modes: full install vs MSI, ESR vs release channel, per-user vs per-machine policy locations (HKCU/HKLM, plist, `distribution/policies.json`), and elevated vs unelevated post-update. Each axis has produced regressions.
- Use the wide (`W`) Win32 APIs in new updater/installer code, not the `A` variants. The `A` wrappers do hidden conversions and are inconsistent with the rest of the tree.

### Update service API and state
- `nsIApplicationUpdateService` states and related constants live in `toolkit/mozapps/update/nsIUpdateService.idl`. New states must be added to the IDL — don't reference undeclared `Ci.nsIApplicationUpdateService.*` constants from JS.
- Tests and external callers must go through documented helpers (e.g. the shared test setup in `toolkit/mozapps/update/tests/data/shared.js`) rather than reaching into `gAUS` or other private internals.
- Keep work that runs during startup off the main thread and asynchronous. Anything walking the install directory, hashing files, or doing nontrivial I/O at startup must be `async` and must not block the main thread.

### Telemetry and metrics
- Update-related metrics are defined in `toolkit/mozapps/update/metrics.yaml` and use Glean. Choose metric names that describe the event in the update domain's vocabulary (e.g. `update.blocked`), not the implementation detail that produced it.
- When migrating histograms to Glean, preserve the existing aggregation semantics; reviewers will spot-check that bucketing, units, and pings line up with the old histograms.

### Tests
- xpcshell and browser-chrome tests that exercise the updater must initialize the update service through the standard test helpers before opening UI like the elevation dialog; otherwise state is undefined.
- The updater lock file path is shared between several test suites (notably `test_backgroundtask_update_sync_manager.js`). Tests that take this lock must use a unique filename per run, or they will interfere with each other.
- Treat `MOZ_BACKGROUNDTASKS_NO_DEFAULT_PROFILE` and similar process-global flags as one-shot per process: cached results in `BackgroundTasksUtils` will not re-check the env var. Reset state explicitly in tests rather than relying on re-reading the flag.

### Code hygiene
- Prefer one focused commit per concern. Splitting "move code" from "change code" is repeatedly requested when large files (e.g. `browser/components/preferences/main.js`) are touched.
- Don't leave orphaned comments after removing the code they referenced. Reviewers flag stale comments around removed locks, removed lock files, and removed branches.
- When a one-arg constructor or implicit conversion is introduced in updater C++ code, mark it `explicit` unless there's a deliberate reason and a `MOZ_IMPLICIT` annotation.
- Prefer `using` over `typedef`, `nullptr` over `NULL`/`0`, and `std::optional<T>` (spelled out) over bare pointers when an absent value is meaningful — the updater is C++ and follows the Mozilla C++ style.

## Active Campaigns (transient)

- **Histogram → Glean migration for update metrics.** Ongoing port of `UPDATE_*` histograms to Glean APIs under `metrics.yaml`. Review for correct units, bucketing, and ping membership against the legacy histogram.
  Context: likely to fade once all `UPDATE_*` histograms are migrated.
- **Concurrent-instance update handling (bug 2019122 line of work).** Refactoring `IsOtherInstanceHandlingUpdates` / `IsOtherInstanceRunning` and gating staging vs downloading vs applying on whether other instances exist. Be extra cautious about locking semantics and read the linked design doc before touching this code path.
  Context: likely to fade once the new locking + state model is fully landed and verified against the auto-apply path.
- **Desktop launcher / enterprise-policy installation logic.** New helpers under `toolkit/mozapps/update/common/EnterprisePolicies*` and `browser/installer/windows/nsis/desktop_launcher_helpers.nsh` decide whether to install the desktop launcher based on install type (MSI vs full), channel (ESR vs not), and policy presence (HKCU, HKLM, plist, `policies.json`).
  Context: likely to fade once the launcher install matrix is stable and documented.
- **Preferences "Firefox Updates" section migration to config-based prefs.** Moving update UI out of `main.js` into per-component widgets. Prefer splitting "move" patches from "change" patches.
  Context: likely to fade as recomp migration completes.

## Common Pitfalls

- Concluding "no other instance running" after a failed `LockFileEx`/`UnlockFileEx` instead of returning conservative `true`.
- Reusing an `OVERLAPPED` struct across lock calls without zeroing it.
- Adding a new lock byte/file without defining its place in the global lock-acquisition order.
- Hard-coding behavior to "non-ESR" or "full install" without considering the MSI, ESR, and enterprise-policy paths in the installer.
- Referencing `Ci.nsIApplicationUpdateService.STATE_*` (or similar) constants from JS/tests without first adding them to the IDL.
- Reading `MOZ_BACKGROUNDTASKS_NO_DEFAULT_PROFILE` once and assuming subsequent calls re-check it.
- Performing synchronous filesystem work during startup paths invoked by the update service.
- Leaving stale comments referencing removed lock files, elevated-lock logic, or pre-migration histograms.
- Using `RegOpenKeyExA`/`A`-suffixed Win32 APIs in new updater code instead of the `W` versions.
- Opening a file with `FILE_DELETE_ON_CLOSE` and then also explicitly deleting it, or vice versa — pick one cleanup strategy.
- Assuming `ShellExecuteEx`-spawned updater processes inherit (or don't inherit) elevation without verifying against the maintenance service tests.

## File-Glob Guidance

- `toolkit/mozapps/update/updater/updater.cpp` — Elevation detection, MAR channel handling, post-update file operations. Verify behavior under service-launched (SYSTEM) and UAC-elevated launches; keep `#ifdef MOZ_VERIFY_MAR_SIGNATURE` blocks readable by factoring conditional logic into helpers rather than spanning braces across `#ifdef`s.
- `toolkit/mozapps/update/UpdateService.sys.mjs` — Update orchestration and instance-coordination logic. Changes to "is another instance handling updates" semantics need explicit consideration of the auto-apply path. (campaign)
- `toolkit/mozapps/update/nsIUpdateService.idl` — Canonical source of update states and constants used from JS. Update here first, then in callers.
- `toolkit/mozapps/update/metrics.yaml` — Glean metric definitions. Names should describe domain events, not implementation artifacts. (campaign)
- `toolkit/mozapps/update/common/EnterprisePolicies*` / `EnterprisePoliciesFlagFile*` — Policy detection across registry, plist, and `policies.json`. Mind process lifetime when one process writes the flag file and another reads it. (campaign)
- `toolkit/xre/MultiInstanceLock.cpp` — Lock-byte protocol shared across the app. Document the meaning of each byte; enforce acquisition order; zero `OVERLAPPED` before reuse.
- `toolkit/xre/WinTokenUtils.cpp` — Token/identity checks for elevation detection. Every code path must return a defined value.
- `browser/installer/windows/nsis/*.nsh` — NSIS installer/uninstaller helpers. Prefer plain function parameters over macros that generate multiple functions; prefer `${If} "$0" == "esr"` style over opaque `${WordFind}` calls; comment early-returns.
- `browser/components/preferences/main.js` — When adding/moving update-related UI here, prefer splitting into a separate file and submit "move" and "change" as separate patches. (campaign)
- `toolkit/mozapps/update/tests/**` — Use shared helpers to initialize the update service; pick unique lockfile names; reset background-task state explicitly rather than relying on env-var re-reads.

## Review Checklist

- Does any change to locking enforce a documented global lock-acquisition order and handle failure paths conservatively?
- Are `OVERLAPPED` structs zero-initialized and re-offset before every `LockFileEx`/`UnlockFileEx` reuse?
- Does elevation detection key on SYSTEM / unrestricted-admin token, not on a grab-bag of privileges?
- Have all four installer axes (MSI vs full, ESR vs release, policy source, elevated vs unelevated) been considered for installer/post-update changes?
- Are new IDL states/constants added to `nsIUpdateService.idl` before being referenced from JS or tests?
- Are new or moved update metrics defined in `metrics.yaml` with names that describe domain events and bucketing matching any legacy histogram?
- Do tests initialize the update service via shared helpers and avoid reaching into `gAUS` internals?
- Do tests that touch the updater lockfile use unique names to avoid cross-test interference?
- Is startup-path work async and free of synchronous main-thread I/O?
- Are stale comments around removed locks, removed branches, or migrated histograms cleaned up?
- Are new Win32 API calls using the `W` variants, and are new single-arg C++ constructors `explicit`?
- For installer NSIS code, are early-returns commented and string comparisons written in the simpler form rather than via `${WordFind}`?

## Evidence

1. *"set *aResult to true. (The call to this function from nsAppRunner.cpp is a good example of why.)"* — supports the conservative-default rule for instance detection.
2. *"the OVERLAPPED parameter is listed as in/out in the docs... The safe thing to do is to zero out the memory and re-assign the offset."* — supports the OVERLAPPED hygiene rule.
3. *"We are trying to identify whether we have been elevated by the unelevated update process... That is what we want to check for here."* — supports the elevation-detection rule.
4. *"It would be easier if you split this into two separate patches: one to move code from one place to another (with no other changes), and one to make the changes on the code in the new location."* — supports the move-vs-change separation guidance.
5. *"Closing a block in a separate #ifdef makes the code hard to read. I recommend splitting the new code out into a separate function."* — supports the `#ifdef` readability rule for `updater.cpp`.

## House style references

- [JavaScript Coding Style](https://firefox-source-docs.mozilla.org/code-quality/coding-style/coding_style_js.html)
- [C++ Coding Style](https://firefox-source-docs.mozilla.org/code-quality/coding-style/coding_style_cpp.html)
- [Using C++ in Firefox Code](https://firefox-source-docs.mozilla.org/code-quality/coding-style/using_cxx_in_firefox_code.html)
- [Fluent for Firefox Developers](https://firefox-source-docs.mozilla.org/l10n/fluent/tutorial.html)