#!/usr/bin/env python3
"""Render real QML states without installing the widget or changing user settings."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", nargs="?", default="/tmp/foamy-train-previews")
    parser.add_argument("--interactions", action="store_true", help="Run keyboard and live Entur station-search checks in a temporary Wayland window")
    parser.add_argument("--bar", action="store_true", help="Render bar status examples")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    plugin = Path(__file__).resolve().parents[1]
    shell = Path(os.environ.get("OMARCHY_SHELL_PATH", "/usr/share/omarchy/shell"))
    if not (shell / "Commons").is_dir():
        raise SystemExit("Omarchy Quattro is required; set OMARCHY_SHELL_PATH to its shell directory.")
    with tempfile.TemporaryDirectory(prefix="foamy-train-preview-") as temporary:
        base = Path(temporary)
        root = base / "shell" if args.interactions else base
        root.mkdir(exist_ok=True)
        for component in ("Commons", "Ui"):
            (root / component).symlink_to(shell / component, target_is_directory=True)
        (root / "plugin").symlink_to(plugin, target_is_directory=True)
        shutil.copyfile(plugin / ("tests/Interactions.qml" if args.interactions else "tests/BarPreview.qml" if args.bar else "tests/Preview.qml"), root / "shell.qml")
        (root / "runtime").mkdir(mode=0o700)
        env = dict(os.environ, TRAIN_PREVIEW_DIR=str(output), QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software", QT_QPA_PLATFORMTHEME="")
        if args.interactions:
            env["QT_QPA_PLATFORM"] = "wayland"
            # Route CLI writes to this test instance, never the user's running shell.
            env["OMARCHY_PATH"] = str(base)
        else:
            env.pop("WAYLAND_DISPLAY", None)
        for variable, directory in (("XDG_CONFIG_HOME", "config"), ("XDG_STATE_HOME", "state"), ("XDG_CACHE_HOME", "cache"), ("XDG_RUNTIME_DIR", "runtime")):
            if variable != "XDG_RUNTIME_DIR" or not args.interactions:
                env[variable] = str(root / directory)
        (Path(env["XDG_CONFIG_HOME"]) / "omarchy").mkdir(parents=True, exist_ok=True)
        if args.interactions:
            (Path(env["XDG_CONFIG_HOME"]) / "omarchy/shell.json").write_text("{}\n")
        result = subprocess.run(["qs", "-p", str(root), "--no-color"], env=env, capture_output=True, text=True, timeout=55)
        log = result.stdout + result.stderr
        (output / "render.log").write_text(log)
        success = "INTERACTION COMPLETE" if args.interactions else "PREVIEW COMPLETE"
        failures = ("SAVE FAILED", "polish() loop", "Failed to load configuration", "ReferenceError", "TypeError", "INTERACTION FAILED")
        if result.returncode or success not in log or any(failure in log for failure in failures):
            raise SystemExit(log)
        if args.interactions:
            saved = json.loads((Path(env["XDG_CONFIG_HOME"]) / "omarchy/shell.json").read_text())
            route = saved["bar"]["layout"]["right"][0]["route"]
            assert route["from"]["id"] != route["to"]["id"], route
            assert all(station["id"].startswith("NSR:StopPlace:") and station["name"] for station in route.values()), route
            assert not (Path(env["XDG_CONFIG_HOME"]) / "foamy.train").exists()
            assert not (Path(env["XDG_STATE_HOME"]) / "foamy.train").exists()
        print(f"{'Interaction checks passed' if args.interactions else 'Rendered bar states' if args.bar else 'Rendered departure and settings states'}: {output}")


if __name__ == "__main__":
    main()
