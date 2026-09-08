# Portable browser and cleanup audit: 2026-09-07

Status: additional source-level evidence collected; the portable release is not accepted.

## Executed browser checks

The service ran only on loopback port 65114 with `CONFIG_SOURCE=portable`, an explicitly synthetic local access token, a synthetic model client, and an unreachable loopback fallback provider. No real account key or external model request was used. The browser fixture exercised the existing Flask application, not the currently blocked native launcher.

- The home page loaded bundled Bootstrap CSS and local style CSS successfully.
- Submitting an invented question and the options Alpha/Beta with the synthetic local token returned HTTP 200 and displayed the synthetic answer Alpha.
- Clicking the home page's statistics navigation link then requested `/dashboard` without authentication and returned HTTP 403 with the visible invalid-token message.
- Opening the same dashboard with the explicit synthetic token returned HTTP 200.
- All dashboard Bootstrap, jQuery, DataTables and responsive-adapter assets were fetched locally with HTTP 200/304. The bundled Chinese language JSON returned HTTP 200.
- The dashboard displayed the synthetic question record, Chinese pagination/search controls and cache count.
- The Details button opened the Bootstrap modal and displayed the same synthetic question, options and answer.
- The temporary browser tab was closed. The owned preview process was positively identified through its project-venv command line and parent process, then stopped. Its original execution handle reached a terminal state after intentional termination.

## Newly confirmed navigation defect

The home form's successful authenticated question request does not transfer authentication when its statistics link is followed. The browser reaches an invalid-token page with no recovery control instead of the dashboard. This is an observed end-to-end navigation failure, not an inference from the source tests. The same user-supplied token succeeds when explicitly included in the dashboard request.

An eventual correction must preserve authentication deliberately without persisting the real provider key, silently changing provider settings, or claiming the page is usable merely because the question API passed. This correction is pending user confirmation together with the previously reported native-startup, OCS-config and battery-file-selection issues.

## Windows cleanup boundary check

A separate synthetic check created a task-owned temporary directory below `.build`, opened a logger with the current `setup_logger`, and attempted the standard temporary-directory cleanup.

Observed result:

```json
{
  "test": "windows_open_log_cleanup",
  "uses_real_credentials": false,
  "cleanup_blocked_while_logger_open": true,
  "cleanup_after_closing_handlers": "passed"
}
```

This proves the Windows file-handle cleanup boundary. It is not a successful run of the native self-test, which still fails earlier on the `retries`/`max_retries` mismatch.

The native self-test must close its task-owned log handlers before temporary-directory teardown and must report failure if cleanup fails. Its current success flag is assigned before the temporary context exits, so this ordering also needs an explicit failure-path check before binary acceptance. No correction was applied during this audit.

## Packaging preparation received

The internal packaging worker prepared `build_windows.ps1`, `packaging/windows.spec`, `packaging/verify_portable.py`, `packaging/PORTABLE_README.txt`, `packaging/BUILD_WINDOWS.md`, and pinned `packaging/build-requirements.txt`. These files remain preparation only: no EduBrain build or binary acceptance was run, and no service EXE/ZIP is approved.

The worker completed without editing the native application, its provider settings, browser templates/assets, or the battery project. Both bounded internal workers are now closed; no background build is being treated as still running.

## Remaining acceptance boundaries

The previously recorded 61 service tests and 8 offline-resource tests do not establish native startup, portable self-test cleanup, actual upstream account availability, clean-OS portability, Windows 10 execution, or physical USB operation. Final source fixes, affected-path checks, packaged execution and a qualifying independent exact-hash audit remain pending.
