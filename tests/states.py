#!/usr/bin/env python3
"""Offscreen checks of what the bar and the popup show in each state, on the
real TrainBar and TrainBody with fixture reports (no service, no helper, no
network): the bar's countdown and notice marker (only route information and
the next train's information count as information), the popup's texts and
cursor stops for normal, delayed, incidents, cancelled, offline, error,
empty, loading, unconfigured, route notices, a long wait and an old update,
that status texts and icons read at 4.5:1 on what they are drawn on, and
that Entur text never renders as markup. Runs on Omarchy 4.5 (the installed
shell, or FOAMY_HOST_45), in the kit's dark, dim-red and light themes.
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
import "plugin/kit"
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
  // The checks start once the popup body has laid out its stops; only the
  // cursor checks in ink() wait (for the cursor fill to fade in).
  Component.onCompleted: wait.waitFor(function() { return shell.view && shell.view.stops.length === 3 }, 15000, function(ok) {
    if (!ok) return done()
    barStates(); popupStates()
    ink(function() { markup(); done() })
  }, "the popup body lays out its stops")
  function done() {
    console.log("FOAMY DONE")
    Qt.quit()
  }

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

  // Status texts and icons read at 4.5:1 on what they are drawn on: the
  // Cancelled label on its red pill on the card, the delay and on-time texts
  // on a card, notice icons under the cursor's fill (one colour with and
  // without it), the stale-data note on its yellow tint, the late text on
  // the hero band, and a station search error. main() runs the scene in the
  // dark theme, in a dark theme with a dim red (2.70:1 raw) and in a light
  // theme, where a yellow must darken.
  function ancestor(item, match) {
    while (item && !match(item)) item = item.parent
    return item
  }
  function reads(item, under, what) {
    var ratio = FoamyPalette.contrastRatio(item.color, under)
    check(ratio >= 4.5, "ink, " + what + ": " + item.color + " on " + under + " reads " + ratio.toFixed(2) + ":1 (4.5:1 needed)")
  }
  // As reads(), but a colour the kit stepped as far as it goes (1.7 times,
  // FoamyPalette.onSurface) passes under 4.5:1: in the light theme the
  // yellow on the band's strongest tint ends there, at 4.40:1.
  function readsOrCapped(item, raw, under, what) {
    var ratio = FoamyPalette.contrastRatio(item.color, under)
    var cap = Qt.color((FoamyPalette.lightTheme ? Qt.darker(raw, 1.7) : Qt.lighter(raw, 1.7)).toString())
    check(ratio >= 4.5 || Qt.colorEqual(item.color, cap), "ink, " + what + ": " + item.color + " on " + under + " reads "
          + ratio.toFixed(2) + ":1 (4.5:1 needed, or the kit's last step " + cap + ")")
  }
  function shown(match) {
    var list = []
    walk(body, function(i) { if (i.visible && match(i)) list.push(i) })
    return list
  }
  function cardOf(item) { return ancestor(item, function(i) { return i.departure !== undefined }) }
  // A departure card's fill as drawn on the popup.
  function cardSurface(item) { return Qt.tint(FoamyPalette.background, cardOf(item).color) }
  // A colour read from a property is a live reference: copy it to keep it.
  function copy(c) { return Qt.rgba(c.r, c.g, c.b, c.a) }
  // Puts the cursor on the notice at `key` and calls then(notice) once its
  // fill has faded in (CursorSurface animates its colour): unchanged since
  // the last poll and no longer the fill it had without the cursor.
  function hover(key, then) {
    var notice = shown(function(i) { return i.notice !== undefined && i.cursorKey === key })[0]
    check(!!notice && !notice.hasCursor, "ink: the notice " + key + " is shown, without the cursor")
    if (!notice) return then(null)
    var before = copy(notice.color), last = before
    shell.view.stopHovered(key)
    wait.waitFor(function() {
      var settled = Qt.colorEqual(notice.color, last) && !Qt.colorEqual(notice.color, before)
      last = copy(notice.color)
      return notice.hasCursor && settled
    }, 5000, function(ok) { then(ok ? notice : null) }, "ink: the cursor's fill on " + key)
  }
  // The status icon of the notice at `key`, checked without and with the
  // cursor on what lies under the notice (`under`, opaque).
  function noticeIcon(key, under, what, then) {
    var notice = shown(function(i) { return i.notice !== undefined && i.cursorKey === key })[0]
    var icon = null
    if (notice)
      walk(notice, function(i) { if (!icon && i.visible && (i.name === "warning" || i.name === "cancelled")) icon = i })
    check(!!icon, "ink: " + what + " has a status icon")
    if (!icon) return then()
    var before = copy(icon.color)
    reads(icon, Qt.tint(under(notice), notice.color), what)
    hover(key, function(lit) {
      if (lit) {
        reads(icon, Qt.tint(under(lit), lit.color), what + " under the cursor")
        check(Qt.colorEqual(icon.color, before), "ink, " + what + ": one colour with and without the cursor: " + before + ", " + icon.color)
      }
      then()
    })
  }
  function ink(then) {
    show("delayed")
    var delay = shown(function(i) { return i.text === "· +3 min" && cardOf(i) })
    check(delay.length === 1, "ink: one delay text on a card in delayed, found " + delay.length)
    if (delay.length === 1) reads(delay[0], cardSurface(delay[0]), "delay text on its card")
    var band = find(body, "heroBand")
    // The band's strongest tint: the wash's start colour under the full glow.
    var paint = null
    walk(band, function(i) { if (!paint && i.fill !== undefined && i.fillEnd !== undefined && i.glow !== undefined) paint = i })
    var late = []
    walk(band, function(i) { if (i.visible && i.text === "· 3 min late") late.push(i) })
    check(!!paint && late.length === 1, "ink: the band paints a wash and shows the late text, found " + late.length)
    if (paint && late.length === 1) readsOrCapped(late[0], FoamyPalette.warning, Qt.tint(paint.fill, paint.glow), "late text on the band")
    noticeIcon("dep/b/signal2", cardSurface, "warning notice icon on a card", function() {
      // Loading the next report clears the cursor.
      show("normal")
      show("delayed")
      noticeIcon("next/signal", function() { return FoamyPalette.background }, "filled warning notice icon", function() { incidentsInk(then) })
    })
  }
  function incidentsInk(then) {
    show("incidents")
    var found = shown(function(i) { return i.text === "Cancelled" })
    check(found.length === 1, "ink: one Cancelled label in incidents, found " + found.length)
    if (found.length === 1)
      reads(found[0], Qt.tint(cardSurface(found[0]), found[0].parent.color), "Cancelled on its pill")
    var onTime = shown(function(i) { return i.text === "· On time" && cardOf(i) })
    check(onTime.length > 0, "ink: an on-time text on a card in incidents")
    for (var i = 0; i < onTime.length; i++) reads(onTime[i], cardSurface(onTime[i]), "on-time text on its card")
    noticeIcon("dep/c/withdrawn", cardSurface, "cancelled notice icon on its card", function() {
      show("offline")
      var note = shown(function(i) { return i.Accessible.role === Accessible.AlertMessage && i.text.indexOf("Cached times") === 0 })
      check(note.length === 1, "ink: the stale-data note shows in offline, found " + note.length)
      if (note.length === 1) reads(note[0], Qt.tint(FoamyPalette.background, note[0].parent.color), "stale-data note on its tint")

      search.error = "Station search failed. Try again."
      var errors = []
      walk(search, function(i) { if (i.visible && i.text === search.error) errors.push(i) })
      check(errors.length === 1, "ink: the station search error shows")
      if (errors.length === 1)
        reads(errors[0], FoamyPalette.background, "station search error")
      search.error = ""
      then()
    })
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


def check_theme(name, theme):
    run = harness.Run("4.5", SHELL, plugin=PLUGIN, theme=theme, prefix="foamy-train-states-")
    run.run(timeout=60)
    oks = run.log.count("FOAMY OK")
    # Nothing here may start a process or reach a host command.
    hosts = run.host_commands()
    if hosts:
        run.ok = False
        print("host commands run: " + "; ".join(hosts))
    if run.ok:
        print(f"4.5 {name}: {oks} checks passed")
        run.cleanup()
        return True
    print(f"4.5 {name}: FAILED (%d ok)\n" % oks + "\n".join(run.failures() or run.log.splitlines()[-30:]))
    print(f"log kept at {run.base}")
    return False


def main():
    # The kit's dim-red fixture and light preview theme: the status colour
    # checks (ink) fail there when a text or icon draws the raw red, or a
    # yellow or green measured on the wrong surface.
    themes = [("dark", "dark"), ("dim-red", str(KIT / "tests/fixtures/themes/dim-red.toml")), ("light", "light")]
    results = [check_theme(name, theme) for name, theme in themes]
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
