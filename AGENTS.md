# AGENTS.md

Agent instructions for `ocsjs-ai-answer-service` (EduBrain portable answer service).

## Project map
- Flask app: `app.py` + `config.py` + `utils.py` + `provider_clients.py` + `logger.py`
- Portable Windows GUI: `portable_entry.py` → `portable_app.py` / `portable_controller.py` / `portable_selftest.py` / `portable_paths.py` / `portable_settings.py`
- Packaging: `packaging/verify_portable.py`, `packaging/windows.spec`, `build_windows.ps1`
- Tests: root `test_*.py`, `tests/test_security_and_config.py`, `packaging/test_snapshot_integrity.py`
- Docs: `README.md`, `api_docs.md`, `docs/windows-portable-acceptance-20260907-current.md`

## Hard rules
- **Never read, print, or modify `.env` or live credentials.** Use `.env.example` as the shape reference only.
- Local-only changes: do **not** push to GitHub unless the user explicitly asks.
- Do not invent provider accounts, keys, or billing claims.
- Packaging evidence must keep physical USB and real provider-account validation as **unverified**. Windows 10 x64 physical testing is **user-waived (2026-09-08), non-blocking**.
- Prefer smallest production change that fixes the root cause; no drive-by refactors.
- Do not weaken snapshot/hash integrity gates in `packaging/verify_portable.py`.

## Runtime
- Project venv: `.build\venv\Scripts\python.exe` (preferred for packaging/regression tests)
- System Python may exist (`C:\Python314\python.exe`); prefer the project venv when testing this app
- Node is available for `.cjs` browser/offline asset tests
- Do not reinstall packages into the pinned build venv unless the user asks

## Test commands
```powershell
# Packaging integrity + waiver metadata
& .\.build\venv\Scripts\python.exe packaging\test_snapshot_integrity.py -v

# Portable foundation / settings / provider clients
& .\.build\venv\Scripts\python.exe test_portable_foundation.py -v

# Safety, runtime, offline assets, service (pick what the change touches)
& .\.build\venv\Scripts\python.exe test_app_safety.py -v
& .\.build\venv\Scripts\python.exe test_runtime_completion.py -v
& .\.build\venv\Scripts\python.exe test_offline_assets.py -v
& .\.build\venv\Scripts\python.exe test_service.py -v
& .\.build\venv\Scripts\python.exe tests\test_security_and_config.py -v

# Browser session (may need network/fixtures)
& .\.build\venv\Scripts\python.exe test_browser_sessions.py -v
```

## Coding standards
- Keep Chinese user-facing strings in portable UI/docs; keep packaging evidence notes in English when they are machine-consumed metadata.
- Validate external boundaries (HTTP bodies, paths, ports, model params); trust internal pure helpers.
- Prefer pure helpers for generated evidence so unit tests can assert without a full freeze.
- Preserve transactional config writes and atomic JSON writes.
- No remote scripts/styles in templates (offline vendor assets only).

## Delivery
- Report exact changed files, test commands + results, and remaining unverified limitations.
- Do not claim complete Windows 10/USB/provider acceptance unless new physical evidence exists.
