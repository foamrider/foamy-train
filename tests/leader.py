#!/usr/bin/env python3
"""Offscreen on Omarchy 4.5 (the installed shell, or FOAMY_HOST_45): the bars
of two monitors, built the way the host builds them (a window per screen from
Variants, the widget in a Loader), share one TrainService. The leading bar's
settings configure the service and it owns the foamy.train IPC target. When
its screen goes away, the other bar takes over both, and the bar that goes
logs no error (the harness fails a run whose log has a TypeError). No route
is set, so nothing is fetched.
  python3 tests/leader.py
"""

import os
import sys
from pathlib import Path

KIT = Path(os.environ.get("FOAMY_KIT", Path.home() / "GitHub/Personal/foamy-kit"))
# 4.5 is the installed shell (FOAMY_HOST_45 overrides it). Set before the
# harness reads it.
os.environ.setdefault("FOAMY_HOST_45", "/usr/share/omarchy/shell")
sys.path.insert(0, str(KIT / "preview"))
import harness

PLUGIN = Path(__file__).resolve().parents[1]

SHELL = r"""
import QtQuick
import Quickshell
import qs.Commons
import "harness"
import "plugin/kit"
import "plugin" as Train

ShellRoot {
  id: shell
  function check(ok, what) { console.log((ok ? "FOAMY OK " : "FOAMY FAIL ") + what) }
  MockBar { id: bar; moduleName: "foamy.train" }
  // The monitors. The host's bar draws a window per screen (Variants over
  // Quickshell.screens) and loads each widget into it with a Loader: a
  // screen that goes away takes its window, the Loader and the widget along.
  property var screens: ["first", "second"]
  // The intervals differ only so the test can see whose settings configure
  // the service.
  readonly property var intervals: ({ first: 300, second: 600 })
  // The widget's component is made at the root, as the host makes it in
  // shell.qml (Qt.createComponent), not in a screen's window.
  Component {
    id: widget
    Train.Panel { bar: bar; moduleName: "foamy.train"; width: 100; height: 32 }
  }
  Variants {
    model: shell.screens
    delegate: Component {
      FloatingWindow {
        id: screenBar
        required property var modelData
        visible: true; implicitWidth: 120; implicitHeight: 40
        Loader {
          sourceComponent: widget
          // As the host hands a loaded widget its settings (WidgetHost.injectProps).
          onLoaded: item.settings = { refreshSeconds: shell.intervals[screenBar.modelData] }
        }
      }
    }
  }
  readonly property var s: Train.TrainService
  function members() { return FoamyShared.memberCount(s.memberScope) }
  // Enabled foamy.train handlers in the shell's IPC registry.
  function targets() { return IpcRegistry.handlers.filter(function(h) { return h && h.enabled && h.target === "foamy.train" }).length }
  // The service polls at one of the bars' intervals: the leader has pushed the settings it was handed.
  function configured() { return s.configured && (s.refreshSeconds === intervals.first || s.refreshSeconds === intervals.second) }
  FoamyWait { id: wait }
  Component.onCompleted: wait.waitFor(function() { return members() === 2 && configured() }, 15000, function(ok) {
    var leading = s.refreshSeconds === shell.intervals.first ? "first" : "second"
    var other = leading === "first" ? "second" : "first"
    check(ok && s.refreshSeconds === shell.intervals[leading] && targets() === 1,
          "one bar leads: the service polls at its interval (" + s.refreshSeconds + " s) and there is " + targets() + " IPC target")
    shell.screens = [other]
    wait.waitFor(function() { return members() === 1 && s.refreshSeconds === shell.intervals[other] }, 15000, function(ok) {
      check(ok, "when the leading bar's screen goes away, the other bar's settings configure the service: "
            + s.refreshSeconds + " s, " + members() + " member")
      var answer = IpcRegistry.call("foamy.train", "status", [])
      check(targets() === 1 && answer.ran, "and the other bar owns the foamy.train IPC target: " + targets() + " live, answered " + answer.ran)
      console.log("FOAMY DONE")
      Qt.quit()
    }, "the other bar takes over")
  }, "both bars join and the leading one configures the service")
}
"""


def main():
    run = harness.Run("4.5", SHELL, plugin=PLUGIN, prefix="foamy-train-leader-")
    # Nothing is fetched without a route; should a request still go out, the
    # non-loopback endpoint makes it fail before it connects.
    run.env["FOAMY_TRAIN_ENTUR_URL"] = "http://entur.invalid"
    run.run(timeout=60)
    oks = run.log.count("FOAMY OK")
    # Nothing in the run may reach a host command (the harness stubs them).
    hosts = run.host_commands()
    if hosts:
        run.ok = False
        print("host commands run: " + "; ".join(hosts))
    if run.ok:
        print(f"4.5: {oks} checks passed")
        run.cleanup()
        sys.exit(0)
    print(f"4.5: FAILED ({oks} ok)\n" + "\n".join(run.failures() or run.log.splitlines()[-30:]))
    print(f"log kept at {run.base}")
    sys.exit(1)


if __name__ == "__main__":
    main()
