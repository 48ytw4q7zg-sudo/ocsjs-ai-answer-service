"""Run the Windows batch entry against a synthetic, credential-free application."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import venv


@unittest.skipUnless(sys.platform == "win32", "Windows batch entry")
class SourceBatchLauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parent
        build_root = root / ".build"
        build_root.mkdir(exist_ok=True)
        if not build_root.resolve().is_relative_to(root):
            raise RuntimeError("Test workspace must remain inside the project")
        cls.workspace = tempfile.TemporaryDirectory(prefix="batch-launch-test-", dir=build_root)
        cls.addClassCleanup(cls.workspace.cleanup)
        cls.project = Path(cls.workspace.name) / "source space \u4e2d\u6587 & launch"
        cls.fallback_project = Path(cls.workspace.name) / "source fallback"
        cls.unrelated = Path(cls.workspace.name) / "unrelated cwd"
        cls.unrelated.mkdir()
        for project in (cls.project, cls.fallback_project):
            project.mkdir()
            shutil.copy2(root / "start.bat", project / "start.bat")
            (project / "source_launcher.py").write_text(
                "import json, os, sys\n"
                "print('LAUNCH_PROBE:' + json.dumps({'executable':sys.executable, "
                "'cwd':os.getcwd(), 'args':sys.argv[1:]}), flush=True)\n"
                "raise SystemExit(int(os.environ['SOURCE_LAUNCHER_TEST_EXIT']))\n",
                encoding="utf-8",
            )
        cls.local_venv = cls.project / ".build" / "venv"
        venv.EnvBuilder(with_pip=False, symlinks=False).create(cls.local_venv)
        cls.local_python = cls.local_venv / "Scripts" / "python.exe"
        cls.base_python = Path(getattr(sys, "_base_executable", sys.executable)).resolve()
        cls.system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))

    def run_batch(self, project, exit_code, *, include_global=True):
        environment = {
            name: os.environ[name] for name in ("SystemRoot", "WINDIR", "COMSPEC", "PATHEXT")
            if name in os.environ
        }
        search = [str(self.system_root / "System32")]
        if include_global:
            search.append(str(self.base_python.parent))
        environment.update({
            "PATH": os.pathsep.join(search),
            "TEMP": self.workspace.name,
            "TMP": self.workspace.name,
            "USERPROFILE": self.workspace.name,
            "HOME": self.workspace.name,
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "SOURCE_LAUNCHER_TEST_EXIT": str(exit_code),
            "SOURCE_LAUNCHER_TEST_ENTRY": str(project / "start.bat"),
        })
        # CMD uses its own quote rules, not subprocess.list2cmdline's CRT rules.
        command = ('"' + str(self.system_root / "System32" / "cmd.exe")
                   + '" /d /s /c ""%SOURCE_LAUNCHER_TEST_ENTRY%" --no-browser --timeout 0.25"')
        return subprocess.run(
            command,
            cwd=self.unrelated, env=environment, input="\n", text=True,
            encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=15, creationflags=subprocess.CREATE_NO_WINDOW,
        )

    def probe_record(self, process):
        records = [line[len("LAUNCH_PROBE:"):] for line in process.stdout.splitlines() if line.startswith("LAUNCH_PROBE:")]
        self.assertEqual(len(records), 1, process.stdout + process.stderr)
        return json.loads(records[0])

    def test_project_interpreter_wins_and_arguments_survive_complex_path(self):
        process = self.run_batch(self.project, 0)
        record = self.probe_record(process)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(Path(record["executable"]).resolve(), self.local_python.resolve())
        self.assertEqual(Path(record["cwd"]).resolve(), self.project.resolve())
        self.assertEqual(record["args"], ["--no-browser", "--timeout", "0.25"])

    def test_application_failure_exit_is_preserved(self):
        process = self.run_batch(self.project, 23)
        self.probe_record(process)
        self.assertEqual(process.returncode, 23, process.stdout + process.stderr)

    def test_global_python_fallback_can_launch_the_same_source_entry(self):
        process = self.run_batch(self.fallback_project, 0)
        record = self.probe_record(process)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(Path(record["executable"]).resolve(), self.base_python)
        self.assertEqual(Path(record["cwd"]).resolve(), self.fallback_project.resolve())

    def test_no_interpreter_does_not_report_a_started_application(self):
        process = self.run_batch(self.fallback_project, 0, include_global=False)
        self.assertNotEqual(process.returncode, 0)
        self.assertNotIn("LAUNCH_PROBE:", process.stdout)
        self.assertIn("Python 3.10+", process.stdout)


if __name__ == "__main__":
    unittest.main()
