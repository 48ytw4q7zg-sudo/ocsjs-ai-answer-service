---
feature: windows-10-waiver-evidence
status: delivered
updated: 2026-09-08
branch: main
commits: uncommitted-working-tree
---

# Windows 10 Waiver Evidence Alignment

## Report

**What was built** — Generated Windows portable build/release evidence now distinguishes the 2026-09-08 user waiver from still-open gaps. `packaging/verify_portable.py` exposes pure helpers `release_status()` and `release_evidence_status()`. `verify()` spreads those fields into `bundle-verification.json`: Windows 10 x64 is `physically_tested=false`, `user_waived=true`, `blocking=false`; physical USB and real provider accounts stay explicitly unverified and unwaived. Packaging docs and the current acceptance remaining-limits text match that contract.

**Verification** — `D:\1\ocsjs-ai-answer-service\.build\venv\Scripts\python.exe packaging\test_snapshot_integrity.py -v` → 18 tests, OK (includes 4 new `ReleaseStatusMetadataTests`). Independent review: all 5 acceptance criteria met; no critical findings.

**Journey log**
- Acceptance document already had the waiver header; the gap was only generated evidence and packaging docs.
- Extracted a pure helper so tests assert metadata without a full freeze.
- First provider note omitted the literal “not waived” string; production note was tightened to match the USB wording.

## [S1] Problem

`docs/windows-portable-acceptance-20260907-current.md` already records the 2026-09-08 user waiver: physical Windows 10 x64 testing may be omitted and is non-blocking. Generated build/release evidence from `packaging/verify_portable.py` still emitted a flat `unverified` list that treated Windows 10 like every other unfinished item. Downstream packaging docs also omitted the waiver. Evidence must distinguish:

- Windows 10 x64: not physically tested, user-waived, non-blocking
- Physical USB filesystem: explicitly unverified
- Real provider accounts/credentials/billing: explicitly unverified

## [S2] Design

Add pure helpers in `packaging/verify_portable.py`:

- `release_status()` returns structured status for the three waiver-relevant items (`physically_tested`, `user_waived`, `blocking`, `note`).
- `release_evidence_status()` returns `unverified` (annotated Windows 10 entry) plus `release_status`.

`verify()` spreads `**release_evidence_status()` into the saved `bundle-verification.json`. Delivered notes:

```json
{
  "unverified": [
    "Windows 10 x64 (not physically tested; user-waived 2026-09-08; non-blocking)",
    "Other Windows 11 builds",
    "A clean OS without installed runtimes",
    "A physical USB filesystem",
    "Real provider credentials/accounts/billing"
  ],
  "release_status": {
    "windows_10_x64": {
      "physically_tested": false,
      "user_waived": true,
      "blocking": false,
      "note": "Not physically tested; user-waived 2026-09-08; non-blocking. Target remains Windows 10/11 x64."
    },
    "physical_usb": {
      "physically_tested": false,
      "user_waived": false,
      "blocking": false,
      "note": "Explicitly unverified. Physical USB filesystem and managed-device policies were not tested and were not waived."
    },
    "real_provider_accounts": {
      "physically_tested": false,
      "user_waived": false,
      "blocking": false,
      "note": "Explicitly unverified; not waived. Synthetic local protocol checks are not real account, credential, model-availability, or billing certification."
    }
  }
}
```

## [S3] Out of Scope

- No new Windows 10 physical test
- No change to USB or provider-account verification
- No rebuild of `dist/` artifacts in this feature
- No HyperBattery packaging change
- No `.env` or credential access
- No GitHub push

## Tasks
- [x] T1: Add `release_status()` / `release_evidence_status()` and wire into `verify()` evidence — acceptance: structured waiver/non-waived fields and annotated Windows 10 `unverified` entry (covers: S2)
- [x] T2: Align `BUILD_WINDOWS.md`, `PORTABLE_README.txt`, and current acceptance remaining-limits text — acceptance: Win10 waived/non-blocking; USB and real accounts still unverified (covers: S2)
- [x] T3: Add focused regression tests for generated status metadata — acceptance: USB and provider items stay unwaived; helper shape asserted (covers: S2; depends: T1)
- [x] T4: Run affected packaging tests — acceptance: `packaging/test_snapshot_integrity.py` exit 0, 18 tests (depends: T1, T3)
