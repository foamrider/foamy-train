#!/usr/bin/env python3
"""Offscreen check that the popup's single cursor stays put while the
countdown ticks (round 6 #5): the pointer routes hover into the cursor
(TrainView.stopHovered, what FoamyAction.onHoveredChanged calls), then the
pointer leaves and the 1 s clock rebuilds `departures` (a new array every
tick, as TrainService does), which rebuilds `stops`. The highlight must stay
on the last stop the pointer or keyboard chose, not ping-pong between the
last two. Then the keys' cursor: after a key the stop under it draws the
accent border, after a real pointer move none does, and a notice's icon
keeps its colour either way. Runs on Omarchy 4.5 (the installed shell, or FOAMY_HOST_45).
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
import harness

PLUGIN = Path(__file__).resolve().parents[1]

SHELL = r"""
import QtQuick
import QtTest
import Quickshell
import qs.Commons
import "harness"
import "plugin" as Train
import "plugin/kit"
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
    var quit = function() { console.log("FOAMY DONE"); Qt.quit() }
    if (!ok) return quit()
    stops(); pointer(); keyboard(); vanished(); keysBorder(quit)
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
    check(body.cursorKey === "", "cursor leaves a stop that is gone: '" + body.cursorKey + "'")
    shell.tick()
    check(body.cursorKey === "", "and does not come back on the next tick")
    // The stop comes back in a later report: the cursor must not light it by itself.
    body.report = Fixtures.report("route")
    check(body.cursorKey === "", "nor when the stop comes back: '" + body.cursorKey + "'")
  }
  TestEvent { id: ev }
  // Every item under `item` for which `match` holds.
  function findAll(item, match) {
    var found = match(item) ? [item] : []
    for (var i = 0; i < item.children.length; i++) found = found.concat(findAll(item.children[i], match))
    return found
  }
  function notice(key) { return findAll(shell.view, function(i) { return i.notice !== undefined && i.cursorKey === key })[0] }
  function noticeIcon(n) { return findAll(n, function(i) { return ["cancelled", "warning", "megaphone"].indexOf(i.name) >= 0 })[0] }
  // The stops that draw the keys' accent border: notices and actions.
  function bordered() {
    return findAll(shell.view, function(i) {
      if (i.notice !== undefined && i.cursorKey !== undefined) return i.visible && i.borderTop > 0 && Qt.colorEqual(i.borderSpec.color, i.accent)
      return i.cursorByKeys !== undefined && i.tooltipText !== undefined && i.border.width > 0
    }).map(function(i) { return i.cursorKey || i.objectName || i.label })
  }
  function pointAt(item) { ev.mouseMove(item, item.width / 2, item.height / 2, -1, Qt.NoButton, Qt.NoModifier) }
  // Calls `then` once the popup has laid out and scrolled: the stop
  // items' places in the window are the same on two polls (positioners lay
  // out on the next frame, after a report or a reveal).
  function settled(then) {
    var last = ""
    wait.waitFor(function() {
      var now = JSON.stringify(shell.findAll(shell.view, function(i) { return i.notice !== undefined }).map(function(i) { var p = i.mapToItem(null, 0, 0); return [p.x, p.y, i.height] }))
      var same = now === last
      last = now
      return same
    }, 5000, then, "the popup settles")
  }
  function keysBorder(done) {
    // A cancelled card's notice: its icon is measured on its fill under the cursor.
    body.report = Fixtures.report("incidents")
    var keyStop = "dep/c/withdrawn"
    for (var i = 0; i < 10 && body.cursorKey !== keyStop; i++) body.moveRequested(0, 1)
    var keyed = shell.notice(keyStop)
    check(body.cursorKey === keyStop && keyed.hasCursor && keyed.borderTop === FoamyStyle.borderWidth && JSON.stringify(shell.bordered()) === JSON.stringify([keyStop]), "the keys on " + keyStop + ": its accent border, on it alone: " + JSON.stringify(shell.bordered()))
    var iconByKeys = shell.noticeIcon(keyed).color
    shell.settled(function() {
      shell.pointAt(shell.notice("dep/b/signal2"))
      check(body.cursorKey === "dep/b/signal2" && JSON.stringify(shell.bordered()) === "[]", "the pointer on another notice: the cursor there, no keys' border: " + body.cursorKey + " " + JSON.stringify(shell.bordered()))
      shell.pointAt(keyed)
      check(body.cursorKey === keyStop && JSON.stringify(shell.bordered()) === "[]" && Qt.colorEqual(shell.noticeIcon(keyed).color, iconByKeys), "the pointer back on " + keyStop + ": no border, its icon the colour it had under the keys: " + shell.noticeIcon(keyed).color + " " + iconByKeys)
      body.moveRequested(0, 1)
      check(body.cursorKey === "dep/d/short" && JSON.stringify(shell.bordered()) === JSON.stringify(["dep/d/short"]), "a key again: the border on the next notice: " + JSON.stringify(shell.bordered()))
      body.moveRequested(0, 1)
      check(body.cursorKey === "refresh" && JSON.stringify(shell.bordered()) === JSON.stringify(["refreshAction"]), "and on Refresh: " + JSON.stringify(shell.bordered()))
      shell.settled(function() {
        shell.pointAt(shell.findAll(shell.view, function(i) { return i.objectName === "refreshAction" })[0])
        check(body.cursorKey === "refresh" && JSON.stringify(shell.bordered()) === "[]", "the pointer on Refresh: no border: " + JSON.stringify(shell.bordered()))
        done()
      })
    })
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
