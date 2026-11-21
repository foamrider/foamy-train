#!/usr/bin/env python3
"""Offscreen checks of what the bar and the popup show in each state, on the
real TrainBar and TrainBody with fixture reports (no service, no helper, no
network): the bar's countdown and notice marker (only route information and
the next train's information count as information), the popup's texts and
cursor stops for normal, delayed, incidents, cancelled, offline, error,
empty, loading, unconfigured, route notices, a long wait and an old update,
and that Entur text never renders as markup. Runs on Omarchy 4.5 (the
installed shell, or FOAMY_HOST_45).
  python3 tests/states.py
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
import "plugin" as Train
import "plugin/Model.js" as Model
import "plugin/tests/Fixtures.js" as Fixtures

ShellRoot {
  id: shell
  function check(ok, what) { console.log((ok ? "FOAMY OK " : "FOAMY FAIL ") + what) }
  function find(item, name) {
    if (item.objectName === name) return item
    for (var i = 0; i < item.children.length; i++) { var found = find(item.children[i], name); if (found) return found }
    return null
  }
  // Every item under `item` once, hidden ones too.
  function walk(item, visit, seen) {
    seen = seen || []
    if (!item || seen.indexOf(item) >= 0) return
    seen.push(item)
    visit(item)
    for (var i = 0; i < item.children.length; i++) walk(item.children[i], visit, seen)
    if (item.contentItem) walk(item.contentItem, visit, seen)
  }
  // The texts a user sees under `item`: shown items with a non-empty text.
  function texts(item) {
    var list = []
    walk(item, function(i) { if (i.visible && typeof i.text === "string" && i.text !== "") list.push(i.text) })
    return list
  }
  function has(item, text) { return texts(item).indexOf(text) >= 0 }
  function none(item, part) { return texts(item).every(function(t) { return t.indexOf(part) < 0 }) }
  function times(item, text) { return texts(item).filter(function(t) { return t === text }).length }

  // The bar widget, fed like Panel.qml feeds it.
  FloatingWindow {
    visible: true; implicitWidth: 300; implicitHeight: 40
    Train.TrainBar { id: bar }
  }
  // A popup body, fed like preview/Preview.qml feeds it.
  property var report: Fixtures.report("normal")
  property bool loading: false
  FloatingWindow {
    visible: true; implicitWidth: 420; implicitHeight: 900
    Train.TrainBody {
      id: body
      width: 420; height: 900
      report: shell.report
      nowEpoch: Fixtures.now
      stale: Model.stale(report, Fixtures.now, false, 60)
      departures: Model.upcoming(report, Fixtures.now, stale)
      next: Model.next(departures)
      loading: shell.loading
      route: report.route
    }
  }
  // Station search results with markup in a label.
  FloatingWindow {
    visible: true; implicitWidth: 320; implicitHeight: 300
    Train.StationSearch { id: search; width: 300; label: "From" }
  }
  readonly property Item view: body.scroller.contentItem.children[0]

  FoamyWait { id: wait }
  // The checks are synchronous once the popup body has laid out its stops.
  Component.onCompleted: wait.waitFor(function() { return shell.view && shell.view.stops.length === 3 }, 15000, function(ok) {
    if (ok) { barStates(); popupStates(); markup() }
    console.log("FOAMY DONE")
    Qt.quit()
  }, "the popup body lays out its stops")

  // Sets the bar to one state (defaults for everything not named) and
  // returns what it shows.
  function showBar(departures, state) {
    state = state || {}
    bar.departures = departures
    bar.next = Model.next(departures)
    bar.routeNotices = state.routeNotices || []
    bar.nowEpoch = Fixtures.now
    bar.stale = !!state.stale
    bar.withinSchedule = state.withinSchedule !== false
    bar.showMinutes = state.showMinutes !== false
    bar.vertical = !!state.vertical
    bar.language = state.language || "en"
    var countdown = find(bar, "barCountdown"), marker = find(bar, "barNotice")
    return {
      countdown: countdown.visible ? countdown.text : "",
      late: Qt.colorEqual(countdown.color, bar.warning),
      marker: marker.visible ? marker.name : ""
    }
  }
  function barStates() {
    var normal = function() { return Fixtures.report("normal").departures }
    var with_ = function(change) { var d = normal(); change(d); return d }
    var late = function(d) { d[0] = Fixtures.departure("a", 13, "R10", 3) }
    var cancelled = function(d) { d[1].cancelled = true }
    // [what, departures, state, countdown ("" hidden), late colour, marker ("" none)]
    var rows = [
      ["on time", normal(), {}, "11 min", false, ""],
      ["a long wait", Fixtures.report("long").departures, {}, "12 h 4 min", false, ""],
      ["a long wait in Norwegian", Fixtures.report("long").departures, { language: "no" }, "12 t 4 min", false, ""],
      ["the next train late", with_(late), {}, "13 min", true, ""],
      ["a later train late", with_(function(d) { d[1] = Fixtures.departure("b", 20, "R11", 3) }), {}, "11 min", false, "warning"],
      ["a warning on a later train", with_(function(d) { d[2].notices = [Fixtures.notice("x", "Signal fault", "warning")] }), {}, "11 min", false, "warning"],
      ["information on the next train", with_(function(d) { d[0].notices = [Fixtures.notice("x", "Shorter train", "info")] }), {}, "11 min", false, "megaphone"],
      ["information on a later train only", with_(function(d) { d[1].notices = [Fixtures.notice("x", "Shorter train", "info")] }), {}, "11 min", false, ""],
      ["route information", normal(), { routeNotices: [Fixtures.notice("route", "Lift unavailable", "info")] }, "11 min", false, "megaphone"],
      ["a cancellation and a warning", with_(function(d) { cancelled(d); d[0].notices = [Fixtures.notice("x", "Signal fault", "warning")] }), {}, "11 min", false, "cancelled"],
      ["cached times", with_(cancelled), { stale: true }, "—", false, ""],
      ["outside the schedule", with_(cancelled), { withinSchedule: false }, "", false, ""],
      ["minutes hidden, the next train late", with_(late), { showMinutes: false }, "", true, "warning"],
      ["a vertical bar", with_(cancelled), { vertical: true }, "", false, ""],
      ["no departures", [], {}, "—", false, ""],
    ]
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i], shown = showBar(row[1], row[2])
      var countdownOk = shown.countdown === row[3] && (row[3] === "" || row[3] === "—" || shown.late === row[4])
      check(countdownOk && shown.marker === row[5],
            "bar, " + row[0] + ": countdown '" + shown.countdown + "'" + (shown.late ? " (late)" : "") + ", marker '" + shown.marker
            + "'; expected '" + row[3] + "'" + (row[4] ? " (late)" : "") + ", marker '" + row[5] + "'")
    }
  }

  function show(state, change) {
    var r = Fixtures.report(state)
    if (change) change(r)
    shell.loading = state === "loading"
    shell.report = r
    return shell.view
  }
  function stops() { return shell.view.stops.join(",") }
  function popupStates() {
    show("normal")
    check(has(body, "Next to Lillestrøm") && has(body, "Following departures") && has(body, "Updated just now")
          && has(body, "11") && has(body, "min") && none(body, "Cancelled"), "popup, normal: " + texts(body).join(" | "))
    check(stops() === "swap,settings,refresh", "popup, normal: stops " + stops())

    var view = show("delayed")
    check(has(body, "· 3 min late"), "popup, delayed: the next train says 3 min late")
    check(view.stops.indexOf("next/signal") >= 0 && view.stops.indexOf("dep/b/signal2") >= 0 && view.stops.indexOf("next/carriage") < 0,
          "popup, delayed: notices with detail are stops, one without is not: " + stops())
    var detail = "The departure is waiting for a clear signal. Check the platform display before boarding."
    check(!has(body, detail), "popup, delayed: the detail is closed at first")
    view.activate("next/signal")
    check(has(body, detail), "popup, delayed: activating the notice shows its detail")
    view.activate("next/signal")
    check(!has(body, detail), "popup, delayed: activating it again hides the detail")

    show("incidents")
    check(times(body, "Cancelled") === 1 && none(body, "28 min"),
          "popup, incidents: the cancelled train shows Cancelled, not a countdown: " + texts(body).join(" | "))
    check(stops() === "swap,settings,next/signal,dep/b/signal2,dep/c/withdrawn,dep/d/short,refresh", "popup, incidents: stops in visual order " + stops())

    show("cancelled")
    check(has(body, "All upcoming trains are cancelled") && times(body, "Cancelled") === 4 && none(body, "No direct trains found"),
          "popup, cancelled: " + texts(body).join(" | "))

    show("offline")
    check(has(body, "Last known to Lillestrøm") && has(body, "Last known departures")
          && has(body, "Cached times; live predictions unavailable.\nOffline. Showing the last available update.")
          && has(body, "Updated 12 minutes ago") && none(body, "On time"), "popup, offline: " + texts(body).join(" | "))

    show("error")
    check(has(body, "No departures available") && has(body, "Cannot reach Entur. Check your connection and try Refresh.")
          && none(body, "No direct trains found"), "popup, error: a failure never reads as no trains: " + texts(body).join(" | "))

    show("empty")
    check(has(body, "No direct trains found"), "popup, empty: " + texts(body).join(" | "))
    show("loading")
    check(has(body, "Loading departures…") && none(body, "No direct trains found"), "popup, loading: " + texts(body).join(" | "))

    show("unconfigured")
    check(has(body, "Choose your stations") && has(body, "Choose stations") && none(body, "Entur"),
          "popup, unconfigured: no footer: " + texts(body).join(" | "))
    check(stops() === "settings,choose", "popup, unconfigured: no Refresh stop: " + stops())

    show("route")
    check(has(body, "Route notices") && has(body, "Oslo S · Lift to the platforms out of service") && shell.view.stops.indexOf("route/station") >= 0,
          "popup, route notices: " + stops())
    show("long")
    check(has(body, "12") && has(body, "h") && has(body, "4") && has(body, "min"), "popup, a long wait: " + texts(body).join(" | "))
    show("normal", function(r) { r.updatedAt = Fixtures.now - 25 * 3600 })
    check(has(body, "Updated 1 day ago"), "popup, an old update counts days: " + texts(body).join(" | "))
  }

  // Entur data (station names, line, platform, notices, search labels) with
  // tags must show as text: every sink that holds a "<" is plain text.
  function markup() {
    var tags = "<b>x</b><img src=\"http://127.0.0.1:9/x\"><a href=\"x\">y</a>"
    show("normal", function(r) {
      r.route = { from: { id: "NSR:StopPlace:1", name: "From " + tags }, to: { id: "NSR:StopPlace:2", name: "To " + tags } }
      r.departures[0].line = "<b>R10</b>"
      r.departures[0].platform = "<i>11</i>"
      r.departures[0].notices = [Fixtures.notice("tagged", "Summary " + tags, "warning", "Detail " + tags, "Scope " + tags)]
      r.departures[1].notices = [Fixtures.notice("tagged2", "Summary " + tags, "info", "Detail " + tags)]
      r.routeNotices = [Fixtures.notice("route", "Route " + tags, "info", "Detail " + tags, "Scope " + tags)]
    })
    shell.view.activate("next/tagged")
    shell.view.activate("route/route")
    search.results = [{ id: "NSR:StopPlace:3", name: "Station", label: "Station " + tags }]
    var sinks = 0, rich = []
    var visit = function(item) {
      if (item.textFormat === undefined || typeof item.text !== "string" || item.text.indexOf("<") < 0) return
      sinks++
      if (item.textFormat !== Text.PlainText) rich.push(item.text)
    }
    walk(body, visit)
    walk(search, visit)
    check(sinks >= 8 && rich.length === 0, "Entur text is never markup: " + sinks + " sinks, rich: " + rich.join(" | "))
  }
}
"""


def main():
    run = harness.Run("4.5", SHELL, plugin=PLUGIN, prefix="foamy-train-states-")
    run.run(timeout=60)
    oks = run.log.count("FOAMY OK")
    # Nothing here may start a process or reach a host command.
    hosts = run.host_commands()
    if hosts:
        run.ok = False
        print("host commands run: " + "; ".join(hosts))
    if run.ok:
        print(f"4.5: {oks} checks passed")
        run.cleanup()
        sys.exit(0)
    print("4.5: FAILED (%d ok)\n" % oks + "\n".join(run.failures() or run.log.splitlines()[-30:]))
    print(f"log kept at {run.base}")
    sys.exit(1)


if __name__ == "__main__":
    main()
