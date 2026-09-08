# Functional completion

Goal: complete the existing OCS-compatible answer workflow, configuration lifecycle, cache behavior and browser recovery without changing provider configuration or credentials.

## Scope and implementation

| Area | Files | Result |
| --- | --- | --- |
| Runtime and request handling | `app.py` | Degraded startup stays observable; failed reload retains the previous runtime; status readers take a committed snapshot; malformed authentication is rejected as JSON |
| Cache and answer normalization | `utils.py` | Cache writes do not deadlock; field separators cannot cause tuple collisions; in-flight answers do not enter a replacement cache; full option text wins before label parsing |
| Configuration input | `config.py`, `ccswitch.py` | Nonfinite numbers use defaults; malformed configuration and decoding errors fall back; model IDs precede display labels |
| Browser flow | `templates/index.html`, `templates/dashboard.html` | Optional token input, JSON token transport, response recovery, valid dashboard template, token aliases, bounded request and response-body waits |
| Container deployment | `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `gunicorn.conf.py`, `healthcheck.py` | Python 3.12 runtime, explicit runtime file copies, excluded local environment files, configured port, threaded single-process serving and readiness-based health check |

## Verification

- `python -m unittest test_runtime_completion test_app_safety -q`: isolated API, cache, configuration and answer regressions. Import the runtime-completion suite first to avoid loading real provider configuration during these tests.
- `node test_dashboard_logic.cjs`: the actual dashboard script is evaluated with synthetic network responses to check token aliases, Unicode transport, hanging fetches and hanging response bodies.
- Browser checks use a localhost-only fixture provider. They verify UI and HTTP behavior, not model accuracy or real upstream availability.
- Cross-review ran in Codex internal review using the requested `gpt-6-astra` / `max` parameters. Its concrete findings were reproduced and addressed. Claude Code and pi attempts through their current bridge returned a model/client compatibility error; they are not counted as successful implementation or final review.

## Acceptance boundaries

Keep OCS GET, form and JSON field aliases compatible. Preserve option-internal spaces and prefer full option matches. Never treat a failed reload as a successful runtime replacement. Do not print question bodies, complete prompts or answers into routine logs. API error handling must not expose raw initialization exceptions or credentials.

Real upstream/OCS integration, production hosting, and external Claude/pi route compatibility remain separate unverified gates. A passing mocked API suite alone is not full-project completion.

## Container behavior

Compose supplies environment values at runtime; `.env` is not copied into the image. `PORT` controls both the published container port and the Gunicorn bind, with 5000 as the default. The single Gunicorn process keeps the in-memory cache and dashboard records coherent across its worker threads. The health check contacts loopback without environment proxies and requires `runtime_ready: true`; this tests local readiness, not the availability of the upstream model provider.

Container build and smoke-test results are recorded separately from the local Python tests. Docker Desktop may need to be started before building.
