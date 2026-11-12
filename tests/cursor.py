#!/usr/bin/env python3
"""Offscreen check that the popup's single cursor stays put while the
countdown ticks (round 6 #5): the pointer routes hover into the cursor
(TrainView.stopHovered, what FoamyAction.onHoveredChanged calls), then the
pointer leaves and the 1 s clock rebuilds `departures` (a new array every
tick, as TrainService does), which rebuilds `stops`. The highlight must stay
on the last stop the pointer or keyboard chose, not ping-pong between the
last two. Runs on Omarchy 4.5 (the installed shell, or FOAMY_HOST_45).
  python3 tests/cursor.py
"""

import os
import sys
from pathlib import Path

KIT = Path(os.environ.get("FOAMY_KIT", Path.home() / "GitHub/Personal/foamy-kit"))
# 4.5 is the installed shell (FOAMY_HOST_45 overrides it). Set before the
# harness reads it.
os.environ.setdefault("FOAMY_HOST_45", "/usr/share/omarchy/shell")
sys.path.insert(0, str(KIT / "preview"))
import harness  # noqa: E402

PLUGIN = Path(__file__).resolve().parents[1]

SHELL = r"""
import QtQuick
import Quickshell
import qs.Commons
import "harness"
import "plugin" as Train
import "plugin/Model.js" as Model
import "plugin/tests/Fixtures.js" as Fixtures

ShellRoot {
  id: shell
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
  FoamyWait { id: wait }
  // The steps are synchronous once the popup body has laid out its stops.
  Component.onCompleted: wait.waitFor(function() { return shell.view && shell.view.stops.length === 3 }, 15000, function(ok) {
    if (ok) { stops(); pointer(); keyboard(); vanished() }
    console.log("FOAMY DONE")
    Qt.quit()
  }, "the popup body lays out its stops")
  function stops() {
    check(shell.view.stops.join(",") === "swap,settings,refresh", "stops are swap, settings (⋯), refresh: " + shell.view.stops.join(","))
    var before = shell.view.stops
    shell.tick()
    check(shell.view.stops !== before, "a clock tick rebuilds the stops array (as in the live popup)")
  }
  function pointer() {
    // Pointer: over Switch direction, then over Refresh, then out of the popup.
    shell.view.stopHovered("swap")
    shell.view.stopHovered("refresh")
    check(body.cursorKey === "refresh", "hover lights Refresh")
    var keys = shell.ticks()
    check(steady(keys, "refresh"), "Refresh stays lit while the clock ticks: " + keys.join(" "))
    shell.view.stopHovered("refresh")
    shell.view.stopHovered("swap")
    var keys2 = shell.ticks()
    check(steady(keys2, "swap"), "Switch direction stays lit while the clock ticks: " + keys2.join(" "))
  }
  function keyboard() {
    // Keyboard: Down from Switch direction to Settings (the ⋯ button), then tick.
    body.moveRequested(0, 1)
    check(body.cursorKey === "settings", "Down moves to Settings")
    var keys3 = shell.ticks()
    check(steady(keys3, "settings"), "Settings stays lit while the clock ticks: " + keys3.join(" "))
  }
  function vanished() {
    // A stop that disappears (the next train leaves and its notice goes) drops the cursor.
    body.report = Fixtures.report("route")
    shell.view.stopHovered("route/station")
    check(body.cursorKey === "route/station", "hover lights the route notice")
    body.report = Fixtures.report("normal")
    check(body.cursorKey === "" && body.heldKey === "", "cursor leaves a stop that is gone: '" + body.cursorKey + "'")
    shell.tick()
    check(body.cursorKey === "", "and does not come back on the next tick")
  }
}
"""


def main():
    run = harness.Run("4.5", SHELL, plugin=PLUGIN, prefix="foamy-train-cursor-")
    run.run(timeout=60)
    oks = run.log.count("FOAMY OK")
    if run.ok:
        print(f"4.5: {oks} checks passed")
        run.cleanup()
        sys.exit(0)
    print("4.5: FAILED (%d ok)\n" % oks + "\n".join(run.failures() or run.log.splitlines()[-30:]))
    print(f"log kept at {run.base}")
    sys.exit(1)


if __name__ == "__main__":
    main()
