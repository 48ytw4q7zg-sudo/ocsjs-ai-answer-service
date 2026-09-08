"""Prepare, freeze and audit the Windows release without importing host app config."""

from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import struct
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
APP_FILES = [name + '.py' for name in (
    'portable_entry', 'portable_app', 'portable_controller', 'portable_selftest',
    'portable_paths', 'portable_settings', 'app', 'config', 'ccswitch', 'logger',
    'utils', 'provider_clients')]
PACKAGING_FILES = ['build_windows.ps1', 'packaging/windows.spec',
                   'packaging/verify_portable.py', 'packaging/build-requirements.txt',
                   'packaging/PORTABLE_README.txt', 'packaging/BUILD_WINDOWS.md',
                   'packaging/test_snapshot_integrity.py']
TOOLS = {'pyinstaller': '6.22.2', 'pyinstaller-hooks-contrib': '2026.7',
         'altgraph': '0.17.5', 'packaging': '26.3', 'pefile': '2024.8.26',
         'pywin32-ctypes': '0.2.3', 'setuptools': '84.0.0'}
REQUIRED_CHECKS = {
    'host_environment_isolation', 'loopback_binding', 'unconfigured_http_responds',
    'page_/', 'page_/dashboard', 'page_/docs', 'bundled_ca_certificates',
    'provider_openai_responses', 'provider_openai_chat', 'provider_anthropic',
    'encrypted_profile_roundtrip', 'no_plaintext_credentials',
    'profile_preferences_roundtrip', 'wrong_password_rejected',
    'native_tk_interface', 'tk_runtime', 'http_thread_stopped',
}

# This packaging hook only observes explicitly requested self-tests. It does not
# alter app/config/provider modules or ordinary launch behavior.
RUNTIME_AUDIT = r'''import atexit
import ctypes
import json
from pathlib import Path
import sys

if '--self-test' in sys.argv and '--self-test-output' in sys.argv:
    _output = Path(sys.argv[sys.argv.index('--self-test-output') + 1])
    if not _output.is_absolute() or _output.suffix.lower() != '.json':
        raise RuntimeError('Packaged self-test audit requires an absolute JSON output path')
    _report = {'frozen': bool(getattr(sys, 'frozen', False)),
               'stdout_is_none': sys.stdout is None, 'stderr_is_none': sys.stderr is None,
               'pointer_bits': ctypes.sizeof(ctypes.c_void_p) * 8,
               'executable': sys.executable, 'bundle_root': str(getattr(sys, '_MEIPASS', '')),
               'loopback_connections': 0, 'external_process_attempts': 0}

    def _selftest_boundary(event, args):
        if event == 'socket.connect':
            address = args[1]
            if not isinstance(address, tuple) or address[0] not in ('127.0.0.1', '::1', 'localhost'):
                raise RuntimeError('Self-test attempted a non-loopback connection')
            _report['loopback_connections'] += 1
        if event in ('subprocess.Popen', 'os.system', 'os.startfile', 'os.startfile/2'):
            _report['external_process_attempts'] += 1
            raise RuntimeError('Self-test attempted to launch an external program')

    sys.addaudithook(_selftest_boundary)

    def _finish_audit():
        try:
            _report['stdout_is_none_at_exit'] = sys.stdout is None
            _report['modules'] = {}
            for name in ('app', 'config', 'portable_app', 'portable_paths', 'portable_settings',
                         'portable_controller', 'provider_clients', 'waitress', 'anthropic',
                         'httpx', 'certifi', 'cryptography.hazmat.bindings._rust', '_tkinter', '_ssl'):
                module = sys.modules.get(name)
                _report['modules'][name] = str(getattr(module, '__file__', ''))
            paths = sys.modules.get('portable_paths')
            _report['application_root'] = str(paths.application_root()) if paths else ''
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
            kernel.GetModuleHandleW.restype = ctypes.c_void_p
            kernel.GetModuleFileNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint]
            kernel.GetModuleFileNameW.restype = ctypes.c_uint
            _report['native_dependencies'] = {}
            names = ('python%d%d.dll' % sys.version_info[:2], 'tcl86t.dll', 'tk86t.dll')
            for name in names:
                handle = kernel.GetModuleHandleW(name)
                buffer = ctypes.create_unicode_buffer(32768)
                if handle and kernel.GetModuleFileNameW(handle, buffer, len(buffer)):
                    _report['native_dependencies'][name] = buffer.value
            tk = sys.modules.get('_tkinter')
            _report['tcl_version'] = getattr(tk, 'TCL_VERSION', None)
            _report['tk_version'] = getattr(tk, 'TK_VERSION', None)
        except Exception as exc:
            _report['audit_error'] = type(exc).__name__ + ': ' + str(exc)
        _output.with_suffix('.runtime.json').write_text(
            json.dumps(_report, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')

    atexit.register(_finish_audit)
'''


def require(value, message):
    if not value:
        raise RuntimeError(message)


def project_path(relative):
    relative = PurePosixPath(str(relative).replace('\\', '/'))
    require(not relative.is_absolute() and '..' not in relative.parts, 'Unsafe project relative path')
    path = ROOT.joinpath(*relative.parts)
    for parent in (path, *path.parents):
        if parent == ROOT:
            break
        require(not parent.is_symlink() and not parent.is_junction(), 'Reparse point rejected: ' + str(parent))
    resolved = path.resolve()
    require(resolved.is_relative_to(ROOT), 'Path escaped the project')
    return resolved


def owned(path):
    path = Path(path).absolute()
    roots = (ROOT / '.build', ROOT / 'dist')
    require(any(path != base and path.is_relative_to(base) for base in roots), 'Not a task-owned build path: ' + str(path))
    for parent in (path, *path.parents):
        if parent == ROOT:
            break
        require(not parent.is_symlink() and not parent.is_junction(), 'Reparse point rejected: ' + str(parent))
    resolved = path.resolve()
    require(any(resolved != base.resolve() and resolved.is_relative_to(base.resolve()) for base in roots), 'Resolved build path escaped')
    return resolved


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def file_record(path):
    path = Path(path)
    require(path.is_file(), 'Required file not present: ' + str(path))
    return {'bytes': path.stat().st_size, 'sha256': digest(path)}


def save(path, value):
    path = owned(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def clean_environment(job):
    env = {k: v for k, v in os.environ.items() if k.upper() in {'SYSTEMROOT', 'WINDIR', 'SYSTEMDRIVE', 'COMSPEC'}}
    env['PATH'] = str(Path(os.environ['SystemRoot']) / 'System32')
    for name in ('TEMP', 'TMP', 'USERPROFILE', 'HOME', 'APPDATA', 'LOCALAPPDATA'):
        target = owned(job / 'isolated' / name.lower())
        target.mkdir(parents=True, exist_ok=True)
        env[name] = str(target)
    env['TMP'] = env['TEMP']
    env.update(PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1', PYTHON_DOTENV_DISABLED='1',
               PYINSTALLER_CONFIG_DIR=str(owned(job / 'pyinstaller-cache')))
    return env


def dependencies():
    result = {}
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata['Name'].lower().replace('_', '-')
        result[name] = {'version': distribution.version,
                        'metadata_sha256': hashlib.sha256((distribution.read_text('METADATA') or '').encode('utf-8')).hexdigest(),
                        'record_sha256': hashlib.sha256((distribution.read_text('RECORD') or '').encode('utf-8')).hexdigest()}
    for name, expected in TOOLS.items():
        require(name in result and result[name]['version'] == expected, 'Build dependency pin mismatch: ' + name + '==' + expected)
    for name in ('flask', 'flask-cors', 'anthropic', 'cryptography', 'httpx', 'certifi', 'waitress', 'markdown', 'python-dotenv'):
        require(name in result, 'Runtime dependency missing from the existing venv: ' + name)
    return result


class ResourceTags(HTMLParser):
    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == 'script' and attrs.get('src'):
            require(not re.match(r'^(?:https?:)?//', attrs['src']), 'Remote script dependency: ' + attrs['src'])
        if tag == 'link' and attrs.get('rel') == 'stylesheet':
            require(not re.match(r'^(?:https?:)?//', attrs.get('href', '')), 'Remote stylesheet dependency')


def resources():
    manifest = load(project_path('packaging/vendor-assets.json'))
    require(manifest.get('schema_version') == 1, 'Unsupported or incomplete vendor manifest')
    assets = [item for package in manifest['packages'] for item in package['files']]
    paths = set()
    for asset in assets:
        relative = asset['path']
        require(relative.startswith('static/vendor/') and relative not in paths, 'Invalid or duplicate asset path')
        paths.add(relative)
        require(file_record(project_path(relative)) == {'bytes': asset['bytes'], 'sha256': asset['sha256']}, 'Vendor asset missing or changed: ' + relative)
    actual = {p.relative_to(ROOT).as_posix() for p in (ROOT / 'static' / 'vendor').rglob('*') if p.is_file()}
    require(actual == paths, 'Vendor directory differs from its explicit manifest')
    templates = ['templates/index.html', 'templates/dashboard.html']
    for name in templates:
        text = project_path(name).read_text(encoding='utf-8')
        ResourceTags().feed(text)
        for reference in manifest['template_references']:
            if reference['template'] == name:
                require(reference['local_url'] in text and reference['original_url'] not in text, 'Template not yet switched to local assets: ' + name)
    names = templates + ['static/style.css', 'README.md', 'api_docs.md', 'THIRD_PARTY_NOTICES.md', 'packaging/vendor-assets.json'] + sorted(paths)
    return [{'path': name, **file_record(project_path(name))} for name in names]


def canonical_hashes(resource_records):
    names = sorted(set(APP_FILES + PACKAGING_FILES + ['requirements.txt', 'LICENSE'] + [r['path'] for r in resource_records]))
    return {name: file_record(project_path(name)) for name in names}


def assert_snapshot(job):
    """Bind the complete build snapshot to the reviewed canonical inputs."""
    job = owned(job)
    snapshot = owned(job / 'snapshot')
    require(snapshot.is_dir(), 'Build snapshot is missing')
    evidence = job / 'evidence'
    baseline = load(evidence / 'source-hashes.json')
    resource_records = load(evidence / 'resource-inputs.json')
    names = set(APP_FILES)
    for record in resource_records:
        name = record['path']
        relative = PurePosixPath(name)
        require(name and '\\' not in name and not relative.is_absolute()
                and '..' not in relative.parts and relative.as_posix() == name,
                'Invalid snapshot input path: ' + name)
        require(name in baseline and baseline[name] == {
            'bytes': record['bytes'], 'sha256': record['sha256']},
            'Resource manifest differs from canonical baseline: ' + name)
        names.add(name)
    expected = {}
    for name in sorted(names):
        require(name in baseline, 'Snapshot input has no canonical baseline: ' + name)
        path = owned(snapshot / name)
        require(path.is_relative_to(snapshot), 'Snapshot input escapes snapshot: ' + name)
        require(file_record(path) == baseline[name],
                'Build snapshot changed; candidate is held: ' + name)
        expected[str(path)] = baseline[name]
    actual = set()
    for path in snapshot.rglob('*'):
        require(not path.is_symlink() and not path.is_junction(),
                'Linked path in build snapshot: ' + str(path))
        if path.is_file():
            actual.add(str(owned(path)))
        else:
            require(path.is_dir(), 'Unsupported path in build snapshot: ' + str(path))
    require(actual == set(expected), 'Build snapshot contains unexpected or missing files')
    return expected


def assert_analysis_inputs(job, analysis=None):
    """Require every snapshot Analysis input to retain its canonical hash."""
    job = owned(job)
    evidence = job / 'evidence'
    if analysis is None:
        analysis = load(evidence / 'analysis-inputs.json')
    require(analysis.get('application_modules_executed') is False,
            'Application modules executed during Analysis')
    require(analysis.get('source_hash_manifest_sha256') == digest(evidence / 'source-hashes.json'),
            'Analysis baseline does not match the reviewed source manifest')
    expected = assert_snapshot(job)
    snapshot = owned(job / 'snapshot')
    seen = set()
    for name, record in analysis['inputs'].items():
        path = Path(name).resolve()
        if path.is_relative_to(snapshot):
            key = str(path)
            require(key in expected, 'Unreviewed snapshot input in Analysis: ' + name)
            require({'bytes': record['bytes'], 'sha256': record['sha256']} == expected[key],
                    'Analysis snapshot input differs from canonical baseline: ' + name)
            seen.add(key)
    require(seen == set(expected), 'Required snapshot inputs are missing from Analysis')


def assert_unchanged(job):
    assert_snapshot(job)
    evidence = job / 'evidence'
    baseline = load(evidence / 'source-hashes.json')
    for name, record in baseline.items():
        require(file_record(project_path(name)) == record, 'Canonical input changed; candidate is held: ' + name)
    require(dependencies() == load(evidence / 'dependency-state.json'), 'Build dependency state changed')


def self_test(executable, entry, job, label, *, frozen, windowed):
    evidence = job / 'evidence'
    output = owned(evidence / (label + '.json'))
    command = [str(executable)]
    if entry:
        command += ['-B', str(entry)]
    command += ['--self-test', '--self-test-output', str(output)]
    cwd = owned(job / 'unrelated working directory')
    cwd.mkdir(exist_ok=True)
    env = clean_environment(job)
    completed = subprocess.run(command, cwd=cwd, env=env, capture_output=not windowed,
                               close_fds=True, timeout=60,
                               creationflags=subprocess.DETACHED_PROCESS if windowed else subprocess.CREATE_NO_WINDOW)
    if not windowed:
        (evidence / (label + '-process.txt')).write_text(
            (completed.stdout or b'').decode('utf-8', 'replace') + (completed.stderr or b'').decode('utf-8', 'replace'), encoding='utf-8')
    require(output.is_file(), label + ': JSON result missing; exit ' + str(completed.returncode))
    report = load(output)
    require(completed.returncode == 0 and report.get('passed') is True,
            label + ': exit ' + str(completed.returncode) + '; ' + report.get('error_type', '') + ': ' + report.get('error', 'self-test did not pass'))
    require(report.get('frozen') is frozen, label + ': unexpected frozen state')
    require(REQUIRED_CHECKS <= set(report.get('checks', [])), label + ': required self-test coverage is missing')
    audit = load(output.with_suffix('.runtime.json'))
    require(not audit.get('audit_error') and audit['pointer_bits'] == 64, label + ': runtime audit failed')
    require(audit['loopback_connections'] > 0 and audit['external_process_attempts'] == 0, label + ': loopback/no-external-program audit failed')
    if windowed:
        require(audit['stdout_is_none'] and audit['stderr_is_none'] and audit['stdout_is_none_at_exit'], label + ': GUI has standard streams')
    if frozen:
        folder = Path(executable).resolve().parent
        require(Path(audit['application_root']).resolve() == folder, label + ': application root is not executable-relative')
        internal = folder / '_internal'
        require(len(audit['native_dependencies']) == 3, label + ': Python/Tcl/Tk native dependencies were not observed')
        for path in list(audit['native_dependencies'].values()) + list(audit['modules'].values()):
            require(bool(path) and Path(path).resolve().is_relative_to(internal), label + ': dependency resolved outside _internal: ' + path)
    return {'exit_code': completed.returncode, 'report': report, 'runtime': audit}


def prepare(job):
    evidence = owned(job / 'evidence')
    evidence.mkdir(parents=True, exist_ok=True)
    require(sys.platform == 'win32' and struct.calcsize('P') == 8, 'Windows x64 Python is required')
    require(Path(sys.prefix).resolve() != Path(sys.base_prefix).resolve(), 'Use the existing project-local venv')
    owned(sys.executable)
    source_records = resources()
    source_hashes = canonical_hashes(source_records)
    save(evidence / 'resource-inputs.json', source_records)
    save(evidence / 'source-hashes.json', source_hashes)
    save(evidence / 'dependency-state.json', dependencies())
    snapshot = owned(job / 'snapshot')
    snapshot.mkdir(exist_ok=True)
    for name in sorted(set(APP_FILES + [r['path'] for r in source_records])):
        destination = owned(snapshot / name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(project_path(name), destination)
        require(file_record(destination) == source_hashes[name], 'Snapshot changed during copy: ' + name)
    hook = owned(job / 'packaging-runtime-audit.py')
    hook.write_text(RUNTIME_AUDIT, encoding='utf-8')
    launcher = owned(job / 'source-audit-launcher.py')
    launcher.write_text(
        'import runpy, sys\nfrom pathlib import Path\n'
        'root = Path(__file__).resolve().parent\n'
        'sys.path.insert(0, str(root / "snapshot"))\n'
        'runpy.run_path(str(root / "packaging-runtime-audit.py"))\n'
        'runpy.run_path(str(root / "snapshot" / "portable_entry.py"), run_name="__main__")\n', encoding='utf-8')
    check = subprocess.run([sys.executable, '-m', 'pip', '--isolated', 'check'], cwd=job,
                           env=clean_environment(job), capture_output=True, timeout=60)
    (evidence / 'pip-check.txt').write_text(check.stdout.decode('utf-8', 'replace') + check.stderr.decode('utf-8', 'replace'), encoding='utf-8')
    require(check.returncode == 0, 'Existing venv failed pip check')
    result = self_test(Path(sys.executable).with_name('pythonw.exe'), launcher, job,
                       'source-self-test', frozen=False, windowed=True)
    assert_unchanged(job)
    save(evidence / 'source-verification.json', {'passed': True, 'self_test': result,
         'vendor_files': sum(1 for r in source_records if r['path'].startswith('static/vendor/')),
         'source_hash_manifest_sha256': digest(evidence / 'source-hashes.json'),
         'dependency_manifest_sha256': digest(evidence / 'dependency-state.json')})
    print('Source self-test, isolated no-console audit, dependency pins and vendor hashes passed.', flush=True)


def freeze(job):
    evidence = job / 'evidence'
    require(load(evidence / 'source-verification.json')['passed'], 'Source gate has not passed')
    assert_unchanged(job)
    env = clean_environment(job)
    env.update(EDUBRAIN_BUILD_SNAPSHOT=str(job / 'snapshot'), EDUBRAIN_BUILD_EVIDENCE=str(evidence),
               EDUBRAIN_BUILD_HOOK=str(job / 'packaging-runtime-audit.py'))
    release = owned(job / 'release')
    release.mkdir(exist_ok=True)
    command = [sys.executable, '-B', '-m', 'PyInstaller', '--noconfirm', '--distpath', str(release),
               '--workpath', str(job / 'pyinstaller-work'), str(ROOT / 'packaging' / 'windows.spec')]
    print('Freezing approved snapshot; progress is recorded in evidence/pyinstaller-build.txt.', flush=True)
    with (evidence / 'pyinstaller-build.txt').open('w', encoding='utf-8') as stream:
        completed = subprocess.run(command, cwd=job, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=600)
    require(completed.returncode == 0, 'PyInstaller exit ' + str(completed.returncode) + '; see pyinstaller-build.txt')
    bundle = owned(release / 'EduBrain')
    shutil.copy2(ROOT / 'packaging' / 'PORTABLE_README.txt', bundle / 'README.txt')
    shutil.copy2(ROOT / 'LICENSE', bundle / 'LICENSE.txt')
    (bundle / 'data').mkdir(exist_ok=True)
    assert_unchanged(job)
    print('Both EXEs built; starting relocated binary acceptance.', flush=True)


def pe_info(path):
    with Path(path).open('rb') as stream:
        require(stream.read(2) == b'MZ', 'Missing PE signature: ' + str(path))
        stream.seek(0x3c)
        offset = struct.unpack('<I', stream.read(4))[0]
        stream.seek(offset)
        header = stream.read(96)
    require(header[:4] == b'PE\0\0', 'Invalid PE signature')
    require(struct.unpack_from('<H', header, 4)[0] == 0x8664, 'Non-AMD64 payload binary: ' + str(path))
    return {'machine': 'AMD64', 'subsystem': struct.unpack_from('<H', header, 92)[0]}


def inventory(bundle, resource_records):
    require({p.name for p in bundle.iterdir()} == {'EduBrain.exe', 'EduBrain-console.exe', '_internal', 'README.txt', 'LICENSE.txt', 'data'}, 'Unexpected bundle root content')
    require(not any((bundle / 'data').iterdir()), 'Release data folder must be empty')
    records, native = [], []
    for path in sorted(bundle.rglob('*')):
        owned(path)
        if not path.is_file():
            continue
        relative = path.relative_to(bundle).as_posix()
        parts = [x.lower() for x in path.relative_to(bundle).parts]
        require(not any(x in {'logs', 'tests', '__pycache__', '.git', 'node_modules', 'credentials.json', 'profile.json', 'settings.json', 'config.json'} or x.startswith('.env') for x in parts), 'Forbidden release path: ' + relative)
        require(path.suffix.lower() not in {'.log', '.key', '.pfx', '.py', '.pyc', '.ps1', '.bat', '.tgz', '.gz', '.7z'}, 'Unexpected source/archive/private file: ' + relative)
        if path.suffix.lower() == '.pem':
            require(relative == '_internal/certifi/cacert.pem', 'Only the public certifi CA bundle is allowed')
        if path.suffix.lower() == '.zip':
            require(relative == '_internal/base_library.zip', 'Unexpected archive in release')
            with zipfile.ZipFile(path) as archive:
                require(all(name.endswith('.pyc') for name in archive.namelist()), 'Unexpected standard-library archive member')
        if path.suffix.lower() in {'.exe', '.dll', '.pyd'}:
            native.append({'path': relative, **pe_info(path)})
        records.append({'path': relative, **file_record(path)})
    require(pe_info(bundle / 'EduBrain.exe')['subsystem'] == 2, 'EduBrain.exe must be windowed')
    require(pe_info(bundle / 'EduBrain-console.exe')['subsystem'] == 3, 'Diagnostic companion must retain console')
    for item in resource_records:
        require(file_record(bundle / '_internal' / item['path']) == {'bytes': item['bytes'], 'sha256': item['sha256']}, 'Packaged resource mismatch: ' + item['path'])
    require((bundle / '_internal' / 'licenses' / 'python' / 'LICENSE.txt').is_file(), 'Python license missing')
    return {'files': records, 'file_count': len(records), 'total_bytes': sum(r['bytes'] for r in records),
            'native_binaries': native, 'empty_data': True, 'resource_count': len(resource_records)}


def verify(job):
    assert_analysis_inputs(job)
    evidence = job / 'evidence'
    assert_unchanged(job)
    analysis = load(evidence / 'analysis-inputs.json')
    require(analysis['application_modules_executed'] is False, 'Application was executed during analysis')
    for path, value in analysis['inputs'].items():
        require(file_record(path) == {'bytes': value['bytes'], 'sha256': value['sha256']}, 'Analysis dependency changed: ' + path)
        source = Path(path).resolve()
        if source.is_relative_to(ROOT) and not source.is_relative_to(job) and not source.is_relative_to(Path(sys.prefix).resolve()):
            raise RuntimeError('Analysis collected a non-snapshot project file: ' + path)
    release = owned(job / 'release')
    bundle = owned(release / 'EduBrain')
    resource_records = load(evidence / 'resource-inputs.json')
    before = inventory(bundle, resource_records)
    archive_path = owned(release / 'EduBrain-Windows-x64.zip')
    with zipfile.ZipFile(archive_path, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.write(bundle, 'EduBrain/')
        for path in sorted(bundle.rglob('*')):
            archive.write(path, (Path('EduBrain') / path.relative_to(bundle)).as_posix())
    relocation = owned(job / 'USB \u4e2d\u6587 \u8def\u5f84')
    relocation.mkdir()
    with zipfile.ZipFile(archive_path) as archive:
        require(archive.testzip() is None, 'ZIP CRC failure')
        for member in archive.namelist():
            item = PurePosixPath(member)
            require(not item.is_absolute() and '..' not in item.parts and '\\' not in member, 'Unsafe ZIP member')
        archive.extractall(relocation)
    extracted = owned(relocation / 'EduBrain')
    moved = owned(relocation / '\u79fb\u52a8\u540e\u7684 EduBrain Portable')
    extracted.rename(moved)
    require(inventory(moved, resource_records) == before, 'ZIP roundtrip changed the payload')
    env = clean_environment(job)
    for name in ('python', 'python3', 'node', 'docker'):
        require(shutil.which(name, path=env['PATH']) is None, 'Target PATH exposes a development runtime: ' + name)
    gui = self_test(moved / 'EduBrain.exe', None, job, 'gui-self-test', frozen=True, windowed=True)
    console = self_test(moved / 'EduBrain-console.exe', None, job, 'console-self-test', frozen=True, windowed=False)
    require(inventory(bundle, resource_records) == before, 'Binary acceptance changed the clean candidate')
    assert_unchanged(job)
    host = {'system': platform.system(), 'release': platform.release(), 'version': platform.version(),
            'edition': platform.win32_edition(), 'machine': platform.machine(), 'pointer_bits': struct.calcsize('P') * 8}
    import winreg
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Windows NT\CurrentVersion') as key:
        host['display_version'] = winreg.QueryValueEx(key, 'DisplayVersion')[0]
        host['os_build'] = str(winreg.QueryValueEx(key, 'CurrentBuild')[0]) + '.' + str(winreg.QueryValueEx(key, 'UBR')[0])
    result = {'passed': True, 'host': host, 'inventory': before, 'gui': gui, 'console': console,
              'zip': {'name': archive_path.name, **file_record(archive_path)}, 'zip_crc_passed': True,
              'minimal_path': env['PATH'], 'relocated_unicode_space_path': str(moved),
              'unrelated_working_directory': True, 'external_programs_blocked_in_self_test': True,
              'source_hashes_sha256': digest(evidence / 'source-hashes.json'),
              'dependency_state_sha256': digest(evidence / 'dependency-state.json'),
              'analysis_inputs_sha256': digest(evidence / 'analysis-inputs.json'),
              'unverified': ['Windows 10', 'Other Windows 11 builds', 'A clean OS without installed runtimes',
                             'A physical USB filesystem', 'Real provider credentials/accounts/billing']}
    save(evidence / 'bundle-verification.json', result)
    sums = [r['sha256'] + '  EduBrain/' + r['path'] for r in before['files']]
    sums.append(result['zip']['sha256'] + '  ' + archive_path.name)
    (release / 'SHA256SUMS.txt').write_text('\n'.join(sums) + '\n', encoding='utf-8')
    shutil.rmtree(owned(relocation))
    shutil.rmtree(owned(job / 'unrelated working directory'))
    print(json.dumps({'passed': True, 'host': host, 'file_count': before['file_count'], 'bundle_bytes': before['total_bytes'], 'zip': result['zip']}), flush=True)


def record(job, release):
    assert_unchanged(job)
    result = load(job / 'evidence' / 'bundle-verification.json')
    require(result['passed'], 'Binary acceptance has not passed')
    require(file_record(release / result['zip']['name']) == {'bytes': result['zip']['bytes'], 'sha256': result['zip']['sha256']}, 'Published ZIP hash mismatch')
    summary = {'status': 'verified-preparation-pending-parent-review', 'release': str(release),
               'archive': str(release / result['zip']['name']), 'zip': result['zip'],
               'bundle_files': result['inventory']['file_count'], 'bundle_bytes': result['inventory']['total_bytes'],
               'host': result['host'], 'evidence': str(job / 'evidence')}
    save(job / 'evidence' / 'build-result.json', summary)
    print(json.dumps(summary, ensure_ascii=True, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['prepare', 'freeze', 'verify', 'record'])
    parser.add_argument('--job-dir', type=Path, required=True)
    parser.add_argument('--release-dir', type=Path)
    args = parser.parse_args()
    job = owned(args.job_dir)
    (job / 'evidence').mkdir(parents=True, exist_ok=True)
    try:
        if args.phase == 'record':
            require(args.release_dir is not None, '--release-dir is required')
            record(job, owned(args.release_dir))
        else:
            globals()[args.phase](job)
    except Exception as exc:
        failure = {'status': 'blocked', 'phase': args.phase, 'error_type': type(exc).__name__,
                   'error': str(exc), 'evidence': str(job / 'evidence')}
        save(job / 'evidence' / ('failure-' + args.phase + '.json'), failure)
        print(json.dumps(failure, ensure_ascii=True), flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
