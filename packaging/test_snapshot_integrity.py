"""Synthetic regression tests for the reviewed-source packaging boundary."""

import importlib.util
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, call, patch


SPEC = importlib.util.spec_from_file_location(
    'portable_integrity_under_test', Path(__file__).with_name('verify_portable.py'))
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)


class SnapshotIntegrityTests(unittest.TestCase):
    def setUp(self):
        build = verifier.ROOT / '.build'
        build.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='snapshot-integrity-', dir=build)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.job = self.root / '.build' / 'job'
        self.evidence = self.job / 'evidence'
        self.snapshot = self.job / 'snapshot'
        self.evidence.mkdir(parents=True)
        self.snapshot.mkdir()
        for name, text in [('app.py', 'canonical fixture\n'),
                           ('templates/index.html', '<p>local resource</p>\n')]:
            for base in (self.root, self.snapshot):
                path = base / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding='utf-8')
        self.root_patch = patch.object(verifier, 'ROOT', self.root)
        self.apps_patch = patch.object(verifier, 'APP_FILES', ['app.py'])
        self.dependencies_patch = patch.object(verifier, 'dependencies', return_value={})
        for replacement in (self.root_patch, self.apps_patch, self.dependencies_patch):
            replacement.start()
            self.addCleanup(replacement.stop)
        self.baseline = {
            name: verifier.file_record(self.root / name)
            for name in ('app.py', 'templates/index.html')
        }
        verifier.save(self.evidence / 'source-hashes.json', self.baseline)
        verifier.save(self.evidence / 'resource-inputs.json', [
            {'path': 'templates/index.html', **self.baseline['templates/index.html']}])
        verifier.save(self.evidence / 'dependency-state.json', {})
        verifier.save(self.evidence / 'source-verification.json', {'passed': True})

    def analysis(self):
        return {
            'application_modules_executed': False,
            'source_hash_manifest_sha256': verifier.digest(self.evidence / 'source-hashes.json'),
            'inputs': {
                str((self.snapshot / name).resolve()): {**record, 'kind': 'fixture'}
                for name, record in self.baseline.items()
            },
        }

    def test_matching_snapshot_passes(self):
        verifier.assert_unchanged(self.job)

    def test_changed_snapshot_rejected_with_unchanged_canonical_source(self):
        (self.snapshot / 'app.py').write_text('modified fixture\n', encoding='utf-8')
        self.assertEqual(verifier.file_record(self.root / 'app.py'), self.baseline['app.py'])
        with self.assertRaisesRegex(RuntimeError, 'Build snapshot changed'):
            verifier.assert_unchanged(self.job)

    def test_missing_snapshot_file_rejected(self):
        (self.snapshot / 'app.py').unlink()
        with self.assertRaises(RuntimeError):
            verifier.assert_snapshot(self.job)

    def test_unexpected_snapshot_file_rejected(self):
        (self.snapshot / 'unreviewed.py').write_text('extra\n', encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'unexpected or missing files'):
            verifier.assert_snapshot(self.job)

    def test_changed_canonical_source_rejected(self):
        (self.root / 'app.py').write_text('canonical drift\n', encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'Canonical input changed'):
            verifier.assert_unchanged(self.job)

    def test_resource_manifest_must_match_canonical_baseline(self):
        verifier.save(self.evidence / 'resource-inputs.json', [
            {'path': 'templates/index.html', 'bytes': 1, 'sha256': '0' * 64}])
        with self.assertRaisesRegex(RuntimeError, 'Resource manifest differs'):
            verifier.assert_snapshot(self.job)

    def test_snapshot_path_traversal_rejected(self):
        verifier.save(self.evidence / 'resource-inputs.json', [
            {'path': '../outside.py', 'bytes': 1, 'sha256': '0' * 64}])
        with self.assertRaisesRegex(RuntimeError, 'Invalid snapshot input path'):
            verifier.assert_snapshot(self.job)

    def test_freeze_stops_drift_before_starting_pyinstaller(self):
        (self.snapshot / 'app.py').write_text('modified fixture\n', encoding='utf-8')
        with patch.object(verifier.subprocess, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'Build snapshot changed'):
                verifier.freeze(self.job)
            run.assert_not_called()

    def test_matching_analysis_inputs_pass(self):
        verifier.assert_analysis_inputs(self.job, self.analysis())

    def test_analysis_manifest_identity_must_match(self):
        analysis = self.analysis()
        analysis['source_hash_manifest_sha256'] = '0' * 64
        with self.assertRaisesRegex(RuntimeError, 'Analysis baseline'):
            verifier.assert_analysis_inputs(self.job, analysis)

    def test_analysis_input_hash_must_match_canonical_baseline(self):
        analysis = self.analysis()
        analysis['inputs'][str((self.snapshot / 'app.py').resolve())]['sha256'] = '0' * 64
        with self.assertRaisesRegex(RuntimeError, 'differs from canonical baseline'):
            verifier.assert_analysis_inputs(self.job, analysis)

    def test_required_analysis_input_cannot_be_omitted(self):
        analysis = self.analysis()
        del analysis['inputs'][str((self.snapshot / 'app.py').resolve())]
        with self.assertRaisesRegex(RuntimeError, 'missing from Analysis'):
            verifier.assert_analysis_inputs(self.job, analysis)

    def test_unknown_snapshot_analysis_input_rejected(self):
        analysis = self.analysis()
        analysis['inputs'][str(self.snapshot / 'unreviewed.py')] = {
            'bytes': 1, 'sha256': '0' * 64, 'kind': 'fixture'}
        with self.assertRaisesRegex(RuntimeError, 'Unreviewed snapshot input'):
            verifier.assert_analysis_inputs(self.job, analysis)

    def test_application_execution_during_analysis_rejected(self):
        analysis = self.analysis()
        analysis['application_modules_executed'] = True
        with self.assertRaisesRegex(RuntimeError, 'Application modules executed'):
            verifier.assert_analysis_inputs(self.job, analysis)

    def test_verify_writes_waiver_and_unverified_limits_to_bundle_evidence(self):
        bundle = self.job / 'release' / 'EduBrain'
        for relative in ('data', '_internal/licenses/python', '_internal/templates'):
            (bundle / relative).mkdir(parents=True)
        for relative in ('README.txt', 'LICENSE.txt', '_internal/licenses/python/LICENSE.txt'):
            (bundle / relative).write_text('Synthetic fixture only.\n', encoding='utf-8')
        verifier.shutil.copy2(self.snapshot / 'templates/index.html',
                              bundle / '_internal/templates/index.html')
        # Minimal PE headers exercise inventory checks; these files must never execute.
        for name, subsystem in (('EduBrain.exe', 2), ('EduBrain-console.exe', 3)):
            binary = bytearray(160)
            binary[:2] = b'MZ'
            struct.pack_into('<I', binary, 0x3c, 64)
            binary[64:68] = b'PE\0\0'
            struct.pack_into('<H', binary, 68, 0x8664)
            struct.pack_into('<H', binary, 156, subsystem)
            (bundle / name).write_bytes(binary)
        verifier.save(self.evidence / 'analysis-inputs.json', self.analysis())
        empty_path = self.job / 'empty executable path'
        empty_path.mkdir()
        (self.job / 'unrelated working directory').mkdir()
        registry = MagicMock()
        registry.QueryValueEx.side_effect = lambda key, name: (
            {'DisplayVersion': 'synthetic', 'CurrentBuild': '0', 'UBR': 0,
             'EditionId': 'Synthetic'}[name], 0)
        with (
            patch.dict(sys.modules, {'winreg': registry}),
            patch.object(verifier, 'clean_environment', return_value={'PATH': str(empty_path)}),
            patch.object(verifier, 'self_test', return_value={
                'exit_code': 0, 'report': {'passed': True}, 'synthetic_fixture': True,
            }) as self_test,
            patch.object(verifier.subprocess, 'run', side_effect=AssertionError(
                'Synthetic bundle verification must not launch a process')) as run,
        ):
            verifier.verify(self.job)
            run.assert_not_called()
        moved = self.job / 'USB \u4e2d\u6587 \u8def\u5f84' / '\u79fb\u52a8\u540e\u7684 EduBrain Portable'
        self.assertEqual(self_test.call_count, 2)
        self_test.assert_has_calls([
            call(moved / 'EduBrain.exe', None, self.job, 'gui-self-test',
                 frozen=True, windowed=True),
            call(moved / 'EduBrain-console.exe', None, self.job, 'console-self-test',
                 frozen=True, windowed=False),
        ])
        # Assert the persisted writer output, not just the detached status helper.
        evidence = verifier.load(self.evidence / 'bundle-verification.json')
        self.assertIs(evidence['passed'], True)
        self.assertIs(evidence['zip_crc_passed'], True)
        self.assertEqual(evidence['source_hashes_sha256'],
                         verifier.digest(self.evidence / 'source-hashes.json'))
        status = evidence['release_status']
        windows = status['windows_10_x64']
        self.assertIs(windows['physically_tested'], False)
        self.assertIs(windows['user_waived'], True)
        self.assertIs(windows['blocking'], False)
        self.assertIn('Not physically tested', windows['note'])
        self.assertIn('user-waived 2026-09-08', windows['note'])
        self.assertIn('non-blocking', windows['note'])
        self.assertIn(
            'Windows 10 x64 (not physically tested; user-waived 2026-09-08; non-blocking)',
            evidence['unverified'])
        for name, description in (
            ('physical_usb', 'A physical USB filesystem'),
            ('real_provider_accounts', 'Real provider credentials/accounts/billing'),
        ):
            with self.subTest(release_status=name):
                self.assertIs(status[name]['physically_tested'], False)
                self.assertIs(status[name]['user_waived'], False)
                self.assertIn('Explicitly unverified', status[name]['note'])
                self.assertIn('not waived', status[name]['note'])
                self.assertIn(description, evidence['unverified'])


class ReleaseStatusMetadataTests(unittest.TestCase):
    def test_windows_10_is_user_waived_and_non_blocking(self):
        status = verifier.release_status()['windows_10_x64']
        self.assertFalse(status['physically_tested'])
        self.assertTrue(status['user_waived'])
        self.assertFalse(status['blocking'])
        self.assertIn('user-waived 2026-09-08', status['note'])
        self.assertIn('non-blocking', status['note'])

    def test_physical_usb_stays_explicitly_unverified_and_unwaived(self):
        status = verifier.release_status()['physical_usb']
        self.assertFalse(status['physically_tested'])
        self.assertFalse(status['user_waived'])
        self.assertIn('Explicitly unverified', status['note'])
        self.assertIn('not waived', status['note'])

    def test_real_provider_accounts_stay_explicitly_unverified_and_unwaived(self):
        status = verifier.release_status()['real_provider_accounts']
        self.assertFalse(status['physically_tested'])
        self.assertFalse(status['user_waived'])
        self.assertIn('Explicitly unverified', status['note'])
        self.assertIn('not waived', status['note'])

    def test_generated_evidence_fields_align_with_waiver(self):
        evidence = verifier.release_evidence_status()
        self.assertIn('unverified', evidence)
        self.assertIn('release_status', evidence)
        self.assertEqual(
            evidence['unverified'][0],
            'Windows 10 x64 (not physically tested; user-waived 2026-09-08; non-blocking)')
        self.assertIn('A physical USB filesystem', evidence['unverified'])
        self.assertIn('Real provider credentials/accounts/billing', evidence['unverified'])
        self.assertFalse(evidence['release_status']['windows_10_x64']['blocking'])
        self.assertTrue(evidence['release_status']['windows_10_x64']['user_waived'])
        self.assertFalse(evidence['release_status']['physical_usb']['user_waived'])
        self.assertFalse(evidence['release_status']['real_provider_accounts']['user_waived'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
