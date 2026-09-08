> 2026-09-08 验收范围更新：用户明确允许省略 Windows 10 实机测试。目标平台仍为 Windows 10/11 x64；Windows 10 实机结果为“未验证，用户已豁免”，不再作为交付阻塞项。下文历史记录中“Windows 10 待验收/待提供环境”等表述仅反映当时状态，以本条更新为准。Windows 11 的已有运行证据不变；本更新不扩大为 Windows 7/8.1、32 位或原生 ARM64 支持，也不声称完成了实体 U 盘实测。

# Windows portable acceptance checkpoint

Date: 2026-09-07. Agreed target: Windows 10/11 x64.

## Decision

The approved snapshot-integrity repair passed its failing-to-passing regression,
14 focused tests and a separate successful GPT-6 Astra/max static review. A new
candidate was then built successfully and passed source, relocated GUI/console
and actual clean Windows 11 Sandbox acceptance.

This is an accepted Windows 11 candidate within the recorded test scope, not a
claim of complete Windows 10 validation or completion of the entire two-project
goal. Actual Windows 10 execution and physical USB testing remain unverified.

## Current deliverable

- Release: `D:\1\ocsjs-ai-answer-service\dist\EduBrain-Windows-x64-20260907-141124-4a1515`
- ZIP: `EduBrain-Windows-x64.zip`, 38,100,164 bytes.
- ZIP SHA256: `5FA373BAF7C54AC2CA1E76EBE783FB7DFDD3D2819EB77FB97C176F5243D70107`
- GUI: `EduBrain\EduBrain.exe`, 10,889,956 bytes.
- GUI SHA256: `9A29F113A35878601C1D39E55338AA22BD17D9EACD3C40BD39359F399B43A39D`
- Console: `EduBrain\EduBrain-console.exe`, 10,893,028 bytes.
- Console SHA256: `82E673E5C4A1785994EA81B671DAF4459EC2612F49ADDEB2903E432077D2D1C5`
- Expanded payload: 1,157 files, 65,360,819 bytes; shipped `data` directory empty.

Extract the ZIP, retain the entire `EduBrain` folder and launch `EduBrain.exe`.
Do not separate the executable from `_internal` or launch it inside the ZIP.
The target does not need Python, Node.js, Docker or programming software.
The application-data folder must be writable. Native UI and bundled web assets
are local; real AI answers still require the user's authorized provider access,
credentials and network connectivity. No real credentials are included.

## Repair and review closure

The original synthetic reproduction kept canonical `app.py` unchanged but
modified its build snapshot; the old guard accepted it. The repaired guard now
compares exact snapshot membership, sizes and SHA256 values with the canonical
baseline at prepare/freeze/verify/record gates. PyInstaller Analysis has guards
before and after execution. Its scripts, pure modules, binaries and data origins
are recorded, and all snapshot origins must match the canonical source manifest.
The build recorded 39 snapshot inputs; all were bound to the same source manifest.

| Reviewed file | SHA256 |
| --- | --- |
| `packaging/verify_portable.py` | `1C787E2C3E07B384CCD1208CC22D8C5FEA0E882A5451CF1DC95EB4F8B0AF92CD` |
| `packaging/windows.spec` | `EC70809B712F719AEE371029EEA5B75C09DC6C09C9653AF2AB197A23785D7725` |
| `packaging/test_snapshot_integrity.py` | `57A283433FEB5F3BDA00263DCD5F40DFE0A4421B42FA57EF53EE56A23D5423FC` |
| `build_windows.ps1` | `1E11EA527997755D9F68E42DCF270ED4BDCD87E76D3689247215D6DAA8EBA59B` |

Independent review: all four requirements PASS, no scoped P0/P1/P2 findings.
CLI exit: 0. CLI session: `01a07c2d-da62-78e2-a8cb-486408de11fe`.
Requested/configured model: `gpt-6-astra`, effort `max`, provider label `custom`.
Official eligibility was refreshed on the audit date using the OpenAI
[model catalog](https://developers.openai.com/api/docs/models) and
[GPT-6 Astra page](https://developers.openai.com/api/docs/models/gpt-6-astra).
This establishes the documented model and invocation selection, not an
unobservable custom backend or billing identity.

The review report is
`D:\1\ocsjs-ai-answer-service\.build\snapshot-integrity-repair-20260907-140101-4a78eb\independent-integrity-audit.txt`.
Its SHA256 is
`BA606485FD7EC0CDCD3A2D8D2D0E421AF84EB0FD519B12BC45B9D3888C844927`.
The matching CLI receipt and terminal record are in the same directory.

This build's source manifest SHA256 is
`5C61185020D5EC004A3A7739FD921C193CED41FEE772F548259C41CDC5488EFF`.
The recorded Analysis manifest references that exact value. The four packaging
inputs and six previously reviewed changed application inputs were additionally
matched against this build baseline. No application/business source was changed
for this packaging repair.

## Execution matrix for this candidate

| Check | Result | Scope |
| --- | --- | --- |
| Focused integrity tests | 14 passed, exit 0 | Changed/missing/extra snapshot files, unchanged canonical reproduction, path traversal, Analysis identity/hash/completeness and pre-freeze refusal |
| Stock Windows PowerShell 5.1 default build | Exit 0 | No `-Python` override; project-local build runtime |
| Source windowed self-test | 21 checks, exit 0 | Isolated source snapshot and no-console audit |
| Relocated frozen GUI | 21 checks, exit 0 | Chinese/space path, unrelated working directory, minimal PATH |
| Relocated frozen console | 21 checks, exit 0 | Same isolated relocated payload |
| Runtime origin | Passed for both executables | Modules and three Python/Tcl/Tk DLLs inside `_internal` |
| Test network/process boundary | 19 loopback connections and zero external-process attempts per executable | Real SDK adapters against synthetic local endpoints, not real provider accounts |
| Native architecture | 37 native PE files AMD64 | GUI subsystem 2, console subsystem 3 |
| Resources | 27 resources, including API documentation; vendor manifest checked | No CDN needed for the bundled pages |
| ZIP and clean payload | CRC passed, exact inventory, empty shipped data | Original release kept separate from runtime test copies |
| Actual clean Windows Sandbox | GUI 21 and console 21 passed, both exit 0 | Kernel 10.0.26100, explicitly Windows 11; no development command on System32-only PATH |
| Sandbox relocation and isolation | Passed | Guest verifies ZIP/EXE hashes and extracts into a Chinese/space path; network and shared clipboard disabled |
| Sandbox runtime origin | Passed | All recorded module/native paths inside the extracted bundle, three native runtime DLLs each |

Build host: Windows 11 Pro 25H2, build 26200.9168, AMD64. Sandbox guest:
Windows 11, kernel 10.0.26100. The Windows NT `10.0` kernel string is not evidence
of Windows 10. The runner installed no software. Its completed test launcher was
identified by its exact task path and closed after successful guest results.

## Preserved application and integration work

- Transactional configuration updates restore the previous usable runtime on
  failure; retry preferences use the correct `max_retries` field.
- OCS export retains its expected one-item list schema, placeholders and handler.
- Browser navigation uses an HTTP-only session instead of placing the token in
  the dashboard URL; token rotation revokes old sessions.
- Cleanup errors cannot be reported as successful self-tests.
- The Anthropic adapter handles supported SDK parameters before dispatch and
  uses bundled CA certificates without inheriting host proxy settings.
- Cache/runtime locking, option matching, segmented input handling, finite input
  validation, degraded startup and safer logging remain covered by prior tests.
- GUI profile persistence is opt-in encrypted storage, separate from ordinary
  preferences and not bound to a particular computer's DPAPI identity.
- Dashboard and homepage assets, including localization, are bundled locally.
- No `.env`, provider defaults, cc-switch configuration, account keys, database
  schema or system security setting was changed by this repair.

Prior source/offline regression evidence records 69 checks plus nine browser
session checks, and both JavaScript suites passed. The separate repaired-source
review is `.build/repaired-source-audit-20260907.txt`.

Current-source Docker acceptance remains separate evidence, not a portable-user
prerequisite: 47 API/runtime tests, nine browser-session tests, 17 real-SDK/image
checks and seven default HTTP/session/readiness checks passed; Docker's actual
health status became healthy. Five temporary containers were removed. Local-only
image ID:
`sha256:a05b418ee474c16d601e60d10352702762ea83876a885a660bc00dd4602f57aa`.
Evidence is under
`.build/container-acceptance-20260907-122142-aa88baa5/`.
The host `.env` was not read, mounted or copied into that image.

Native manual inspection previously exercised all four service tabs, a synthetic
unconfigured question, status refresh, help and normal close. That inspection
used the earlier `DF4386...` executable, not this new binary hash. This candidate
has fresh automated native/self-test evidence; do not relabel the earlier manual
walkthrough as a fresh manual run. The earlier browser fixture also demonstrated
token-free dashboard navigation. No real model account was used for those checks.

## Evidence index

- Current build evidence: `D:\1\ocsjs-ai-answer-service\.build\windows-20260907-141124-4a1515\evidence`
- `build-result.json` SHA256: `5106EF21378EBA24D55C9AFBBAD933D81FA0630E453607202654C7977801CEFE`
- `source-verification.json` SHA256: `E7D5FEC8C060DA4513F9A2E0C4112495A3F7A2C72B53438662670BD3C9651B99`
- `bundle-verification.json` SHA256: `0B5143657D0D5650ECAFDB5ADA6DC0728044799900F40C4FDAFA2C7217C3F137`
- Focused tests, direct build receipt and compact build acceptance: `D:\1\ocsjs-ai-answer-service\.build\snapshot-integrity-repair-20260907-140101-4a78eb`
- Clean Sandbox result: `D:\1\ocsjs-ai-answer-service\.build\clean-windows-20260907-5fa373\out\result.json`
- Sandbox-result SHA256: `6EFBE7EF39DBEB5E4C88B278DC6300154C4CE3CEC80BB365E6FDD896A4EEDFD4`
- Sandbox compact result and cleanup: `.build/clean-windows-20260907-5fa373/acceptance-summary.json`
- Prior manual UI observations: `.build/native-ui-acceptance-20260907.json`

Generated build records retain their original preparation-stage status. This
checkpoint pairs them with the independent review and subsequent Sandbox proof;
it does not rewrite historical evidence or grant global Windows approval.

## Failures, execution lanes and remaining limits

The bounded internal build helper's startup request ended with exit `-1` and no
output; no actual build result was obtained from that request. Its immutable
failure handoff remains under `.build/rebuild-acceptance-20260907-29e2e4db/`.
The parent confirmed no leftover build process and recovered by invoking the
existing build entry directly, which exited 0. The helper did not perform the
successful build or an independent review.

Claude Code and pi previously returned documented HTTP 400 protocol/version
errors on the requested model route. They were not retried unchanged in this
repair. The task-authorized fallback was a separate successful Codex CLI review
invocation, not an internal helper relabeled as another harness. This statement
does not diagnose the user's present account or cc-switch settings.

Packaging metadata/RECORD identities do not prove every installed dependency byte
matches upstream; the integrity guard addresses accidental/concurrent drift at
the recorded build boundaries, not a malicious administrator controlling the
entire build host. Optional packaging warnings are not silently treated as proof
that every possible third-party feature was exercised.

1. Actual Windows 10 x64 startup and feature acceptance: unverified; a target
   machine is still needed.
2. Physical USB and other hardware/managed-device policies: unverified.
3. Real provider accounts, credentials, model availability and billing: unverified;
   synthetic local protocol checks are not account certification.
4. Windows 7/8.1, 32-bit systems and native ARM64 are outside the agreed target.

Older release directories and failed checkpoints remain preserved. Use the exact
current ZIP and executable hashes above when continuing acceptance.
