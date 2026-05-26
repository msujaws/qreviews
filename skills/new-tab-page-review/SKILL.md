---
description: Durable review guidance for Firefox New Tab Page patches, covering React/JSX conventions, SCSS/CSS correctness, design tokens and HCM, localization, testing, and accessibility.
---

# Module Scope

- Paths: `browser/components/newtab/**/*`, `browser/extensions/newtab/**/*`
- Bugzilla components: Firefox::New Tab Page

# Core Reviewers

- Owner: thecount
- Peers: ini, maxx, mconley, nbarrett, nina-py, rhamoui

# Standing Conventions

## Design Tokens, HCM & Accessibility
- Use design tokens instead of literal colors or pixel values. Hard-coded `fill`, `color`, or `background` values that don't resolve to tokens are review-blocking.
- On High Contrast Mode (HCM), active UI must have full opacity and correct system-color pairs (e.g. `ButtonText` paired with `ButtonFace`, not `CanvasText`). Transparency on active UI is not acceptable.
- Interactive elements need persistent `aria-label`s, `aria-expanded` on toggles, and semantic HTML (`<h*>`, `<dialog>`) instead of generic `<span>` / `<div>`.

## React & JSX
- Hooks must come before any early return; placing `useState` / `useEffect` after `if (...) return` causes React error #310.
- Prefer functional components with hooks over class components. New work shouldn't introduce class components; existing ones are candidates for conversion.
- Don't rely on event bubbling for click-outside / close handlers. Compare `e.target === e.currentTarget`, or attach / detach listeners on visibility transitions.
- Scope class-name selectors narrowly. Broad names like `.small-widget` bleed across components — prefix with a size / widget context (e.g. `${size}-widget`).

## SCSS / CSS
- Reset UA defaults on `<dialog>` (at minimum `padding` and `margin`) before styling.
- Avoid `backdrop-filter: blur()` — documented perf regression.
- Use kebab-case class names, not BEM. Project convention is kebab-case throughout.
- When using the `animation` shorthand, don't also set `animation-delay` separately — the shorthand overrides it. Pick one form.
- Run `./mach npm run bundle --prefix=browser/extensions/newtab` in the same patch as SCSS changes so `css/activity-stream.css` matches the source.

## Localization (.ftl)
- A change to a string's meaning or attributes requires a new Fluent ID and a migration. Reusing an ID drops translations.
- Don't edit `browser/extensions/newtab/webext-glue/locales/**` — it's regenerated at train-hop.
- Canonical source is `browser/locales/en-US/browser/newtab/newtab.ftl`. All user-facing string edits land there.
- Don't impose English sentence structure on other locales — avoid splitting a message into multiple attributes keyed to English word order.

## Testing
- Unit tests must assert the actual behavior, not just non-existence. For "feature X is hidden when toggled off," first assert X is present in the default case, then toggle, then assert gone.
- Any new UI toggle in the Customize Panel needs a browser test end-to-end, not just a unit test. Existing weather / toggle tests are the blueprint.
- Check that props actually changed between `prev` and `current` — tests that compare identical objects detect nothing.

## Prefs, Actions & Bundle Hygiene
- Pref migrations must cover all prior UI states (watch for compound states like `weather.display`). Wrap init hooks in try / catch.
- Name system prefs `PREF_SYSTEM_*` for consistency with existing code.
- Keep `common/Actions.mjs` alphabetized; the compiled bundle must match.
- Shared constants (e.g. `DEFAULT_USER_CTR`) live in a single file — don't duplicate across modules.
- In hot loops, prefer `Set.has` over `Array.includes` for membership checks.

## Assets
- Optimize new SVGs with `svgo`. Prefer SVG over GIF. Include the license header.

# Active Campaigns (transient)

- **Nova layout rollout**: New CSS must be scoped to `.nova-enabled`. Treat Nova as the eventual default — write styles so when `.nova-enabled` becomes unconditional, nothing has to migrate back; classic rules go behind `.classic-enabled` overrides. Unguarded changes that regress the classic layout are blockers, and Nova styles should not introduce breakpoints the classic layout doesn't have. Context: likely to fade once Nova ships as the default and `.nova-enabled` is removed.

# Common Pitfalls

- CSS changes not scoped to `.nova-enabled`, regressing the classic layout. (campaign)
- Missing Testing Policy Project Tag on the revision.
- Editing `browser/extensions/newtab/webext-glue/locales/**` (read-only; regenerated at train-hop).
- `.ftl` attribute changes without a new ID + Fluent migration.
- Hard-coded colors or transparency on active UI in HCM; wrong color-pair (e.g. `CanvasText` where `ButtonText` is required).
- `<dialog>` used without resetting UA `padding` / `margin`.
- Hooks placed after early returns; class components where a functional + hooks component would fit.
- Click-outside-to-close handlers that rely on uncontrolled bubbling, with no `stopPropagation` safety.
- `backdrop-filter: blur()` in new styles; unoptimized SVG / GIF assets.
- Forgetting to regenerate the activity-stream bundle after SCSS changes — reviewers catch stale diffs via stylelint / license Mozlint errors.
- Duplicating constants across files; using `Array.includes` in hot loops where a `Set` fits.
- `common/Actions.mjs` out of alphabetical order or out of sync with the bundle.
- Accessibility affordances (labels, `aria-expanded`, dialog semantics) added only partially.

# File-Glob Guidance

- `browser/extensions/newtab/content-src/components/**/*.jsx` — React correctness: hook order, bubbling / `stopPropagation`, class → functional conversions, semantic HTML (`<h*>` vs `<span>`, `<dialog>`), `aria-label` / `aria-expanded` on interactive elements.
- `browser/extensions/newtab/content-src/components/**/_*.scss`, `content-src/styles/nova/**` — Design tokens over literals; kebab-case class names; `<dialog>` resets; avoid `backdrop-filter: blur()`; animation shorthand vs `animation-delay`; HCM color pairs; full opacity on active UI. Scope to `.nova-enabled` (campaign).
- `browser/extensions/newtab/css/**/activity-stream.css` — Must match the SCSS source in the same patch; regenerated via the bundle command.
- `browser/extensions/newtab/data/content/assets/**` — Optimize SVGs (`svgo`); prefer SVG over GIF; include license header.
- `browser/extensions/newtab/lib/**.sys.mjs` — Pref migrations cover all prior UI states; try / catch around init hooks; non-critical fetches shouldn't make `Promise.all` fatal; system prefs named `PREF_SYSTEM_*`.
- `browser/extensions/newtab/lib/InferredModel/**`, `InferredPersonalizationFeed.sys.mjs` — Shared constants in one place; `Set` for membership checks in loops; don't recompute smoothing / normalization twice.
- `browser/extensions/newtab/common/Actions.mjs`, `data/content/activity-stream.bundle.js` — Keep actions alphabetized; bundle regenerated in the same diff.
- `browser/extensions/newtab/test/jest/**`, `test/unit/**`, `test/browser/**` — Real assertions (positive baseline before negative assertion); browser test for every new Customize Panel toggle; check for stale expectations after class / pref renames.
- `browser/extensions/newtab/webext-glue/locales/**` — Do NOT edit; regenerated at train-hop.
- `browser/locales/en-US/browser/newtab/newtab.ftl` — Canonical string source; new IDs + Fluent migrations on meaning changes; avoid English-shaped multi-part strings.
- `browser/components/newtab/AboutNewTab*.sys.mjs`, `lib/cache.worker.js` — Worker has no `document`; plumb locale direction from the parent rather than defaulting to LTR; try / catch around init hooks.

# Review Checklist

- [ ] Design tokens used; HCM color pairs correct; no transparency on active UI.
- [ ] `<dialog>` UA defaults (`padding`, `margin`) reset; no `backdrop-filter: blur()`.
- [ ] Class names kebab-case; SCSS + compiled CSS both updated (bundle regenerated).
- [ ] SVG assets optimized; SVG preferred over GIF; license header present.
- [ ] React: no hooks after early returns; event handlers don't rely on fragile bubbling; semantic elements used.
- [ ] `.ftl` edits only in `browser/locales/en-US/...`; new / changed attributes get a new ID + migration.
- [ ] Accessibility: persistent `aria-label`s, `aria-expanded` on toggle buttons, dialog semantics.
- [ ] Prefs / migrations cover all prior UI states; system prefs named `PREF_SYSTEM_*`.
- [ ] `common/Actions.mjs` alphabetized; bundle matches.
- [ ] Unit tests assert actual behavior (positive baseline before negative); browser test added for new Customize Panel toggles.
- [ ] Testing Policy Project Tag applied; Mozlint (stylelint / eslint / license) clean.
- [ ] Train-hop considerations: no edits under `webext-glue/locales/**`; worker code receives locale direction from the parent.
- [ ] (campaign) Nova changes scoped to `.nova-enabled`; classic layout unaffected.
