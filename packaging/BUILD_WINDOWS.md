# Windows x64 portable packaging

Use the existing project-local `.build/venv/Scripts/python.exe` (CPython 3.14.4 x64,
PyInstaller 6.22.2). `packaging/build-requirements.txt` keeps the application
requirements and pins the build-only tools. The build validates installed pins
and `pip check`; it does not reinstall packages or modify global settings.

```powershell
& .\build_windows.ps1
```

`-PrepareOnly` creates the allowlist snapshot and runs the source/vendor gates.
The normal command proceeds only when these gates pass. Missing assets, changed
hashes or source self-test errors stop the build and preserve exact evidence.
Application bugs must be corrected by their owner; packaging does not patch them.

Each job lives under `.build/windows-<UTC timestamp>-<id>`. The preparation phase
hashes explicit application modules, packaging inputs, templates, README, notices,
licenses and manifest-listed static assets. It rejects unlisted vendor files and
remote script/stylesheet references. Those exact files are copied into a temporary
snapshot; no .env, host configuration, profile, log, test tree or archive is copied.
The snapshot is tested with pythonw from an unrelated directory and an environment
containing only Windows essentials and disposable project-local user/temp paths.

PyInstaller receives only the prepared entry, explicit dynamic hidden modules and
allowlisted resources. The spec never imports app/config/provider modules. An audit
hook rejects their execution in the analysis process and checks they were not
imported. Build subprocesses have no inherited credential/provider environment,
use isolated home directories and set PYTHON_DOTENV_DISABLED. Original library
metadata, entry points and license texts are retained; installer state and
direct_url.json are not copied. Python/Tk and CA resources are bundled. UPX and
elevation requests are disabled. EduBrain.exe and EduBrain-console.exe share one
`_internal`; the latter is a diagnostic companion, not a separate answer CLI.

The supplemental packaging runtime hook is active only with explicit --self-test
and --self-test-output ABS_JSON arguments. It does not modify application modules
or ordinary launch behavior. It writes a neighboring `.runtime.json` recording
actual standard-stream availability, imported module paths and loaded Python/Tcl/Tk
DLL paths. During synthetic self-tests it rejects non-loopback connections and
external program launches. No real credentials are provided or logged.

Binary acceptance checks all PE headers are AMD64, the expected console/windowed
subsystems, every explicit resource hash, an empty data directory, and a filename
privacy inventory. The only permitted archive is the bundled standard-library ZIP;
the permitted PEM is certifi's public CA bundle. It creates the deliverable ZIP,
checks CRCs, extracts it, and moves the folder into a Chinese-and-spaces path.
Both EXEs then run synthetic protocol/profile/Tk/start-stop self-tests with only
System32 on PATH and a different cwd. Python/Node/Docker are absent from PATH, and
external programs are blocked during these tests. Python/Tk DLLs and application
modules must resolve inside the moved `_internal` directory.

Canonical input and dependency metadata hashes are checked again after each gate;
actual PyInstaller analysis-input file hashes are checked after freezing. Concurrent
changes hold the candidate instead of overwriting another worker's changes.
Only after acceptance passes is the unique release directory moved to `dist/`.
Prior releases are never deleted or overwritten. All recursive cleanup/move targets
are checked for absolute project containment and reparse points first.

The release directory contains `EduBrain/`, `EduBrain-Windows-x64.zip` and
`SHA256SUMS.txt`. Its `data/` is empty. Per-job `evidence/` retains source/resource/
dependency/analysis hashes, source and binary self-test reports, process exits,
PyInstaller output, host version and final `build-result.json`. Failed phases write
`failure-<phase>.json`. A source failure means no binary build was attempted.

This workflow prepares a locally verified, unsigned artifact for parent review.
It is not a qualifying independent review. A minimal PATH run on the build host
does not prove compatibility with every Windows 11 build, a clean OS, physical
USB storage, real model accounts or billing. Those results remain unverified.

Windows 10 x64 remains the documented target, but physical Windows 10 testing was
not performed and is user-waived (2026-09-08); generated `bundle-verification.json`
reports that item as not physically tested, user-waived, and non-blocking. Physical
USB validation and real provider-account validation remain explicitly unverified
and were not waived.

Official packaging references:
- https://pyinstaller.org/en/stable/usage.html
- https://pyinstaller.org/en/stable/spec-files.html
- https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html
