---
description: Review guidance for the Windows NSIS-based browser installer, updater hooks, and related stub/full installer telemetry and registry handling.
---

# Browser Installer Review Skill

This skill captures conventions for reviewing changes under `browser/installer/windows/nsis/`, the stub installer, post-update scripts, and the small amount of C++ in `toolkit/mozapps/update/` that the installer module touches.

## Standing Conventions

### NSIS code structure
- Keep `shared.nsh` from growing further. New logic belongs in a topical `*_helpers.nsh` (e.g. `installer_helpers.nsh`, `uninstaller_helpers.nsh`, `desktop_launcher_helpers.nsh`, `telemetry.nsh`) so it can be included by tests and reasoned about in isolation. Rationale: `shared.nsh` is already a junk drawer and test infrastructure cannot drive functions buried in it.
- When moving code between files, do the pure move in one patch and the edits in a follow-up. Rationale: reviewers cannot diff a combined move+edit, and the stack-of-patches workflow is the documented norm.
- Prefer structured control flow (`${If}`/`${Else}`, named functions) over `Goto` and bare labels. Where labels are unavoidable, give them meaningful names rather than `""` or numeric suffixes. Rationale: NSIS is already hard to read; jumping to anonymous labels makes audits harder.
- Document every register a function reads, writes, or clobbers in a header comment, and prefer contiguous registers (`$0`/`$1`/`$2`) over scattered choices. Save/restore on entry/exit when a function is callable from arbitrary contexts.

### Win32 / C++ in installer-adjacent code
- Use the `W` variants of Win32 APIs (`RegOpenKeyExW`, `GetFullPathNameW`, etc.), not the `A` variants. Rationale: the A wrappers do hidden ANSI↔wide conversions; W is both correct for non-ASCII and the established Mozilla pattern.
- For Win32 APIs that report required buffer size via the return value (e.g. `GetFullPathNameW`), handle all three documented outcomes: success (`ret < nBufferLength`), buffer-too-small (`ret > nBufferLength`), and failure (`ret == 0`). Allocate or retry rather than returning a sentinel string.
- Don't invent string sentinels like `"X:length_error"` to signal failure across function boundaries. Use an explicit out-parameter or success flag. Rationale: stringly-typed error channels invite `"X:length_error" == "X:length_error"` style bugs.
- Follow the standard C++ rules from the house guides: `nullptr` over `NULL`, `using` over `typedef`, `override`/`final` on virtuals, `[[nodiscard]]` on failable functions, braces around every controlled statement.

### Telemetry & install ping
- Any new field added to the install ping schema must be reflected in `mozilla-pipeline-schemas` and in `gcp-ingestion`'s parser before the change rides the trains. Mention the dependency explicitly in the patch description.
- When choosing values for ping fields, verify how `ParseUri` in `gcp-ingestion` interprets them — small integers like `0` and `1` already have assigned meanings (e.g. `old_running`). Don't reuse a value that means something else.
- Treat the install ping as append-only: prefer extracting reusable building blocks into `telemetry.nsh` so the stub and full installers stay schema-aligned.

### Registry & per-user vs. per-machine
- Be explicit about which hive (`HKLM` vs `HKCU`) a write targets and run it in the matching elevation context. The post-update split between "installation" tasks (HKLM, machine state) and "oneuser" tasks (HKCU, current user's profile/desktop) must be respected — do not put HKCU writes on the elevated path or HKLM writes on the per-user path.
- One user's actions must not modify another user's Desktop, Start Menu, or HKCU registry. Operations that target user-scoped resources run as that user, not as SYSTEM, even during updates.
- When normalizing install paths for comparison, mirror how `InstallDir` is set elsewhere rather than rolling ad-hoc casing/separator fixes. Prefer a single helper (e.g. `GetDefaultInstallDir`) over three near-duplicates.

### Testability
- New NSIS functions should be exercised by `browser/installer/windows/nsis/test_stub.nsi` / `test/xpcshell/test_stub_installer.js` where the harness allows. If the harness genuinely cannot test it (no mocking for shell context, registry, elevation, IO), say so explicitly in the patch description with a `#testing-exception-other` justification rather than silently skipping.
- Keep mock/test scaffolding out of production headers. If a function needs a mockable seam, put the mock in the test file, not next to the real implementation.
- Run the existing tests (`./mach test browser/installer/windows/nsis/test/xpcshell/test_stub_installer.js`) whenever editing `test_stub.nsi` or any included header.

### Localization & docs
- FTL changes need `fluent-reviewers`; this is enforced by Herald and shouldn't be worked around.
- When `browser/installer/windows/docs/*.rst` documents a flag, keep flag names, casing, and override semantics (e.g. `/DesktopLauncher` vs `/DesktopShortcut`) in sync between the docs, the parsing code, and the ping field.

## Active Campaigns (transient)

- **Desktop Launcher rollout.** Patches touching `desktop_launcher_helpers.nsh`, `OnInstallDesktopLauncherHandler`, `InstallDesktopLauncherApp`, and the `DesktopLauncherAppInstalled` registry value are part of an ongoing rollout. Watch for: respecting prior user removal of the desktop shortcut, not installing under MSI/ESR/enterprise-policy conditions, and recording the launcher in the shortcut log so uninstall removes it. *Context: likely to fade once the launcher is shipped and the channel/MSI/ESR gating settles.*
- **Stable uninstall registry key migration.** Changes that move installations to a deterministic uninstall key name (for Windows Backup, winget). Reviewers should check that existing installs migrate on update and that winget's discovery isn't broken. *Context: likely to fade after migration code has shipped for a couple of cycles.*
- **NSIS lint enablement.** `file-whitespace` and license-header linting is being turned on across `.nsh`/`.nsi`. New files must pass these; existing files touched in a patch should be cleaned. *Context: likely to fade once lint is enabled globally and CI enforces it.*

## Common Pitfalls

- Adding business logic to `shared.nsh` instead of a topical helper file, making it untestable.
- Calling `GetFullPathNameW` (or similar) with a fixed-size buffer and ignoring the "buffer too small" return.
- Writing HKCU from elevated post-update code, or HKLM from the per-user path.
- Hardcoding registry values like `Mozilla Firefox` where `MOZ_APP_BASENAME` / `BrandFullName` should be used.
- Reusing an install-ping field value that `gcp-ingestion` already maps to a different meaning (especially `0`/`1`).
- Leaving accidental whitespace changes, trailing whitespace, or mixed indentation in `.nsi`/`.nsh` files — `moz-phab` and the new linter will flag these.
- Gating a fix on `${UpdateChannel}` in a way that silently excludes `nightly`/`beta`/`release`/`esr`. Enumerate the channels you intend to cover.
- Using stringly-typed error sentinels from NSIS helpers; prefer an explicit error flag plus an out-parameter.
- Deleting a registry value before confirming the corresponding `Delete` of the file/shortcut succeeded — leaves uninstall in an inconsistent state if re-run.
- Forgetting to update both the installer and the uninstaller when adding a new piece of installed state (registry key, shortcut, log entry).
- Mixing structural moves with behavioral edits in a single patch.
- Adding `!define`s, env vars, or args in an earlier patch that aren't used until a later patch in the stack — keep patches self-contained.

## File-Glob Guidance

- `browser/installer/windows/nsis/shared.nsh` — Don't grow it. New code goes to a topical `*_helpers.nsh`. Audit register usage and document it. (campaign: launcher logic is migrating out.)
- `browser/installer/windows/nsis/installer.nsi`, `uninstaller.nsi`, `stub.nsh`, `stub.nsi` — Keep command-line flag parsing centralized; honor `/Prompt`, `/D=`, `/InstallDirectoryPath=`, `/InstallDirectoryName=` consistently. Be explicit when behavior depends on whether a previous install exists.
- `browser/installer/windows/nsis/telemetry.nsh` and `test_telemetry.nsh` — All install-ping logic flows through here. Any new field needs a paired schema + gcp-ingestion change.
- `browser/installer/windows/nsis/desktop_launcher_helpers.nsh` (campaign) — Channel gating, enterprise-policy gating, MSI gating, and per-user shell-context handling all live or should live here.
- `browser/installer/windows/nsis/postupdate.nsh`, `postupdate_helper.nsh` — Split work clearly into "installation" (HKLM, machine-wide) vs "oneuser" (HKCU, current-user) targets, driven by an explicit argument/env var from the updater.
- `browser/installer/windows/nsis/test/xpcshell/test_stub_installer.js` and `test_stub.nsi` — New NSIS functions should land with tests here when feasible; mocks belong in the test file.
- `browser/installer/windows/docs/*.rst` — Keep flag docs in sync with code; document override relationships between flags.
- `toolkit/mozapps/update/updater/updater.cpp` and `toolkit/mozapps/update/common/` — Prefer generic signaling (e.g. an `EnterprisePoliciesExist` bool) over feature-specific flags (`/DesktopLauncher…`). Use `W` Win32 APIs. Use `MOZ_APP_BASENAME` for the product identifier in registry paths.
- `browser/locales/en-US/installer/*.properties`, FTL files — `fluent-reviewers` group review is required and automatic.
- `build/moz.configure/init.configure` — When special-casing channels (Nightly/Beta/etc.), justify in a comment which channels are intentionally excluded and why.

## Review Checklist

- [ ] New NSIS functions live in a topical helper, not `shared.nsh`, and are tested where the harness allows (or testing-exception is justified).
- [ ] Register usage is documented; no surprising clobbers of `$0`–`$9`.
- [ ] Control flow uses `${If}`/`${Else}` and named labels; no anonymous `""` jump targets.
- [ ] Win32 calls use the `W` variants and handle all documented return cases (success / buffer-too-small / failure).
- [ ] Registry writes use the correct hive for the elevation context (HKLM ↔ installation/system; HKCU ↔ one user).
- [ ] No code path modifies another user's Desktop, Start Menu, or HKCU state.
- [ ] Install-ping schema changes are paired with `mozilla-pipeline-schemas` and `gcp-ingestion` updates; new field values don't collide with existing parser meanings.
- [ ] Channel/edition gating (`nightly`/`beta`/`release`/`esr`, MSI, ESR, enterprise policies) is enumerated explicitly, not implied.
- [ ] Patches are self-contained: moves are separate from edits, and defines/args/env vars are introduced in the patch that uses them.
- [ ] No trailing whitespace, accidental indentation changes, or missing license headers in `.nsh`/`.nsi`.
- [ ] Installer and uninstaller are updated together when adding new installed state.
- [ ] Docs (`browser/installer/windows/docs/*.rst`) match flag names, casing, and override semantics in code.

## House style references

- [JavaScript Coding Style](https://firefox-source-docs.mozilla.org/code-quality/coding-style/coding_style_js.html)
- [C++ Coding Style](https://firefox-source-docs.mozilla.org/code-quality/coding-style/coding_style_cpp.html)
- [Using C++ in Firefox Code](https://firefox-source-docs.mozilla.org/code-quality/coding-style/using_cxx_in_firefox_code.html)
- [Fluent for Firefox Developers](https://firefox-source-docs.mozilla.org/l10n/fluent/tutorial.html)