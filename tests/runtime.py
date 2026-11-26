#!/usr/bin/env python3
"""Offscreen runtime checks on Omarchy 4.5 (the installed shell, or
FOAMY_HOST_45): two bar instances share one TrainService (leader configures
it), the in-process `lock isLocked` probe pauses polling while locked, the route
reaches the helper on stdin (never argv), popup demand switches the clock
to seconds, settings saves keep the route, invalid values are refused and not
saved, the foamy.train IPC target answers through the shell's IpcRegistry
(status, swap, settings, close, snooze, refresh), outside the schedule the
popup still shows departures, snoozing mutes the widget until tomorrow without
saving settings (an open popup on either bar still fetches), an oversized
cached report (an older helper's: 10,000 route notices) reaches the popup
within the report's limits, a station query reaches the helper as one
argument, a paste that fails after a search found no station shows its own
error under the field, the schedule rows and the route fields save what they should, a
snooze that can't be saved still applies and is logged, a weekly schedule
from the settings hides or mutes the widget and stops fetching, a stored
same-station route is reported without a fetch, switching the weekly
schedule on in the popup's settings shows its day rows and keeps the page
within its bounds while the popup grows to fit, a choice or a day range the
settings can't save (no bar entry) shows the saved one again at once, and,
with real key presses, Esc closes the popup after it was closed on Settings
and opened again, and after Back from Settings.

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
import harness

PLUGIN = Path(__file__).resolve().parents[1]

SHELL = r"""
import QtQuick
import QtTest
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
  // Helper starts of the service, counted where the process starts.
  property int fetches: 0
  property int before: 0
  Connections {
    target: Train.TrainService.statusProcess
    function onRunningChanged() { if (Train.TrainService.statusProcess.running) shell.fetches++ }
  }
  function check(ok, what) { if (!ok) console.log("FOAMY FAIL " + what); else console.log("FOAMY OK " + what) }
  MockBar { id: bar; moduleName: "foamy.train" }
  // The screen the popups draw into (offscreen Qt has no layer shell): an
  // open popup lays out and shows as on the desktop.
  FloatingWindow {
    visible: true; implicitWidth: 1920; implicitHeight: 1080
    ScreenSim {}
    // Real key presses, sent to the window that has the focus.
    Item { TestEvent { id: ev } }
  }
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
  // Nothing in flight or queued. The process reports `running` later than
  // fetch() starts it, so a helper start is counted only once the service
  // is idle again.
  function idle() { return !s.inFlight && !s.statusProcess.running && !s.pendingRefresh }
  // Waits until the service is idle, runs `poke`, waits until it is idle
  // again and calls `then` with the number of helper starts in between.
  function startsAfter(poke, label, then) {
    when(idle, "the service is idle before: " + label, function() {
      var n = shell.fetches
      poke()
      when(idle, label, function() { then(shell.fetches - n) })
    })
  }
  readonly property var s: Train.TrainService
  Component.onCompleted: when(function() { return s.active && s.configured }, "the leader configures the service", step0)
  function step0() {
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
    IpcRegistry.call("foamy.train", "swap", [])
    saved = bar.saved[bar.saved.length - 1]
    check(saved.settings.route.from.name === "Lillestrøm" && saved.settings.route.to.name === "Oslo S", "IPC swap saves the reversed pair")
    // As the host reflects a save to every bar instance. Without it the saved
    // values stay pending and are dropped 10 s later, which reconfigures the
    // service (and starts a fetch) at a moment no step controls.
    shell.entry = saved.settings
    var n = bar.saved.length
    a.save("refreshSeconds", 7)
    check(a.settingsError !== "" && bar.saved.length === n && !a.saving, "an invalid interval is refused and nothing is saved: " + a.settingsError)
    a.save("route", { from: shell.route.from, to: shell.route.from })
    check(a.settingsError === "Choose two different stations." && bar.saved.length === n && !a.saving,
          "a same-station route is refused with its reason and nothing is saved: " + a.settingsError)
    // The IPC target through the shell's registry: one live handler for both
    // bar instances, with exactly the documented functions.
    var targets = IpcRegistry.handlers.filter(function(h) { return h && h.enabled && h.target === "foamy.train" })
    check(targets.length === 1, "one live foamy.train IPC target for two bar instances: " + targets.length)
    var names = targets.length === 1 ? IpcRegistry.declaredFunctions(targets[0]).sort().join(",") : ""
    check(names === "close,open,refresh,settings,snooze,status,swap,toggle", "the IPC target's functions: " + names)
    var answer = IpcRegistry.call("foamy.train", "status", [])
    var status = answer.ran ? JSON.parse(answer.output) : ({})
    check(Object.keys(status).sort().join(",") === "departures,lockProbe,locked,networkReady,pollSeconds,snoozed,stale,status,withinSchedule"
          && status.lockProbe === "in-process" && status.locked === false && status.pollSeconds === s.pollInterval,
          "IPC status reports the service state: " + answer.output)
    check(!IpcRegistry.call("foamy.train", "bogus", []).ran, "IPC refuses an unknown function")
    a.close()
    when(function() { return !s.demanded }, "demand drops when the popup closes", stepSettings)
  }
  function stepSettings() {
    IpcRegistry.call("foamy.train", "settings", [])
    when(function() { return s.demanded && ((a.opened && a.editingSettings) || (b.opened && b.editingSettings)) },
         "IPC settings opens the popup on Settings", function() {
      IpcRegistry.call("foamy.train", "close", [])
      when(function() { return !s.demanded && !a.editingSettings && !b.editingSettings && !s.loading && !s.inFlight },
           "IPC close closes the popup and leaves Settings", step5)
    })
  }
  function step5() {
    check(body.scroller.contentHeight > body.scroller.height + 100, "fixture body overflows its viewport")
    body.moveRequested(0, -1)
    check(body.cursorKey === "refresh" && body.scroller.contentY > 0, "cursor on Refresh scrolls to the footer")
    body.moveRequested(0, -1)
    check(body.cursorKey === "settings" && body.scroller.contentY === 0, "cursor back on Settings scrolls the header into view")
    body.moveRequested(0, 1); body.moveRequested(0, -1); body.moveRequested(0, -1)
    check(body.cursorKey === "swap" && body.scroller.contentY === 0, "cursor on Switch direction keeps the header visible")
    // A mouse-wheel notch split 8 x 15 (the kit's FoamyWheelScroll on the body's scroller).
    var wheel = body.scrollerWheel
    for (var n = 0; n < 8; n++) wheel.wheel({ angleDelta: Qt.point(0, -15), pixelDelta: Qt.point(0, 0) })
    var to = isNaN(wheel.destination) ? body.scroller.contentY : wheel.destination
    check(wheel.target === body.scroller && to > 0, "the mouse wheel scrolls the popup body: " + to)
    wheel.scrollTo(0, false)
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
    IpcRegistry.call("foamy.train", "snooze", [])
    var midnight = new Date(); midnight.setHours(24, 0, 0, 0)
    check(!s.withinSchedule && s.snoozed, "IPC snooze mutes the widget")
    check(barTooltip().indexOf(" · snoozed") > 0, "the bar tooltip says snoozed: " + barTooltip())
    check(s.scheduleOverride && s.scheduleOverride.until === midnight.getTime(), "without a schedule the snooze lasts until midnight")
    check(bar.saved.length === shell.savedCount, "snoozing never saves settings")
    startsAfter(function() { s.refresh(false, false); s.refresh(true, false) }, "background refreshes while snoozed end", function(started) {
      check(started === 0, "snoozed, a background refresh starts no helper: " + started)
      // Any bar's open popup counts as demand (step4 opened the other one).
      shell.before = shell.fetches
      b.open()
      when(function() { return s.demanded && shell.fetches > shell.before }, "a popup opened while snoozed starts a fetch", step7)
    })
  }
  function step7() {
    b.close()
    when(function() { return !s.demanded }, "the popup closes while snoozed", step8)
  }
  function step8() {
    startsAfter(function() { s.refresh(false, false) }, "a background refresh with the popup closed ends", function(started) {
      check(!s.live && started === 0, "with the popup closed again nothing is fetched: " + started)
      step8b()
    })
  }
  function step8b() {
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
    IpcRegistry.call("foamy.train", "refresh", [])
    when(function() { return !s.inFlight }, "the next request ends", step10)
  }
  function step10() {
    check(s.report.errorCode === "offline" && s.report.error !== "Train request failed. Try Refresh.",
          "the next request runs normally: " + s.report.errorCode)
    // A helper whose search reply lists more stations than the 8 asked for.
    // The query is shell syntax: it must reach the helper as one argument
    // (main() reads what the fake helper received).
    search.pluginDir = Quickshell.env("FOAMY_TRAIN_FAKE_SEARCH")
    shell.startSearch("-x $(id)")
    when(function() { return !search.inFlight }, "the long station search ends", step11)
  }
  function step11() {
    check(search.error === "" && search.results.length === 8 && search.results[7].id === "NSR:StopPlace:8",
          "a long station list shows the first 8: " + search.results.length + " " + search.error)
    stepPaste()
  }
  // The texts a user sees under `item`: shown items with a non-empty text.
  function shown(item) {
    var list = item.visible && typeof item.text === "string" && item.text !== "" ? [item.text] : []
    for (var i = 0; i < item.children.length; i++) list = list.concat(shown(item.children[i]))
    return list
  }
  // A typed name finds no station, then a paste fails (the clipboard holds
  // no text: main() makes the wl-paste stand-in fail). The line under the
  // field shows the paste's error, not the older search message.
  function stepPaste() {
    search.pluginDir = Quickshell.env("FOAMY_TRAIN_FAKE_EMPTY_SEARCH")
    shell.startSearch("Xyzzy")
    when(function() { return !search.inFlight }, "the search that finds no station ends", function() {
      check(shown(search).indexOf("No stations found.") >= 0, "a search that finds no station says so: " + shown(search).join(" | "))
      // A paste lands only in a field with the focus, in the active window.
      var window = search.Window.window
      window.requestActivate()
      when(function() { return window.active }, "the station search window is active", function() {
        search.input.focusInput()
        when(function() { return search.input.inputActiveFocus }, "the station field takes the focus", stepPasteFails)
      })
    })
  }
  function stepPasteFails() {
    search.input.requestPaste(false)
    when(function() { return !search.input.pasteRunning }, "the failed paste ends", function() {
      var texts = shown(search)
      check(texts.indexOf("Could not paste clipboard text. Copy plain text and try again.") >= 0 && texts.indexOf("No stations found.") < 0,
            "a failed paste shows its error under the station field, not the older search message: " + texts.join(" | ")
            + " (the field's paste error: " + search.input.pasteError + ")")
      when(function() { return find(pane, "scheduleSunday") !== null }, "the settings page lists the schedule days", step12)
    })
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
    // The route fields save a pair only when both stations are chosen and it changes.
    var fromSearch = find(pane, "fromSearch"), toSearch = find(pane, "toSearch")
    var stationA = { id: "NSR:StopPlace:1", name: "A", label: "A" }, stationB = { id: "NSR:StopPlace:2", name: "B", label: "B" }
    var saves = shell.paneSaves.length
    fromSearch.choose(stationA)
    check(shell.paneSaves.length === saves, "one chosen station saves nothing")
    toSearch.choose(stationB)
    var last = shell.paneSaves[shell.paneSaves.length - 1]
    check(shell.paneSaves.length === saves + 1 && last[0] === "route" && last[1].from.id === "NSR:StopPlace:1" && last[1].to.id === "NSR:StopPlace:2",
          "the second station saves the pair: " + JSON.stringify(last))
    pane.route = { from: { id: "NSR:StopPlace:1", name: "A" }, to: { id: "NSR:StopPlace:2", name: "B" } }
    saves = shell.paneSaves.length
    toSearch.choose(stationB)
    check(shell.paneSaves.length === saves, "choosing the saved route again saves nothing")
    fromSearch.input.text = "O"; fromSearch.input.textEdited()
    check(shell.paneSaves.length === saves && fromSearch.selected === null, "editing a station's text clears it and saves nothing")
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
    when(function() { return shell.saveFailures === 2 }, "the resume save fails", step14)
  }
  // The bar tooltip (bar.showTooltip has no size limit): station names come
  // from Entur, at most 160 code points each, so the route part is capped.
  function barTooltip() {
    for (var i = 0; i < a.children.length; i++) if (a.children[i].tooltipText !== undefined) return a.children[i].tooltipText
    return ""
  }
  function step14() {
    s.overridePath = shell.overridePath
    var shown = s.route.from.name + " → " + s.route.to.name
    check(barTooltip().indexOf("Trains · " + shown + " · ") === 0 || barTooltip() === "Trains · " + shown,
          "a short route is shown whole in the bar tooltip: " + barTooltip())
    // 160 code points each, the most a saved station name may have.
    var long = Array(160).join("Ø")
    // As the host reflects a saved route to every bar instance.
    shell.entry = { route: { from: { id: "NSR:StopPlace:1", name: long + "1" }, to: { id: "NSR:StopPlace:2", name: long + "2" } }, refreshSeconds: 300 }
    when(function() { return s.route && s.route.from.id === "NSR:StopPlace:1" }, "the long route reaches the service", function() {
      var route = barTooltip().split(" · ")[1] || ""
      check(Array.from(route).length <= 100 && route.slice(-1) === "…" && route.indexOf(long) < 0,
            "a long route is cut in the bar tooltip: " + Array.from(route).length + " code points")
      step15()
    })
  }
  // A weekly schedule from the settings, independent of the clock: every day
  // off, then every day all day. (The run is offline, so the button is dimmed
  // in every state; `dimmed` says nothing here.)
  function step15() {
    shell.entry = Object.assign({}, shell.entry, { scheduleEnabled: true, scheduleOutsideMode: "hide" })
    when(function() { return !s.withinSchedule }, "a schedule with every day off takes effect", function() {
      check(!a.visible && !b.visible, "outside the schedule both bars hide the widget")
      startsAfter(function() { s.refresh(false, false); s.refresh(true, false) }, "background refreshes outside the schedule end", step15b)
    })
  }
  function step15b(started) {
    check(started === 0, "outside the schedule a refresh starts no helper: " + started)
    shell.entry = Object.assign({}, shell.entry, { scheduleOutsideMode: "mute" })
    when(function() { return a.visible && b.visible }, "muted outside the schedule, the widget shows", function() {
      check(barTooltip().indexOf(" · outside your schedule") > 0, "the bar tooltip says outside your schedule: " + barTooltip())
      var always = {}
      for (var i = 0; i < Schema.dayKeys.length; i++) always[Schema.dayKeys[i]] = "00:00-24:00"
      shell.before = shell.fetches
      shell.entry = Object.assign({}, shell.entry, always)
      // With every popup closed, the schedule that starts fetches by itself.
      when(function() { return s.withinSchedule && a.visible && !s.demanded && shell.fetches > shell.before },
           "every day all day puts the widget in force and fetches at once", function() {
        check(barTooltip().indexOf("outside your schedule") < 0, "in the schedule the tooltip drops the note: " + barTooltip())
        startsAfter(function() { s.refresh(false, false) }, "a background refresh in the schedule ends", function(started) {
          check(started === 1, "in the schedule a background refresh starts the helper: " + started)
          step16()
        })
      })
    })
  }
  // A hand-edited shell.json with the same station at both ends.
  function step16() {
    shell.before = shell.fetches
    shell.entry = Object.assign({}, shell.entry, { route: { from: shell.route.from, to: shell.route.from } })
    when(function() { return s.route === null && s.report.status === "error" && idle() }, "a stored same-station route gives an error report", function() {
      check(s.report.error === "Choose two different stations." && shell.fetches === shell.before,
            "an invalid stored route is reported and nothing is fetched: " + s.report.error)
      stepScheduleReveal()
    })
  }
  // Switching the weekly schedule on in the popup's settings: the card grows
  // with its content (FoamyPopup fits it to the body), the page scrolls the
  // day rows into view and stays within its bounds. First with less room
  // than the page needs (the card capped at 700 px), then with room for all
  // of it (the screen's available height).
  function stepScheduleReveal() {
    shell.entry = { route: shell.route, refreshSeconds: 300 }
    when(function() { return s.route && s.route.from.id === shell.route.from.id && idle() }, "a valid route is stored again", function() {
      scheduleReveal(700, true, function() {
        scheduleReveal(0, false, stepRefusedChoice)
      })
    })
  }
  // The FoamySettingsPage around `item`.
  function settingsPage(item) {
    for (var at = item; at; at = at.parent) if (at.flickable !== undefined && at.wheel !== undefined) return at
    return null
  }
  // Runs `then` once `ready()` holds and the page is at rest: no glide runs
  // and two readings in a row agree.
  function whenAtRest(page, ready, label, then) {
    var flick = page.flickable, last = ""
    when(function() {
      var reading = [flick.contentY, flick.contentHeight, flick.height].join("/")
      var still = reading === last
      last = reading
      return ready() && isNaN(page.wheel.destination) && still
    }, label, then)
  }
  function scheduleReveal(cap, overflows, then) {
    var room = cap > 0 ? "a card capped at " + cap + " px" : "room for the whole page"
    var toggle = null, page = null
    a.popup.maxHeight = cap
    a.openSettings()
    when(function() {
      toggle = a.popup.bodyItem ? find(a.popup.bodyItem, "scheduleEnabled") : null
      page = toggle ? settingsPage(toggle) : null
      return a.opened && a.editingSettings && page && page.visible && page.flickable.height > 0
    }, "Settings opens (" + room + ")", function() {
      var flick = page.flickable
      whenAtRest(page, function() { return !toggle.checked && !a.saving }, "Settings comes to rest with the schedule off (" + room + ")", function() {
        check(flick.contentY === 0, "Settings opens at the top of its page (" + room + "): contentY " + flick.contentY)
        var saves = bar.saved.length
        toggle.clicked()
        var saved = bar.saved[bar.saved.length - 1]
        check(bar.saved.length === saves + 1 && saved.settings.scheduleEnabled === true, "the switch saves the schedule on (" + room + ")")
        // As the host reflects the save to every bar instance.
        shell.entry = saved.settings
        whenAtRest(page, function() {
          var sunday = find(page, "scheduleSunday")
          return toggle.checked && !a.saving && sunday && sunday.height > 0
                 && sunday.mapToItem(flick.contentItem, 0, 0).y + sunday.height <= flick.contentHeight + 0.5
        }, "the settings page comes to rest with the schedule's rows laid out (" + room + ")", function() {
          var end = Math.max(0, flick.contentHeight - flick.height)
          var top = flick.contentY, bottom = top + flick.height
          check(top >= -0.5 && top <= end + 0.5,
                "the page stays within its bounds (" + room + "): contentY " + top + ", its end " + end
                + (top > end ? ", " + (top - end) + " px past its end" : ""))
          var monday = find(page, "scheduleMonday"), sunday = find(page, "scheduleSunday")
          var rowsTop = monday.mapToItem(flick.contentItem, 0, 0).y
          var rowsBottom = sunday.mapToItem(flick.contentItem, 0, 0).y + sunday.height
          if (overflows)
            check(end > 0 && rowsBottom > flick.height, "the page is taller than the card, and the rows end below an unscrolled view ("
                  + room + "): rows end at " + rowsBottom + ", view " + flick.height + ", page " + flick.contentHeight)
          else
            check(end < 0.5, "the whole page fits (" + room + "): page " + flick.contentHeight + ", view " + flick.height)
          check(rowsTop >= top - 0.5 && rowsBottom <= bottom + 0.5,
                "the schedule's day rows are in view (" + room + "): rows " + rowsTop + "-" + rowsBottom + ", view " + top + "-" + bottom)
          // The schedule off again, at rest, before the next case opens Settings.
          toggle.clicked()
          shell.entry = bar.saved[bar.saved.length - 1].settings
          whenAtRest(page, function() { return !toggle.checked && !a.saving }, "the settings page comes to rest with the schedule off again (" + room + ")", function() {
            a.close()
            when(function() { return !a.opened }, "the popup closes (" + room + ")", then)
          })
        })
      })
    })
  }
  // Choices the settings can't save: without a bar entry (no module name)
  // the queue refuses every save. A refused pick gives way to the saved
  // choice at once, instead of showing beside the error until its hold ends.
  function stepRefusedChoice() {
    // The schedule on, as the host reflects it: "Outside the schedule" shows.
    shell.entry = Object.assign({}, shell.entry, { scheduleEnabled: true })
    a.openSettings()
    when(function() {
      var outside = a.popup.bodyItem ? find(a.popup.bodyItem, "scheduleOutsideMode") : null
      return a.opened && a.editingSettings && outside !== null && outside.visible
    }, "Settings opens with every choice shown", function() {
      var saves = bar.saved.length
      a.moduleName = ""
      // Each choice: pick an option other than the saved one.
      var names = ["lookAheadHours", "refreshSeconds", "scheduleOutsideMode"]
      for (var i = 0; i < names.length; i++) {
        var choice = find(a.popup.bodyItem, names[i]), saved = choice.value
        var before = shown(choice)
        var other = choice.options.filter(function(option) { return option.value !== saved })[0]
        choice.select(other.value)
        var after = shown(choice)
        check(JSON.stringify(after) === JSON.stringify(before) && after.indexOf(other.label) < 0,
              "a refused pick of " + other.label + " in " + names[i] + " shows the saved choice again at once: "
              + after.join(" | ") + " (before the pick: " + before.join(" | ") + ")")
      }
      check(bar.saved.length === saves && a.settingsError === "Settings can't be saved: this widget has no bar entry.",
            "the picks are refused and nothing is saved: " + a.settingsError)
      a.moduleName = "foamy.train"
      shell.entry = Object.assign({}, shell.entry, { scheduleEnabled: false })
      a.close()
      when(function() { return !a.opened }, "the popup closes after the refused picks", stepRefusedRange)
    })
  }
  // A day range the settings can't save (no bar entry, as above): the day's
  // time fields show the saved range again at once.
  function stepRefusedRange() {
    shell.entry = Object.assign({}, shell.entry, { scheduleEnabled: true, scheduleMonday: "07:00-09:00" })
    a.openSettings()
    var monday = null
    when(function() {
      monday = a.popup.bodyItem ? find(a.popup.bodyItem, "scheduleMonday") : null
      return a.opened && a.editingSettings && monday !== null && monday.visible && find(monday, "fromTime").text === "07:00"
    }, "Settings opens with Monday's saved range", function() {
      var from = find(monday, "fromTime"), to = find(monday, "toTime")
      var saves = bar.saved.length
      a.moduleName = ""
      from.text = "08:15"; from.editingFinished()
      check(bar.saved.length === saves && a.settingsError === "Settings can't be saved: this widget has no bar entry.",
            "the range is refused and nothing is saved: " + a.settingsError)
      check(from.text === "07:00" && to.text === "09:00",
            "a refused range shows the saved 07:00-09:00 again at once: " + from.text + "-" + to.text)
      a.moduleName = "foamy.train"
      shell.entry = Object.assign({}, shell.entry, { scheduleEnabled: false })
      a.close()
      when(function() { return !a.opened }, "the popup closes after the refused range", stepKeysClosedOnSettings)
    })
  }
  // The keys after Settings hides, with real key presses: the popup closed
  // on Settings opens again with its keys in the body, so Esc closes it; Esc
  // on Settings goes back, and the next Esc closes the popup.
  function focused() {
    var window = a.popup.bodyItem ? a.popup.bodyItem.Window.window : null
    return window ? window.activeFocusItem : null
  }
  function inside(item, ancestor) {
    for (var at = item; at; at = at.parent) if (at === ancestor) return true
    return false
  }
  function esc() { ev.keyClick(Qt.Key_Escape, Qt.NoModifier, -1) }
  // Opens the popup (on Settings with `settings`) and runs `then` once its
  // window is active. On the desktop the host's exclusive keyboard focus
  // does that as the popup opens; offscreen, the test asks for it.
  function openActive(settings, label, then) {
    if (settings) a.openSettings()
    else a.open()
    when(function() { return a.opened && a.editingSettings === settings && a.popup.bodyItem !== null }, "the popup opens (" + label + ")", function() {
      var window = a.popup.bodyItem.Window.window
      window.requestActivate()
      when(function() { return window.active }, "the popup's window is active (" + label + ")", then)
    })
  }
  // Runs `then` once the settings page has the keys (its Back button).
  function settingsHasKeys(label, then) {
    var page = settingsPage(find(a.popup.bodyItem, "scheduleEnabled"))
    when(function() { return page.visible && inside(focused(), page) }, "the settings page has the keys (" + label + ")", then)
  }
  function stepKeysClosedOnSettings() {
    openActive(true, "closed on Settings", function() {
      settingsHasKeys("closed on Settings", function() {
        a.close()
        check(!a.editingSettings, "closing the popup leaves Settings")
        // Opened again once the closed popup has faded out, as a user would.
        when(function() { return !a.popup.visible }, "the popup closed on Settings hides", function() {
          openActive(false, "opened again", function() {
            when(function() { return inside(focused(), a.popup.bodyItem) }, "the popup's body has the keys", function() {
              var holder = focused()
              esc()
              check(!a.opened, "Esc closes the popup that was closed on Settings (the keys were on " + holder + ")")
              when(function() { return !a.popup.visible }, "the popup closed with Esc hides", stepKeysAfterBack)
            })
          })
        })
      })
    })
  }
  function stepKeysAfterBack() {
    openActive(true, "Back", function() {
      settingsHasKeys("Back", function() {
        esc()
        check(a.opened && !a.editingSettings, "Esc on Settings goes back")
        // The keys come back to the popup's key catcher after Back.
        wait.waitFor(function() { return focused() === a.popup.bodyItem }, 3000, function(back) {
          check(back, "after Back the popup's key catcher has the keys: " + focused())
          esc()
          check(!a.opened, "the next Esc closes the popup")
          done()
        }, "the keys come back after Back")
      })
    })
  }
  function done() {
    console.log("FOAMY DONE")
    Qt.quit()
  }
}
"""


def fake_search(directory, count=40):
    """A plugin directory whose helper (either arch) answers every search
    with `count` valid stations and appends its arguments, one per line, to
    `directory`/argv."""
    stations = [
        {"id": f"NSR:StopPlace:{n}", "name": f"Station {n}", "label": f"Station {n}, Norway"}
        for n in range(1, count + 1)
    ]
    reply = json.dumps({"status": "ok", "stations": stations})
    for arch in ("x86_64", "aarch64"):
        helper = directory / "bin" / arch / "foamy-train-helper"
        helper.parent.mkdir(parents=True)
        helper.write_text(
            "#!/bin/sh\nprintf '%s\\n' \"$@\" >> '" + str(directory / "argv") + "'\ncat <<'EOF'\n" + reply + "\nEOF\n"
        )
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
        return {
            "id": f"sj{i}",
            "line": "R10",
            "aimed": now + 600 * i,
            "expected": now + 600 * i,
            "arrival": now + 600 * i + 600,
            "aimedTime": clock,
            "expectedTime": clock,
            "arrivalTime": clock,
            "delay": 0,
            "duration": 10,
            "platform": "1",
            "realtime": True,
            "cancelled": False,
            "notices": [notice(f"n{i}-{n}") for n in range(300)],
        }

    report = {
        "status": "ok",
        "route": route,
        "departures": [departure(i) for i in range(1, 11)],
        "routeNotices": [notice(f"r{n}") for n in range(10_000)],
        "updatedAt": now - 60,
        "stale": False,
        "error": "",
        "errorCode": "",
    }
    text = json.dumps(report, ensure_ascii=False) + "\n"
    assert len(text.encode()) < 2_000_000, len(text)
    directory = home / ".cache" / "foamy.train"
    directory.mkdir(parents=True, mode=0o700)
    for language in ("en", "nb"):
        key = f"{route['from']['id']}/{route['to']['id']}/{language}/24"
        path = directory / (hashlib.sha256(key.encode()).hexdigest() + ".json")
        path.write_text(text)
        path.chmod(0o600)


ROUTE = {
    "from": {"id": "NSR:StopPlace:59872", "name": "Oslo S"},
    "to": {"id": "NSR:StopPlace:62339", "name": "Lillestrøm"},
}


def main():
    run = harness.Run("4.5", SHELL, plugin=PLUGIN, prefix="foamy-train-runtime-")
    # The harness gives qs a dead system bus, so NetworkManager is invisible
    # (on the real one the service would ask Entur two seconds later); the
    # non-loopback endpoint override makes any request that still goes out
    # fail before it connects.
    run.env["FOAMY_TRAIN_ENTUR_URL"] = "http://entur.invalid"
    run.env["FOAMY_TRAIN_FAKE_SEARCH"] = str(fake_search(run.base / "fake-search"))
    run.env["FOAMY_TRAIN_FAKE_EMPTY_SEARCH"] = str(fake_search(run.base / "fake-empty-search", count=0))
    # A paste reads the kit's wl-paste stand-in, never the real clipboard. It
    # fails, as wl-paste does when the clipboard holds no text (an image).
    run.env.update(harness.hostenv.clipboard_fakes(run.base / "clipboard", run.env))
    Path(run.env["TEST_CLIPBOARD_STATE"]).write_text("failure")
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
    # The station query reached the helper as one argument, not as shell syntax.
    argv = run.base / "fake-search" / "argv"
    received = argv.read_text().splitlines() if argv.exists() else []
    if received != ["--search=-x $(id)"]:
        run.ok = False
        print(f"the fake search helper received {received}, expected ['--search=-x $(id)']")
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
