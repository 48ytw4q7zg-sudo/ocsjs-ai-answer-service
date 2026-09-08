"""Explicit PyInstaller entry; supports a bounded, synthetic offline self-test."""

import argparse
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description="EduBrain Windows portable application")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--self-test-output", type=Path)
    arguments = parser.parse_args()
    if arguments.self_test:
        from portable_selftest import run
        report = run()
        content = json.dumps(report, ensure_ascii=False, indent=2)
        if arguments.self_test_output:
            from portable_settings import write_json_atomic
            write_json_atomic(arguments.self_test_output.resolve(), report)
        if sys.stdout is not None:
            print(content)
        return 0 if report["passed"] else 1
    from portable_app import main as launch
    try:
        launch()
    except Exception as exc:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("EduBrain 启动失败", "程序无法启动（" + type(exc).__name__ + "）。\n请将整个文件夹解压到可写位置，并保留 _internal。", parent=root)
        root.destroy()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
