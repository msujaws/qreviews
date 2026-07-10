---
name: review-using-docs
description: Use this skill when reviewing changed files in a directory and relevant reference material (docs and schemas) should be selected from /mots.yaml before performing a normal code review.
---

# Review Using Docs

Use this skill when the user asks for a code review that should consult reference material first.

## Workflow

1. Identify the review scope.
   - Determine the requested directory, files, or patch range.
   - Get the changed file list from the active VCS.
   - Limit the review to changed files inside the requested scope unless the user asks for a broader review.

2. Map changed files to Mots modules.
   - Read `/mots.yaml`.
   - Match each changed file against module `includes` and `excludes`.
   - If multiple modules match, choose the most specific matching module.
   - Record the mapping from changed file to module name and `machine_name`.

3. Select reference material from Mots.
   - For each matched module, scan its `includes` list.
   - Treat an entry as a reference-material path if it contains `docs` outside of `docshell`, or contains `schema`/`schemas` (i.e., the regex `docs(?!hell)|schemas?` matches the entry).
   - Also include any paths listed under the matched module's `machine_name` in the **Module Overrides** section below.
   - If the entry is a glob or directory, read the files it expands to.
   - Deduplicate entries across `/mots.yaml` and the overrides table.
   - If neither `/mots.yaml` nor the overrides table yields a qualifying entry for the matched module, the module has no listed reference material — note this and continue with ordinary review.

4. Read reference material before reviewing code.
   - Extract expected behavior, architecture, invariants, API contracts, ownership boundaries, and testing expectations.
   - Track which reference material informed which files or modules.
   - If a matched module has no qualifying entries in `/mots.yaml` or the overrides table, say so briefly and continue with ordinary review.

5. Review the changed code normally.
   - Prioritize correctness, regressions, edge cases, API contract mismatches, missing tests, maintainability, and security or privacy risks.
   - Compare implementation and tests against the reference material from `/mots.yaml`.
   - Use reference material as a source, not unquestionable truth.
   - Flag stale or misleading reference material only when the mismatch creates real engineering risk.

6. Report findings.
   - Findings first, ordered by severity.
   - Include precise file and line references.
   - Mention the relevant reference material when it supports a finding.
   - Include open questions or assumptions.
   - Keep any summary brief and secondary.

## Module Overrides

These supplement `/mots.yaml` `includes` while the corresponding upstream
mots.yaml patches are in review. Treat each listed path as a reference-material
source for the named module. Remove an entry once the upstream mots.yaml change
lands.

- `inproduct_messaging`
  - `browser/components/asrouter/docs/**/*`
  - `browser/components/aboutwelcome/docs/**/*`
  - `toolkit/components/messaging-system/schemas/**/*`
  - `browser/components/uitour/docs/**/*`
  - **Remove when:** all four paths appear under `inproduct_messaging` in `/mots.yaml`.

## Firefox Notes

- Follow repository search guidance from `AGENTS.md`.
- Use `searchfox-cli` for Firefox source discovery outside local changed files.
- Use narrow local commands for changed-file discovery and reading selected reference material.
- `/mots.yaml` is the source of module path metadata and review reference-material links, supplemented by the **Module Overrides** section above for modules whose upstream mots.yaml patch is still in review.
- Entries in matched modules' `includes` whose path matches the reference-material regex (`docs(?!hell)|schemas?`), plus any module-specific override paths, are the source of truth for reference material.
