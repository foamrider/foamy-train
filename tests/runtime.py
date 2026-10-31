#!/usr/bin/env python3
"""Offscreen runtime checks on both hosts (4.0 installed, 4.5 reference tree):
two bar instances share one TrainService (leader configures it), the 4.5
in-process `lock isLocked` probe pauses polling while locked, the route
reaches the helper on stdin (never argv), popup demand switches the clock
to seconds, settings saves keep the route, and invalid values are refused.

Uses the foamy-kit preview harness (temp HOME/XDG, no Wayland/Hyprland, no
host scripts): FOAMY_KIT=/path/to/foamy-kit (default ~/GitHub/Personal/foamy-kit).
The helper runs in offline mode (no network in the sandbox), so Entur is
never contacted.
  python3 tests/runtime.py [4.0|4.5|both]
"""
import os
import sys
from pathlib import Path

KIT = Path(os.environ.get("FOAMY_KIT", Path.home() / "GitHub/Personal/foamy-kit"))
sys.path.insert(0, str(KIT / "preview"))
import harness  # noqa: E402

PLUGIN = Path(__file__).resolve().parents[1]
LOCK_45 = 'ShellIpc { target: "lock"; function isLocked(): string { return shell.locked ? "true" : "false" } }'

SHELL = r'''
import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import "harness"
import "plugin" as Train
import "plugin/tests/Fixtures.js" as Fixtures

ShellRoot {
  id: shell
  property bool locked: true
  property var route: ({ from: { id: "NSR:StopPlace:59872", name: "Oslo S" }, to: { id: "NSR:StopPlace:62339", name: "Lillestrøm" } })
  property var entry: ({ route: shell.route, refreshSeconds: 300 })
  property int step: 0
  readonly property bool modern: HOST === "4.5"
  function check(ok, what) { if (!ok) console.log("FOAMY FAIL " + what); else console.log("FOAMY OK " + what) }
  MockBar { id: bar; moduleName: "foamy.train" }
  LOCK
  FloatingWindow {
    visible: true; implicitWidth: 300; implicitHeight: 60
    Train.Panel { id: a; bar: bar; moduleName: "foamy.train"; settings: shell.entry; width: 100; height: 32 }
    Train.Panel { id: b; bar: bar; moduleName: "foamy.train"; settings: shell.entry; x: 140; width: 100; height: 32 }
  }
  // A body taller than its viewport: cursor stops must scroll into view.
  FloatingWindow {
    visible: true; implicitWidth: 420; implicitHeight: 300
    Train.TrainBody {
      id: body
      width: 420; height: 300
      report: Fixtures.report("normal")
      nowEpoch: Fixtures.now
      departures: report.departures
      next: report.departures[0]
      route: Fixtures.route
    }
  }
  Timer {
    interval: 400; repeat: true; running: true
    onTriggered: {
      var s = Train.TrainService
      switch (shell.step++) {
      case 0:
        check(s.active && s.configured, "service active and configured by the leader")
        check(s.refreshSeconds === 300 && s.route && s.route.from.name === "Oslo S", "leader pushed its settings")
        check(s.clock.precision === SystemClock.Minutes, "minute clock while every popup is closed")
        s.statusProcess.running = false
        break
      case 1:
        s.refresh(false, false)
        if (modern) {
          check(s.lockInProcess && s.sessionLocked, "4.5 in-process lock probe reports locked")
          check(!s.statusProcess.running, "no Entur request while locked")
          check(s.pollInterval === 10, "locked: only the cheap lock probe ticks (10 s)")
        } else {
          check(!s.lockInProcess, "4.0 has no IpcRegistry; lock probe falls back to omarchy-shell")
        }
        shell.locked = false
        break
      case 2:
        if (s.loading) { shell.step--; break }
        s.refresh(false, false)
        check(!s.sessionLocked, "unlocked session polls again")
        check(s.statusProcess.running || s.lockProbing, "a request starts after unlock")
        break
      case 3:
        if (s.loading || s.lockProbing) { shell.step--; break }
        var argv = s.statusProcess.command.join(" ")
        check(argv.indexOf("--route-stdin") >= 0 && argv.indexOf("NSR:") < 0 && argv.indexOf("Oslo") < 0, "route is not in argv")
        check(s.report.route && s.report.route.to.name === "Lillestrøm", "helper received the route on stdin (" + s.report.status + "/" + s.report.errorCode + ")")
        check(s.report.errorCode === "offline", "sandbox fetch is offline (no network)")
        a.open()
        break
      case 4:
        check(s.demanded && s.clock.precision === SystemClock.Seconds, "open popup raises demand and second precision")
        check(s.pollInterval === 300, "open popup polls at the configured interval")
        a.save("refreshSeconds", 600)
        var saved = bar.saved[bar.saved.length - 1]
        check(saved && saved.settings.refreshSeconds === 600 && saved.settings.route.from.id === "NSR:StopPlace:59872", "inline save keeps the route")
        a.swapDirection()
        saved = bar.saved[bar.saved.length - 1]
        check(saved.settings.route.from.name === "Lillestrøm" && saved.settings.route.to.name === "Oslo S", "swap saves the reversed pair")
        a.save("refreshSeconds", 7)
        check(a.settingsError !== "", "invalid interval refused: " + a.settingsError)
        a.save("route", { from: shell.route.from, to: shell.route.from })
        check(a.settingsError !== "", "same-station route refused: " + a.settingsError)
        check(JSON.parse(s.statusObject ? JSON.stringify(s.statusObject()) : "{}").pollSeconds > 0, "status object")
        a.close()
        break
      case 5:
        check(!s.demanded, "demand drops when the popup closes")
        check(body.scroller.contentHeight > body.scroller.height + 100, "fixture body overflows its viewport")
        body.moveRequested(0, -1)
        check(body.cursorKey === "refresh" && body.scroller.contentY > 0, "cursor on Refresh scrolls to the footer")
        body.moveRequested(0, -1)
        check(body.cursorKey === "settings" && body.scroller.contentY === 0, "cursor back on Settings scrolls the header into view")
        body.moveRequested(0, 1); body.moveRequested(0, -1); body.moveRequested(0, -1)
        check(body.cursorKey === "swap" && body.scroller.contentY === 0, "cursor on Switch direction keeps the header visible")
        console.log("FOAMY DONE")
        Qt.quit()
      }
    }
  }
}
'''


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    status = 0
    for host in (["4.0", "4.5"] if which == "both" else [which]):
        qml = SHELL.replace("LOCK", LOCK_45 if host == "4.5" else "").replace("HOST", '"%s"' % host)
        run = harness.Run(host, qml, plugin=PLUGIN, prefix="foamy-train-runtime-")
        run.run(timeout=60)
        oks = run.log.count("FOAMY OK")
        if run.ok:
            print(f"{host}: {oks} checks passed")
            run.cleanup()
        else:
            status = 1
            print(f"{host}: FAILED ({oks} ok)\n" + "\n".join(run.failures() or run.log.splitlines()[-30:]))
            print(f"log kept at {run.base}")
    sys.exit(status)


if __name__ == "__main__":
    main()
