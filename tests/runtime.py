#!/usr/bin/env python3
"""Offscreen runtime checks on Omarchy 4.5 (the installed shell, or
FOAMY_HOST_45): two bar instances share one TrainService (leader configures
it), the in-process `lock isLocked` probe pauses polling while locked, the route
reaches the helper on stdin (never argv), popup demand switches the clock
to seconds, settings saves keep the route, invalid values are refused, outside the
schedule the popup still shows departures, snoozing mutes the widget
until tomorrow without saving settings (an open popup still fetches), an
oversized cached report (an older helper's: 10,000 route notices) reaches the
popup within the report's limits, the schedule rows save their days, and a
snooze that can't be saved still applies and is logged.

Uses the foamy-kit preview harness (temp HOME/XDG, no Wayland/Hyprland, no
host scripts): FOAMY_KIT=/path/to/foamy-kit (default ~/GitHub/Personal/foamy-kit).
The system bus is a dead address, so NetworkManager is invisible and the
helper runs in offline mode; its Entur endpoint is also overridden with a
non-loopback URL, which fails every request without connecting. Entur is
never contacted.
  python3 tests/runtime.py
"""
import hashlib
import json
import os
import sys
import time
from pathlib import Path

KIT = Path(os.environ.get("FOAMY_KIT", Path.home() / "GitHub/Personal/foamy-kit"))
# 4.5 is the installed shell (FOAMY_HOST_45 overrides it). Set before the
# harness reads it.
os.environ.setdefault("FOAMY_HOST_45", "/usr/share/omarchy/shell")
sys.path.insert(0, str(KIT / "preview"))
import harness  # noqa: E402

PLUGIN = Path(__file__).resolve().parents[1]

SHELL = r'''
import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import "harness"
import "plugin/kit"
import "plugin/kit/FoamyNative.js" as FoamyNative
import "plugin" as Train
import "plugin/tests/Fixtures.js" as Fixtures
import "plugin/Preferences.js" as Schema

ShellRoot {
  id: shell
  property bool locked: true
  property var route: ({ from: { id: "NSR:StopPlace:59872", name: "Oslo S" }, to: { id: "NSR:StopPlace:62339", name: "Lillestrøm" } })
  property var entry: ({ route: shell.route, refreshSeconds: 300 })
  property int savedCount: 0
  function check(ok, what) { if (!ok) console.log("FOAMY FAIL " + what); else console.log("FOAMY OK " + what) }
  MockBar { id: bar; moduleName: "foamy.train" }
  // The stock lock's in-process `lock isLocked` target.
  ShellIpc { target: "lock"; function isLocked(): string { return shell.locked ? "true" : "false" } }
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
  // The service's own report in a popup body: its notices are delegates.
  FloatingWindow {
    visible: true; implicitWidth: 420; implicitHeight: 300
    Train.TrainBody {
      id: live
      width: 420; height: 300
      report: Train.TrainService.report
      nowEpoch: Train.TrainService.nowEpoch
      stale: Train.TrainService.stale
      departures: Train.TrainService.departures
      next: Train.TrainService.next
      route: Train.TrainService.route
    }
  }
  // Items under `item` whose type name starts with `type`.
  function count(item, type) {
    var n = String(item).indexOf(type + "_QMLTYPE") === 0 ? 1 : 0
    for (var i = 0; i < item.children.length; i++) n += count(item.children[i], type)
    return n
  }
  function find(item, name) {
    if (item.objectName === name) return item
    for (var i = 0; i < item.children.length; i++) { var found = find(item.children[i], name); if (found) return found }
    return null
  }
  // Station search whose process can't start (no such deadline command):
  // `searching` still clears and the failure shows. Then a helper that
  // isn't there (bash exits 127): the usual unavailable message.
  FloatingWindow {
    visible: true; implicitWidth: 320; implicitHeight: 120
    Train.StationSearch { id: search; width: 300; label: "From"; pluginDir: "/nonexistent/foamy-train" }
  }
  // The settings page with the schedule on: one row per day.
  property var paneSettings: ({ scheduleEnabled: true, scheduleMonday: "07:00-09:00", scheduleTuesday: "" })
  property var paneSaves: []
  FloatingWindow {
    visible: true; implicitWidth: 420; implicitHeight: 900
    Train.SettingsPane {
      id: pane
      width: 420
      settings: shell.paneSettings
      language: "en"
      onSaveRequested: function(key, value) { shell.paneSaves.push([key, value]) }
    }
  }
  function startSearch(text) {
    search.input.text = text
    search.searching = true
    search.runSearch()
  }
  FoamyWait { id: wait }
  // Runs `then` once `condition` holds; a timeout fails the run and ends it.
  function when(condition, label, then) {
    wait.waitFor(condition, 15000, function(ok) {
      if (ok) then()
      else Qt.quit()
    }, label)
  }
  readonly property var s: Train.TrainService
  Component.onCompleted: when(function() { return s.active && s.configured }, "the leader configures the service", step0)
  function step0() {
    check(s.active && s.configured, "service active and configured by the leader")
    check(s.refreshSeconds === 300 && s.route && s.route.from.name === "Oslo S", "leader pushed its settings")
    check(s.clock.step === 60000, "minute clock while every popup is closed")
    s.statusProcess.running = false
    search.deadline = ["/nonexistent/foamy-no-such-command"]
    shell.startSearch("Oslo")
    // running -> false for a start that failed arrives asynchronously, and
    // so does the end of a startup fetch stopped above (one that started
    // before the lock stand-in registered).
    when(function() { return !search.inFlight && !s.inFlight && !s.loading }, "the search that can't start ends", step1)
  }
  function step1() {
    check(!search.searching, "a search that can't start stops searching")
    check(search.error === "Station search failed. Try again.", "and says it failed: " + search.error)
    search.deadline = ["timeout", "--kill-after=2s", "18s"]
    shell.startSearch("Bergen")
    s.refresh(false, false)
    check(s.lockInProcess && s.sessionLocked, "the in-process lock probe reports locked")
    check(!s.statusProcess.running, "no Entur request while locked")
    check(s.pollInterval === 10, "locked: only the cheap lock probe ticks (10 s)")
    shell.locked = false
    when(function() { return !search.inFlight && !s.loading }, "the next search and any fetch end", step2)
  }
  function step2() {
    check(!search.searching && search.error === FoamyNative.UNAVAILABLE_TEXT, "the next search runs and finishes: " + search.error)
    s.refresh(false, false)
    check(!s.sessionLocked, "unlocked session polls again")
    check(s.statusProcess.running, "a request starts after unlock")
    when(function() { return !s.loading && !s.inFlight }, "the unlocked request ends", step3)
  }
  function step3() {
    var argv = s.statusProcess.command.join(" ")
    check(argv.indexOf("--route-stdin") >= 0 && argv.indexOf("NSR:") < 0 && argv.indexOf("Oslo") < 0, "route is not in argv")
    check(argv.indexOf("timeout --kill-after=2s 18s bash -c") === 0 && argv.indexOf("foamy-train-helper") >= 0, "the native helper runs under the widget timeout")
    check(s.report.route && s.report.route.to.name === "Lillestrøm", "helper received the route on stdin (" + s.report.status + "/" + s.report.errorCode + ")")
    check(s.report.errorCode === "offline", "sandbox fetch is offline (no network)")
    check(!s.networkConnected, "the service sees no network connection (system bus isolated)")
    // The cache holds 10 departures with 300 notices each and 10,000 route notices.
    var view = live.scroller.contentItem
    var notices = count(view, "Notice"), cards = count(view, "DepartureCard")
    check(s.report.status === "stale" && s.report.departures.length === 6 && s.report.routeNotices.length === 5,
          "an oversized cached report is cut to 6 departures and 5 route notices: " + s.report.departures.length + "/" + s.report.routeNotices.length)
    check(notices === 23 && cards === 5, "at most 6 x 3 + 5 notice delegates: " + notices + " notices, " + cards + " cards")
    var omitted = find(view, "noticesOmitted")
    check(s.report.noticesOmitted === true && omitted && omitted.visible, "the popup says some notices are not shown")
    a.open()
    when(function() { return s.demanded }, "the open popup raises demand", step4)
  }
  function step4() {
    check(s.clock.step === 1000, "open popup raises demand and second precision")
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
    check(JSON.parse(JSON.stringify(s.statusObject())).pollSeconds > 0, "status object")
    a.close()
    when(function() { return !s.demanded }, "demand drops when the popup closes", step5)
  }
  function step5() {
    check(!s.demanded, "demand drops when the popup closes")
    check(body.scroller.contentHeight > body.scroller.height + 100, "fixture body overflows its viewport")
    body.moveRequested(0, -1)
    check(body.cursorKey === "refresh" && body.scroller.contentY > 0, "cursor on Refresh scrolls to the footer")
    body.moveRequested(0, -1)
    check(body.cursorKey === "settings" && body.scroller.contentY === 0, "cursor back on Settings scrolls the header into view")
    body.moveRequested(0, 1); body.moveRequested(0, -1); body.moveRequested(0, -1)
    check(body.cursorKey === "swap" && body.scroller.contentY === 0, "cursor on Switch direction keeps the header visible")
    // A mouse-wheel notch split 8 x 15 scrolls about three rows (FoamyWheelScroll).
    var wheel = body.scrollerWheel
    check(!!wheel && wheel.target === body.scroller, "the body scrolls with the kit wheel handling")
    if (wheel) {
      for (var n = 0; n < 8; n++) wheel.wheel({ angleDelta: Qt.point(0, -15), pixelDelta: Qt.point(0, 0) })
      var to = isNaN(wheel.destination) ? body.scroller.contentY : wheel.destination
      check(Math.abs(to - Math.min(wheel.notch, wheel.maxY)) < 1, "one wheel notch scrolls about three rows: " + to)
      wheel.scrollTo(0, false)
    }
    // Outside the schedule the popup shows the departures as usual; the
    // header says why the bar is muted.
    body.outsideSchedule = true
    when(function() { return bodyPart("heroBand") && bodyPart("heroBand").meta.indexOf(" · outside your schedule") > 0 },
         "outside the schedule the header says so", step6)
  }
  // A direct child of the fixture body's content column.
  function bodyPart(name) {
    var view = body.scroller.contentItem.children[0]
    for (var i = 0; i < view.children.length; i++) if (view.children[i].objectName === name) return view.children[i]
    return null
  }
  function step6() {
    var view = body.scroller.contentItem.children[0]
    var band = bodyPart("heroBand"), details = bodyPart("departureDetails")
    check(band.meta.indexOf(" · outside your schedule") > 0, "outside the schedule the header says so: " + band.meta)
    check(details && details.visible, "outside the schedule the departures still show")
    var stops = view.stops.join(",")
    check(stops.indexOf("swap,settings,") === 0 && view.stops[view.stops.length - 1] === "refresh", "stops: Switch direction, ⋯, … Refresh: " + stops)
    // Snooze and Settings are in the ⋯ menu; Switch direction stays a button.
    check(band.settingsInMenu && band.shownTrailing.length === 1 && band.menuItems[0].iconName === "sun"
          && band.menuItems[0].text === "Resume now", "Snooze and Settings are in the ⋯ menu; outside the schedule it offers Resume now")
    view.activate("settings")
    check(band.menuOpen && body.blocked, "Enter on ⋯ opens the menu, which takes the keys")
    band.closeMenu()
    body.snoozed = true
    check(band.meta.indexOf(" · snoozed") > 0 && band.menuItems[0].text === "Stop snoozing", "snoozed: the header says so; the menu offers Stop snoozing")
    body.outsideSchedule = false; body.snoozed = false
    check(band.menuItems[0].text === "Snooze until tomorrow" && band.menuItems[0].iconName === "moon", "in the schedule the menu offers Snooze until tomorrow")
    // The service: no schedule, so in force until snoozed.
    shell.savedCount = bar.saved.length
    check(s.withinSchedule && !s.snoozed, "without a schedule the widget is in force")
    s.toggleSnooze()
    var midnight = new Date(); midnight.setHours(24, 0, 0, 0)
    check(!s.withinSchedule && s.snoozed && !s.canPoll && !s.canFetch(), "snoozing mutes the widget and stops background fetches")
    check(s.scheduleOverride && s.scheduleOverride.until === midnight.getTime(), "without a schedule the snooze lasts until midnight")
    check(bar.saved.length === shell.savedCount, "snoozing never saves settings")
    a.open()
    when(function() { return s.demanded }, "the popup opens while snoozed", step7)
  }
  function step7() {
    check(s.live && s.canFetch(), "an open popup still fetches while snoozed")
    a.close()
    when(function() { return !s.demanded }, "the popup closes while snoozed", step8)
  }
  function step8() {
    check(!s.live && !s.canFetch(), "closing the popup stops fetching again")
    s.toggleSnooze()
    check(s.withinSchedule && !s.snoozed && s.scheduleOverride === null, "pressing again resumes the schedule")
    check(bar.saved.length === shell.savedCount, "resuming never saves settings")
    // A departure request that can't start (no such deadline command):
    // Quickshell emits no exited(), only running -> false. The request
    // still ends: the failure shows and the refresh queued behind it runs.
    when(function() { return !s.inFlight && !s.pendingRefresh }, "requests from resuming end", function() {
      s.deadline = ["/nonexistent/foamy-no-such-command"]
      s.refresh(true, true)
      s.refresh(true, true)
      check(s.inFlight && s.pendingRefresh, "a second refresh queues behind the first")
      when(function() { return !s.inFlight && !s.pendingRefresh }, "the failed request and the queued one end", step9)
    })
  }
  function step9() {
    check(!s.loading && s.report.error === "Train request failed. Try Refresh.",
          "a request that can't start fails visibly: " + s.report.status + "/" + s.report.error)
    s.deadline = ["timeout", "--kill-after=2s", "18s"]
    s.refresh(true, true)
    when(function() { return !s.inFlight }, "the next request ends", step10)
  }
  function step10() {
    check(s.report.errorCode === "offline" && s.report.error !== "Train request failed. Try Refresh.",
          "the next request runs normally: " + s.report.errorCode)
    // A helper whose search reply lists more stations than the 8 asked for.
    search.pluginDir = Quickshell.env("FOAMY_TRAIN_FAKE_SEARCH")
    shell.startSearch("Many")
    when(function() { return !search.inFlight }, "the long station search ends", step11)
  }
  function step11() {
    check(search.error === "" && search.results.length === 8 && search.results[7].id === "NSR:StopPlace:8",
          "a long station list shows the first 8: " + search.results.length + " " + search.error)
    when(function() { return find(pane, "scheduleSunday") !== null }, "the settings page lists the schedule days", step12)
  }
  // The schedule rows: popup text labels, the switch and the time fields
  // save the day's range; an invalid time is reported, not saved.
  function step12() {
    var monday = find(pane, "scheduleMonday"), tuesday = find(pane, "scheduleTuesday")
    var labels = []
    for (var i = 0; i < Schema.dayKeys.length; i++) {
      var row = find(pane, Schema.dayKeys[i])
      labels.push(row && count(row, "TrainText") === 1 ? row.label : "?")
    }
    check(labels.join(",") === "Monday,Tuesday,Wednesday,Thursday,Friday,Saturday,Sunday", "each day row has one TrainText label: " + labels.join(","))
    var from = find(monday, "fromTime"), to = find(monday, "toTime")
    check(monday.dayEnabled && from.text === "07:00" && to.text === "09:00" && find(monday, "daySwitch").checked, "Monday shows its range, switched on")
    check(!tuesday.dayEnabled && !find(tuesday, "daySwitch").checked && !find(tuesday, "fromTime").enabled, "Tuesday is off, its times disabled")
    find(monday, "daySwitch").toggled()
    find(tuesday, "daySwitch").toggled()
    from.text = "08:15"; from.editingFinished()
    to.text = "25:00"; to.editingFinished()
    check(JSON.stringify(shell.paneSaves) === JSON.stringify([["scheduleMonday", ""], ["scheduleTuesday", "06:00-18:00"],
          ["scheduleMonday", "08:15-09:00"], ["scheduleMonday", "invalid"]]), "the row saves: " + JSON.stringify(shell.paneSaves))
    shell.paneSettings = { scheduleEnabled: true, scheduleMonday: "", scheduleTuesday: "" }
    check(!monday.dayEnabled && from.text === "07:00", "turned off, Monday keeps its last range in the fields: " + from.text)
    find(monday, "daySwitch").toggled()
    check(shell.paneSaves[shell.paneSaves.length - 1][1] === "07:00-09:00", "switched on again, Monday saves its last range")
    // The snooze state file can't be written (a read-only state folder): the
    // snooze still applies, and the failed save is logged (runtime.py checks).
    shell.overridePath = s.overridePath
    s.overridePath = Quickshell.env("FOAMY_TRAIN_READONLY_STATE") + "/foamy-train/schedule-override.json"
    s.toggleSnooze()
    check(s.snoozed, "a snooze that can't be saved still applies")
    when(function() { return shell.saveFailures === 1 }, "the snooze save fails", step13)
  }
  property string overridePath: ""
  property int saveFailures: 0
  Connections {
    target: Train.TrainService.overrideFile
    function onSaveFailed() { shell.saveFailures++ }
  }
  function step13() {
    s.toggleSnooze()
    check(!s.snoozed, "resuming works the same way")
    when(function() { return shell.saveFailures === 2 }, "the resume save fails", function() {
      s.overridePath = shell.overridePath
      console.log("FOAMY DONE")
      Qt.quit()
    })
  }
}
'''


def fake_search(directory, count=40):
    """A plugin directory whose helper (either arch) answers every search
    with `count` valid stations."""
    stations = [{"id": f"NSR:StopPlace:{n}", "name": f"Station {n}", "label": f"Station {n}, Norway"}
                for n in range(1, count + 1)]
    reply = json.dumps({"status": "ok", "stations": stations})
    for arch in ("x86_64", "aarch64"):
        helper = directory / "bin" / arch / "foamy-train-helper"
        helper.parent.mkdir(parents=True)
        helper.write_text("#!/bin/sh\ncat <<'EOF'\n" + reply + "\nEOF\n")
        helper.chmod(0o755)
    return directory


def oversized_cache(home, route):
    """The departure cache an older helper could leave: every notice kept.
    The route as the service sends it, both languages, the default 24 hours."""
    now = int(time.time())
    clock = time.strftime("%H:%M", time.gmtime(now))

    def notice(identifier):
        return {"id": identifier, "summary": "Signal fault", "detail": "", "kind": "warning", "scopeLabel": ""}

    def departure(i):
        return {"id": f"sj{i}", "line": "R10", "aimed": now + 600 * i, "expected": now + 600 * i,
                "arrival": now + 600 * i + 600, "aimedTime": clock, "expectedTime": clock, "arrivalTime": clock,
                "delay": 0, "duration": 10, "platform": "1", "realtime": True, "cancelled": False,
                "notices": [notice(f"n{i}-{n}") for n in range(300)]}
    report = {"status": "ok", "route": route, "departures": [departure(i) for i in range(1, 11)],
              "routeNotices": [notice(f"r{n}") for n in range(10_000)], "updatedAt": now - 60, "stale": False,
              "error": "", "errorCode": ""}
    text = json.dumps(report, ensure_ascii=False) + "\n"
    assert len(text.encode()) < 2_000_000, len(text)
    directory = home / ".cache" / "foamy.train"
    directory.mkdir(parents=True, mode=0o700)
    for language in ("en", "nb"):
        key = f"{route['from']['id']}/{route['to']['id']}/{language}/24"
        path = directory / (hashlib.sha256(key.encode()).hexdigest() + ".json")
        path.write_text(text)
        path.chmod(0o600)


ROUTE = {"from": {"id": "NSR:StopPlace:59872", "name": "Oslo S"}, "to": {"id": "NSR:StopPlace:62339", "name": "Lillestrøm"}}


def main():
    run = harness.Run("4.5", SHELL, plugin=PLUGIN, prefix="foamy-train-runtime-")
    # The harness gives qs a dead system bus, so NetworkManager is invisible
    # (on the real one the service would ask Entur two seconds later); the
    # non-loopback endpoint override makes any request that still goes out
    # fail before it connects.
    run.env["FOAMY_TRAIN_ENTUR_URL"] = "http://entur.invalid"
    run.env["FOAMY_TRAIN_FAKE_SEARCH"] = str(fake_search(run.base / "fake-search"))
    oversized_cache(Path(run.env["HOME"]), ROUTE)
    readonly = run.base / "readonly-state"
    readonly.mkdir(mode=0o500)
    run.env["FOAMY_TRAIN_READONLY_STATE"] = str(readonly)
    run.run(timeout=90)
    readonly.chmod(0o700)
    oks = run.log.count("FOAMY OK")
    # A snooze or resume that can't be saved is logged, once each.
    unsaved = run.log.count("foamy-train: couldn't save the snooze state to ")
    if unsaved != 2:
        run.ok = False
        print(f"failed snooze saves logged: {unsaved}, expected 2")
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
