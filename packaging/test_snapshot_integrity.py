"""Synthetic regression tests for the reviewed-source packaging boundary."""

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


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


if __name__ == '__main__':
    unittest.main(verbosity=2)
