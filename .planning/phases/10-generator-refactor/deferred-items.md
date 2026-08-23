# Phase 10 Deferred Items

## 10-03: Existing Windows productization test failures

- `backend/tests/test_productization.py::test_windows_secret_acl_commands_remove_explicit_extra_access_and_are_idempotent` fails on this host because PowerShell `Get-Acl` serializes `AreAccessRulesProtected` as `null` after successful `icacls` calls. The test was run both inside the required regression group and in isolation; it is unchanged from the 10-03 starting commit.
- `backend/tests/test_productization.py::test_windows_lifecycle_script_without_action_keeps_control_console_open` fails on this host because the interactive `项目启停.ps1` process does not exit within 10 seconds after receiving `0`. The test file and lifecycle script are outside Plan 10-03 and were not modified.
- The remaining required regression group passes with these two existing environment-specific cases deselected: `75 passed, 2 deselected in 34.39s`.

Owner: future productization/Windows runtime qualification. Status: open.
