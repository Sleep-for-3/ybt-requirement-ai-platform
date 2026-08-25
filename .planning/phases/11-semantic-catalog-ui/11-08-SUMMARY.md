---
phase: 11-semantic-catalog-ui
plan: 08
subsystem: testing
tags: [nextjs, cdp, browser, semantic-catalog, accessibility]

# Dependency graph
requires:
  - phase: 11-06
    provides: request-key scoped semantic catalog controller and stale-response protection
  - phase: 11-07
    provides: lawful detail disclosures, restricted-reference rendering, and stable evidence controls
provides:
  - dependency-free CDP browser harness over the real semantic catalog routes
  - production catalog and detail browser regression matrix with deferred API responses
  - bounded process, CDP, signal, and temporary-profile teardown
affects: [phase-11-semantic-catalog-ui, SUI-01, SUI-02, browser-regression]

# Actuals (#2632)
actuals:
  tokens: 14881
  tasks: 2
  commits: 5

# Tech tracking
tech-stack:
  added: []
  patterns:
    - dependency-free Node ESM CDP driver using installed Next and Edge/Chrome
    - Fetch interception with held, out-of-order API completions against real routes
    - bounded teardown with CDP command deadlines, child exit waits, profile retries, and signal cleanup

key-files:
  created:
    - frontend/tests/semantic-catalog-browser-harness.mjs
    - frontend/tests/semantic-catalog-browser.test.mjs
  modified:
    - frontend/tests/semantic-catalog-browser-harness.mjs
    - frontend/tests/semantic-catalog-browser.test.mjs

key-decisions:
  - "Use the installed Next runtime and headless Edge/Chrome over loopback with CDP Fetch interception, so assertions exercise the actual /semantics and /semantics/42 routes, effects, apiGet calls, ProjectSelector, tabs, and disclosures."
  - "Treat cleanup as a correctness boundary: every CDP command and child exit is bounded, profile deletion retries and surfaces failure, and active runtimes close on SIGINT/SIGTERM."
  - "Patch AbortController only inside the browser test page to preserve deferred adversarial completions; production code remains unchanged and still owns apiGet cancellation."

patterns-established:
  - "CR-01 browser evidence first paints project A, switches the real selector to B, observes A clearing/loading, then resolves B."
  - "Restricted-reference assertions inspect visible text, DOM/attributes, links, outerHTML, and the accessibility tree."

requirements-completed: [SUI-01, SUI-02]

coverage:
  - id: D1
    description: "Real /semantics catalog route covers project-switch races, loading, both empty variants, retryable 500, unauthorized 403, canonical filters, uncategorized labeling, and pagination boundaries."
    requirement: SUI-01
    verification:
      - kind: automated_ui
        ref: "frontend/tests/semantic-catalog-browser.test.mjs#production browser catalog"
        status: pass
      - kind: automated_ui
        ref: "node --test --test-name-pattern=production browser catalog frontend/tests/semantic-catalog-browser.test.mjs"
        status: pass
    human_judgment: false
  - id: D2
    description: "Real /semantics/42 detail route covers shell/lazy loading, empty/error/retry/403 states, keyboard tabs and focus, restricted markers, conflicts, and independent long disclosures."
    requirement: SUI-02
    verification:
      - kind: automated_ui
        ref: "frontend/tests/semantic-catalog-browser.test.mjs#production browser detail"
        status: pass
      - kind: automated_ui
        ref: "node --test --test-name-pattern=production browser detail frontend/tests/semantic-catalog-browser.test.mjs"
        status: pass
    human_judgment: false
  - id: D3
    description: "The complete production browser file runs all catalog and detail cases with deterministic lifecycle cleanup."
    verification:
      - kind: automated_ui
        ref: "node --test frontend/tests/semantic-catalog-browser.test.mjs"
        status: pass
    human_judgment: false
---

# Phase 11 Plan 08: Production Browser Route Coverage Summary

**Real-route CDP coverage for semantic catalog races, lawful detail states, keyboard disclosures, and bounded browser teardown.**

## Performance

- **Duration:** approximately 49 min
- **Started:** 2026-08-25T19:01:54+08:00
- **Completed:** 2026-08-25T19:50:05+08:00
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Added a dependency-free harness that starts the real loopback Next routes, launches an installed headless Edge/Chrome, intercepts semantic API requests through CDP Fetch, and exposes DOM, focus, keyboard, URL, and accessibility helpers.
- Added six catalog and six detail browser tests using actual production routes and controls, including CR-01 A-to-B loading clearance, independent late success/error cases, retries, unauthorized states, URL canonicalization, focus retention, restricted-marker absence, conflicts, and independent disclosures.
- Hardened lifecycle behavior after an interrupted run: CDP commands, child exits, test cases, and the suite are bounded; cleanup attempts all resources, retries profile deletion, reports failures, and handles SIGINT/SIGTERM.

## Verification Evidence

- Catalog pattern: 6/6 passed; orchestrator final evidence reports 24.3s.
- Detail pattern: 6/6 passed; orchestrator final evidence reports 20.6s.
- Full browser file: 12/12 passed; orchestrator final evidence reports 29.4s.
- Normal frontend test script: 83/83 passed, exit 0, `duration_ms 31072.8198`.
- Frontend lint: exit 0; existing unrelated `react-hooks/exhaustive-deps` warnings remain.
- Lifecycle audit after browser runs: `LIVE_TEST_PROCESSES=0`, `TEMP_PROFILES=0`.

The optional frontend build command was started but interrupted by the user after 26.8s; its result is intentionally unverified and is not represented as a pass.

## Task Commits

Each TDD task was committed atomically:

1. **Task 1 RED: add failing production browser catalog test** - `a3e75b8` (`test`)
2. **Task 1 GREEN: add production catalog browser coverage** - `352b2d6` (`feat`)
3. **Task 2 RED: add failing production detail browser tests** - `b5e3526` (`test`)
4. **Task 2 GREEN: cover production detail browser interactions** - `da352d7` (`feat`)
5. **Lifecycle follow-up: bound browser harness teardown** - `33782df` (`fix`)

## Files Created/Modified

- `frontend/tests/semantic-catalog-browser-harness.mjs` - loopback Next/browser startup, CDP API interception, route interaction helpers, and deterministic cleanup.
- `frontend/tests/semantic-catalog-browser.test.mjs` - real catalog/detail browser regression matrix and fail-safe test bounds.

## Decisions Made

- Keep the harness first-party and dependency-free, using only installed project/runtime capabilities.
- Preserve real production route behavior and use test-only intercepted responses to make completion order and restricted payloads adversarial.
- Make lifecycle cleanup fail loudly rather than silently retaining a child process or temporary browser profile.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed interrupted browser-run teardown leaks**

- **Found during:** post-run lifecycle audit after Task 2
- **Issue:** Windows `taskkill` returned before the child-exit event, profile-removal errors were swallowed, and CDP commands could wait without a deadline; an interrupted run left semantic-catalog browser profiles behind.
- **Fix:** Added CDP command deadlines, process-exit waits and fallback termination, bounded profile-removal retries with surfaced errors, all-phase cleanup aggregation, signal handlers, per-test timeouts, and a suite watchdog.
- **Files modified:** `frontend/tests/semantic-catalog-browser-harness.mjs`, `frontend/tests/semantic-catalog-browser.test.mjs`
- **Verification:** catalog, detail, full browser, and normal frontend tests passed; repeated audits reported zero matching child processes and zero temporary profiles.
- **Committed in:** `33782df`

---

**Total deviations:** 1 auto-fixed (Rule 1 bug)
**Impact on plan:** The fix stayed within the declared test-file scope and closes the plan's browser/server lifecycle threat mitigation without package or production-source changes.

## Issues Encountered

- A prior interrupted focused run left temporary browser profiles after its processes had exited; the bounded teardown fix removed the leak and subsequent audits were clean.
- The optional frontend build was interrupted by the user after 26.8s, so no build-pass claim is made.

## Known Stubs

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- SUI-01 and SUI-02 are covered by executable real-route browser evidence and the full frontend test suite.
- No package, production source, backend, or user WIP files were changed by this plan.

## TDD Gate Compliance

- RED gate: `a3e75b8` precedes `352b2d6` for catalog coverage.
- RED gate: `b5e3526` precedes `da352d7` for detail coverage.
- GREEN implementations and the lifecycle fix are committed separately.

## Self-Check: PASSED

- Summary file exists at the declared path.
- All five plan commits (`a3e75b8`, `352b2d6`, `b5e3526`, `da352d7`, `33782df`) are present in git history.
- Shared dirty and untracked user-owned files remain unstaged and untouched.

---
*Phase: 11-semantic-catalog-ui*
*Plan: 08*
*Completed: 2026-08-25*
