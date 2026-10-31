#!/usr/bin/env python3
"""Offscreen check that the popup's single cursor stays put while the
countdown ticks (round 6 #5): the pointer routes hover into the cursor
(TrainView.stopHovered, what FoamyAction.onHoveredChanged calls), then the
pointer leaves and the 1 s clock rebuilds `departures` (a new array every
tick, as TrainService does), which rebuilds `stops`. The highlight must stay
on the last stop the pointer or keyboard chose, not ping-pong between the
last two.
  python3 tests/cursor.py [4.0|4.5|both]
"""
import os
import sys
from pathlib import Path

KIT = Path(os.environ.get("FOAMY_KIT", Path.home() / "GitHub/Personal/foamy-kit"))
sys.path.insert(0, str(KIT / "preview"))
import harness  # noqa: E402

PLUGIN = Path(__file__).resolve().parents[1]

SHELL = r'''
import QtQuick
import Quickshell
import qs.Commons
import "harness"
import "plugin" as Train
import "plugin/Model.js" as Model
import "plugin/tests/Fixtures.js" as Fixtures

ShellRoot {
  id: shell
  property int step: 0
  property var seen: []
  function check(ok, what) { console.log((ok ? "FOAMY OK " : "FOAMY FAIL ") + what) }
  FloatingWindow {
    visible: true; implicitWidth: 420; implicitHeight: 640
    Train.TrainBody {
      id: body
      width: 420; height: 640
      report: Fixtures.report("normal")
      nowEpoch: Fixtures.now
      // Like TrainService: a fresh array on every clock tick.
      departures: Model.upcoming(report, nowEpoch, false)
      next: Model.next(departures)
      route: Fixtures.route
    }
  }
  readonly property Item view: body.scroller.contentItem.children[0]
  function tick() { body.nowEpoch += 1 }
  // Five ticks; record the lit stop after each.
  function ticks() {
    var keys = []
    for (var i = 0; i < 5; i++) { tick(); keys.push(body.cursorKey) }
    return keys
  }
  function steady(keys, key) { return keys.every(function(k) { return k === key }) }
  Timer {
    interval: 200; repeat: true; running: true
    onTriggered: {
      switch (shell.step++) {
      case 0:
        check(shell.view && shell.view.stops.join(",") === "swap,settings,refresh", "stops are swap, settings, refresh: " + (shell.view ? shell.view.stops.join(",") : "?"))
        var before = shell.view.stops
        shell.tick()
        check(shell.view.stops !== before, "a clock tick rebuilds the stops array (as in the live popup)")
        break
      case 1:
        // Pointer: over Switch direction, then over Refresh, then out of the popup.
        shell.view.stopHovered("swap")
        shell.view.stopHovered("refresh")
        check(body.cursorKey === "refresh", "hover lights Refresh")
        var keys = shell.ticks()
        check(steady(keys, "refresh"), "Refresh stays lit while the clock ticks: " + keys.join(" "))
        break
      case 2:
        shell.view.stopHovered("refresh")
        shell.view.stopHovered("swap")
        var keys2 = shell.ticks()
        check(steady(keys2, "swap"), "Switch direction stays lit while the clock ticks: " + keys2.join(" "))
        break
      case 3:
        // Keyboard: Down from Switch direction to Settings, then tick.
        body.moveRequested(0, 1)
        check(body.cursorKey === "settings", "Down moves to Settings")
        var keys3 = shell.ticks()
        check(steady(keys3, "settings"), "Settings stays lit while the clock ticks: " + keys3.join(" "))
        break
      case 4:
        // A stop that disappears (the next train leaves and its notice goes) drops the cursor.
        body.report = Fixtures.report("route")
        shell.view.stopHovered("route/station")
        check(body.cursorKey === "route/station", "hover lights the route notice")
        body.report = Fixtures.report("normal")
        check(body.cursorKey === "" && body.heldKey === "", "cursor leaves a stop that is gone: '" + body.cursorKey + "'")
        shell.tick()
        check(body.cursorKey === "", "and does not come back on the next tick")
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
        run = harness.Run(host, SHELL, plugin=PLUGIN, prefix="foamy-train-cursor-")
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
