# Windows portable checkpoint: not ready for delivery

Confirmed target: Windows 10/11 x64. No Windows 7, Windows 8.1, x86, or native ARM64 promise.

## Prepared implementation

- `portable_paths.py`: separate bundled resources and executable-relative writable data.
- `config.py`: portable mode ignores host dotenv, provider environment and cc-switch settings.
- `provider_clients.py`: Anthropic-compatible text adapter for OpenAI Chat and Responses APIs.
- `portable_settings.py`: validated ordinary settings and opt-in password-encrypted portable credentials.
- `portable_controller.py`, `portable_app.py`, `portable_entry.py`, `portable_selftest.py`: native service lifecycle, settings/question UI and synthetic self-test. These are not yet accepted.
- All 11 automatic frontend CDN references were replaced with bundled local assets. The vendor manifest records package/file hashes and original licenses.

## Current evidence

- `test_portable_foundation`, `test_app_safety`, `test_runtime_completion`: 61 tests passed on Windows 11 x64 with the project-local Python 3.14.4 build environment.
- This regression command imported native cc-switch configuration before its test fixtures were applied. Only model/base metadata appeared in output; tests used mocked providers. This run is not evidence of portable host-configuration isolation or actual upstream availability. Subsequent build checks must bootstrap isolated fixtures before importing the application.
- Vendor worker: 8 focused offline-asset tests passed; dashboard JavaScript tests passed; VerifyOnly and idempotent regeneration passed without downloads or writes.
- `packaging/vendor-assets.json` SHA256: `427b36261cf6f233e1132e9b7c6d163431f1b51506cbef120d025fc2e7792616`.
- Native source self-test exited 1 before service startup: `TypeError: Preferences.__init__() got an unexpected keyword argument 'retries'`. The canonical field is `max_retries`. Evidence: `.build/service-source-selftest.json`.

## Pending corrections and acceptance

- Native controller, UI and self-test use `retries` rather than the canonical `max_retries`. Parent requested user confirmation before correcting its newly introduced bug, as required by the host workflow.
- Native copied integration configuration must preserve the existing OCS array shape, title/options/type placeholders and response handler from `api_docs.md`, with current loopback URL and local access token. The prototype currently omits the handler and must not be represented as ready to import.
- Native source self-test, transactional configuration application, authenticated browser/native interactions and service shutdown still require successful checks.
- Packaging preparation is delegated to an internal implementation worker. No service EXE/ZIP is accepted at this checkpoint.
- Packaged no-console behavior, relocation, minimal PATH, bundled TLS/Tk resources, file privacy and exact payload hashes remain pending.
- Windows 10 execution, a clean Windows installation and a physical USB run remain unverified. The Windows Sandbox feature-state query required elevation; no feature was enabled or changed.
- A final independent review must bind the exact final source hashes to a successful, eligible reviewer invocation. Configured model selection is not proof of backend identity.

No host provider defaults, credentials, database schema, or Git history were changed by the portable implementation. Online AI answers still require a user-selected reachable model service and valid credentials; the portable package does not include a local language model or a user's account secrets.
