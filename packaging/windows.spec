# PyInstaller analyzes a prepared allowlist snapshot, never the host application.
import hashlib
import importlib.metadata
import json
import os
import runpy
from pathlib import Path
import sys

ROOT = Path(SPECPATH).parent.resolve()
BUILD = (ROOT / '.build').resolve()
SOURCE = Path(os.environ['EDUBRAIN_BUILD_SNAPSHOT']).resolve()
EVIDENCE = Path(os.environ['EDUBRAIN_BUILD_EVIDENCE']).resolve()
RUNTIME_HOOK = Path(os.environ['EDUBRAIN_BUILD_HOOK']).resolve()
for path in (SOURCE, EVIDENCE, RUNTIME_HOOK):
    if not path.is_relative_to(BUILD) or path == BUILD:
        raise RuntimeError('Build inputs must be inside this project .build')

APP_MODULES = [
    'app', 'config', 'ccswitch', 'logger', 'utils', 'provider_clients',
    'portable_entry', 'portable_app', 'portable_controller', 'portable_selftest',
    'portable_paths', 'portable_settings',
]
blocked_code = {str((root / (name + '.py')).resolve()).casefold()
                for root in (ROOT, SOURCE) for name in APP_MODULES}


def prevent_application_execution(event, arguments):
    if event == 'exec':
        filename = getattr(arguments[0], 'co_filename', '')
        if filename and str(Path(filename).resolve()).casefold() in blocked_code:
            raise RuntimeError('Application execution is forbidden during bundle analysis')


sys.addaudithook(prevent_application_execution)
resource_manifest = json.loads((EVIDENCE / 'resource-inputs.json').read_text(encoding='utf-8'))
datas = []
for record in resource_manifest:
    relative = Path(record['path'])
    path = (SOURCE / relative).resolve()
    if not path.is_relative_to(SOURCE) or not path.is_file():
        raise RuntimeError('Invalid prepared resource: ' + record['path'])
    datas.append((str(path), relative.parent.as_posix()))

python_license = Path(sys.base_prefix) / 'LICENSE.txt'
if not python_license.is_file():
    raise RuntimeError('The build Python installation must include LICENSE.txt')
datas.append((str(python_license), 'licenses/python'))

# Preserve installed library metadata/entry points and original license files.
# direct_url.json, RECORD, installer state and the build tool packages are omitted.
build_only = {'pip', 'setuptools', 'pyinstaller', 'pyinstaller-hooks-contrib',
              'altgraph', 'pefile', 'pywin32-ctypes', 'gunicorn'}
for distribution in importlib.metadata.distributions():
    name = distribution.metadata['Name'].lower().replace('_', '-')
    if name in build_only:
        continue
    for item in distribution.files or ():
        relative = Path(str(item))
        if not relative.parts or not relative.parts[0].endswith('.dist-info'):
            continue
        base = relative.name.lower()
        if base in {'metadata', 'wheel', 'entry_points.txt', 'top_level.txt'} or any(
                marker in base for marker in ('license', 'copying', 'notice')):
            path = Path(distribution.locate_file(item)).resolve()
            if path.is_file():
                datas.append((str(path), relative.parent.as_posix()))

integrity = runpy.run_path(str(ROOT / 'packaging' / 'verify_portable.py'))
integrity['assert_unchanged'](EVIDENCE.parent)
analysis_baseline_sha256 = integrity['digest'](EVIDENCE / 'source-hashes.json')

a = Analysis(
    [str(SOURCE / 'portable_entry.py')],
    pathex=[str(SOURCE)],
    binaries=[],
    datas=datas,
    hiddenimports=APP_MODULES + [
        '_tkinter', 'tkinter', 'tkinter.ttk', 'tkinter.messagebox', 'tkinter.simpledialog',
        'waitress', 'cryptography', 'cryptography.hazmat.bindings._rust',
        'anthropic', 'httpx', 'certifi', 'flask', 'flask_cors', 'markdown',
        'markdown.extensions.fenced_code', 'markdown.extensions.tables',
        'markdown.extensions.toc', 'markdown.extensions.codehilite',
    ],
    hookspath=[], hooksconfig={}, runtime_hooks=[str(RUNTIME_HOOK)],
    excludes=['gunicorn', 'pytest', 'unittest', 'test', 'tests', 'pip', 'PyInstaller'],
    noarchive=False, optimize=0,
)
if any(name in sys.modules for name in APP_MODULES):
    raise RuntimeError('An application module was imported by the build process')

integrity['assert_unchanged'](EVIDENCE.parent)
integrity['require'](
    integrity['digest'](EVIDENCE / 'source-hashes.json') == analysis_baseline_sha256,
    'Canonical source manifest changed during Analysis',
)
origins = {}
for name, filename, kind in list(a.scripts) + list(a.pure) + list(a.binaries) + list(a.datas):
    if filename and Path(filename).is_file():
        path = Path(filename).resolve()
        with path.open('rb') as stream:
            sha256 = hashlib.file_digest(stream, 'sha256').hexdigest()
        origins[str(path)] = {'bytes': path.stat().st_size, 'sha256': sha256, 'kind': kind}
analysis_evidence = {
    'application_modules_executed': False,
    'source_hash_manifest_sha256': analysis_baseline_sha256,
    'inputs': origins,
}
integrity['assert_analysis_inputs'](EVIDENCE.parent, analysis_evidence)
(EVIDENCE / 'analysis-inputs.json').write_text(
    json.dumps(analysis_evidence, indent=2), encoding='utf-8')

pyz = PYZ(a.pure)
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name='EduBrain', debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False,
          disable_windowed_traceback=False, uac_admin=False, contents_directory='_internal')
console = EXE(pyz, a.scripts, [], exclude_binaries=True, name='EduBrain-console', debug=False,
              bootloader_ignore_signals=False, strip=False, upx=False, console=True,
              uac_admin=False, contents_directory='_internal')
COLLECT(gui, console, a.binaries, a.datas, strip=False, upx=False, name='EduBrain')
