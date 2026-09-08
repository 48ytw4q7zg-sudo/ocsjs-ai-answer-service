# Windows portable delivery plan

## Goal and agreed support

Deliver separate USB-copyable applications for the battery project and the answer service. The user confirmed Windows 10/11 64-bit as the support scope. Build x64 artifacts on the current x64 Windows host; do not claim native ARM64, Windows 7/8.1, or 32-bit validation.

Target computers must not need Python, Docker, package managers, compilers, or existing cc-switch settings. Battery analysis must work offline. Answer generation necessarily needs a reachable provider and user-supplied authorization; no real credentials may be embedded in a release.

## Design

- Use a PyInstaller one-folder distribution with bundled interpreter, libraries and native runtime dependencies. Provide a ZIP of each complete folder, not an EXE separated from its supporting files.
- Resolve bundled resources separately from writable portable data. Use the executable folder as the portable root and handle read-only media without crashing.
- Keep development/native source behavior compatible. Frozen answer-service mode must ignore host `.env`, home-directory provider settings and unrelated provider environment variables.
- Add a native launcher/configuration interface for the answer service. Store ordinary preferences beside the executable; never include existing machine credentials in artifacts. Any credential persistence must be explicitly user-controlled and password-protected with machine-independent encryption.
- Keep the browser UI usable without CDN downloads. Include required frontend assets and licenses, with no automatic third-party tutorial media fetch for offline battery use.

## Files and ownership

| Share | Exact files or output boundaries | Owner |
| --- | --- | --- |
| Battery portable application | `D:/1/HyperBatteryHealthCalc-main/HyperBatteryHealthCalc-bat/portable_entry.py`, `battery_gui.py`, `battery_calc.py`, project `packaging/windows.spec`, `packaging/build_windows.ps1`, portable tests/docs, `.build/`, `dist/` | Bounded GPT-6 max execution share |
| Answer-service portable mode | `portable_paths.py`, `portable_settings.py`, `portable_app.py`, `config.py`, `app.py`, `logger.py`, portable tests | Parent Codex |
| Answer-service distribution | `packaging/windows.spec`, `packaging/build_windows.ps1`, build requirements, `static/vendor/`, templates, `.build/`, `dist/` | Parent Codex |
| Independent audit | Current source/artifact hashes and concrete acceptance evidence | Separate successful qualifying reviewer invocation; retain prior Claude/pi failure evidence and task-only fallback |

## Risks and checks

| Risk | Acceptance evidence |
| --- | --- |
| Hidden runtime dependency | Launch packaged self-tests with a minimal PATH and poisoned host provider variables |
| Absolute paths or machine-local data | Copy complete packages into a different directory with spaces/non-ASCII characters and run again |
| Missing Tk/SSL/frontend resources | Packaged dependency and resource checks, native-launch self-test, browser checks |
| Unintentional credential/data inclusion | Explicit build inputs and release inventory; exclude `.env`, personal logs, provider stores and the real diagnostic ZIP |
| Port conflicts or background leftovers | Configurable loopback service startup, orderly shutdown and task-owned test process cleanup |
| Windows compatibility overclaim | Record actual test OS/architecture and distinguish vendor support from unperformed OS testing |
| Stale audit approval | Record exact reviewed content hashes; any reviewed-content change invalidates approval |

The full goal remains active until portable artifacts exist, relevant functionality is verified, and the requested independent audit is complete. This plan does not narrow the existing project-improvement objective to packaging alone.
