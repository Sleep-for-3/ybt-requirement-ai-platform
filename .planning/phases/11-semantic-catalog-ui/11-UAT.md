---
status: testing
phase: 11-semantic-catalog-ui
source: [11-VERIFICATION.md]
started: 2026-08-25T15:32:34Z
updated: 2026-08-25T15:32:34Z
---

## Current Test

number: 1
name: Approved viewport and visible-focus matrix
expected: |
  At 320x720, 768x1024, 1280x800, and 1440x900, the populated and exceptional catalog/detail states have no unintended page overflow or overlap. Only deliberate table/tab scrolling occurs; focus remains visible; long content wraps readably; skeletons and notices remain stable; and the bounded chain is nonblank with text/list order matching the visual order.
awaiting: user response

## Tests

### 1. Approved viewport and visible-focus matrix

expected: At 320x720, 768x1024, 1280x800, and 1440x900, inspect populated, empty, forbidden, retryable-error, conflict, audit, historical, restricted-reference, long-text, comparison-table, horizontal-tab, and bounded-chain states by keyboard. No unintended overflow or overlap occurs, focus is visible, and all controls and notices remain coherent.
result: pending

## Summary

total: 1
passed: 0
issues: 0
pending: 1
skipped: 0
blocked: 0

## Gaps

