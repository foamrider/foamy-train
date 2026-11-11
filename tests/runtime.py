#!/usr/bin/env python3
"""Offscreen runtime checks on Omarchy 4.5 (the installed shell, or
FOAMY_HOST_45; 4.0 too when FOAMY_HOST_40 names a 4.0 shell tree):
two bar instances share one TrainService (leader configures it), the 4.5
in-process `lock isLocked` probe pauses polling while locked, the route
reaches the helper on stdin (never argv), popup demand switches the clock
to seconds, settings saves keep the route, invalid values are refused, outside the
schedule the popup still shows departures, and snoozing mutes the widget
until tomorrow without saving settings (an open popup still fetches).

Uses the foamy-kit preview harness (temp HOME/XDG, no Wayland/Hyprland, no
host scripts): FOAMY_KIT=/path/to/foamy-kit (default ~/GitHub/Personal/foamy-kit).
The system bus is a dead address, so NetworkManager is invisible and the
helper runs in offline mode; its Entur endpoint is also overridden with a
non-loopback URL, which fails every request without connecting. Entur is
never contacted.
  python3 tests/runtime.py [4.0|4.5|both]   (default both: 4.0 prints SKIP
                                            unless FOAMY_HOST_40 is set)
"""
import os
import sys
from pathlib import Path

KIT = Path(os.environ.get("FOAMY_KIT", Path.home() / "GitHub/Personal/foamy-kit"))
# 4.5 is the installed shell (FOAMY_HOST_45 overrides it); 4.0 runs only when
# FOAMY_HOST_40 names a 4.0 shell tree. Set before the harness reads them.
os.environ.setdefault("FOAMY_HOST_45", "/usr/share/omarchy/shell")
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
import "plugin/kit"
import "plugin/kit/FoamyNative.js" as FoamyNative
import "plugin" as Train
import "plugin/tests/Fixtures.js" as Fixtures

ShellRoot {
  id: shell
  property bool locked: true
  property var route: ({ from: { id: "NSR:StopPlace:59872", name: "Oslo S" }, to: { id: "NSR:StopPlace:62339", name: "Lillestrøm" } })
  property var entry: ({ route: shell.route, refreshSeconds: 300 })
  property int step: 0
  property int savedCount: 0
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
  // Station search whose process can't start (no such deadline command):
  // `searching` still clears and the failure shows. Then a helper that
  // isn't there (bash exits 127): the usual unavailable message.
  FloatingWindow {
    visible: true; implicitWidth: 320; implicitHeight: 120
    Train.StationSearch { id: search; width: 300; label: "From"; pluginDir: "/nonexistent/foamy-train" }
  }
  function startSearch(text) {
    search.input.text = text
    search.searching = true
    search.runSearch()
  }
  Timer {
    interval: 400; repeat: true; running: true
    onTriggered: {
      var s = Train.TrainService
      switch (shell.step++) {
      case 0:
        check(s.active && s.configured, "service active and configured by the leader")
        check(s.refreshSeconds === 300 && s.route && s.route.from.name === "Oslo S", "leader pushed its settings")
        check(s.clock.step === 60000, "minute clock while every popup is closed")
        s.statusProcess.running = false
        search.deadline = ["/nonexistent/foamy-no-such-command"]
        shell.startSearch("Oslo")
        break
      case 1:
        check(!search.searching && !search.inFlight, "a search that can't start stops searching")
        check(search.error === "Station search failed. Try again.", "and says it failed: " + search.error)
        search.deadline = ["timeout", "--kill-after=2s", "18s"]
        shell.startSearch("Bergen")
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
        if (search.inFlight) { shell.step--; break }
        check(!search.searching && search.error === FoamyNative.UNAVAILABLE_TEXT, "the next search runs and finishes: " + search.error)
        if (s.loading) { shell.step--; break }
        s.refresh(false, false)
        check(!s.sessionLocked, "unlocked session polls again")
        check(s.statusProcess.running || s.lockProbing, "a request starts after unlock")
        break
      case 3:
        if (s.loading || s.lockProbing) { shell.step--; break }
        var argv = s.statusProcess.command.join(" ")
        check(argv.indexOf("--route-stdin") >= 0 && argv.indexOf("NSR:") < 0 && argv.indexOf("Oslo") < 0, "route is not in argv")
        check(argv.indexOf("timeout --kill-after=2s 18s bash -c") === 0 && argv.indexOf("foamy-train-helper") >= 0, "the native helper runs under the widget timeout")
        check(s.report.route && s.report.route.to.name === "Lillestrøm", "helper received the route on stdin (" + s.report.status + "/" + s.report.errorCode + ")")
        check(s.report.errorCode === "offline", "sandbox fetch is offline (no network)")
        check(!s.networkConnected, "the service sees no network connection (system bus isolated)")
        a.open()
        break
      case 4:
        check(s.demanded && s.clock.step === 1000, "open popup raises demand and second precision")
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
        break
      case 6:
        var view = body.scroller.contentItem.children[0]
        var band = null, details = null
        for (var i = 0; i < view.children.length; i++) {
          if (view.children[i].objectName === "heroBand") band = view.children[i]
          if (view.children[i].objectName === "departureDetails") details = view.children[i]
        }
        check(band && band.meta.indexOf(" · outside your schedule") > 0, "outside the schedule the header says so: " + (band ? band.meta : "?"))
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
        break
      case 7:
        check(s.live && s.canFetch(), "an open popup still fetches while snoozed")
        a.close()
        break
      case 8:
        check(!s.live && !s.canFetch(), "closing the popup stops fetching again")
        s.toggleSnooze()
        check(s.withinSchedule && !s.snoozed && s.scheduleOverride === null, "pressing again resumes the schedule")
        check(bar.saved.length === shell.savedCount, "resuming never saves settings")
        // A departure request that can't start (no such deadline command):
        // Quickshell emits no exited(), only running -> false. The request
        // still ends: the failure shows and the refresh queued behind it runs.
        s.deadline = ["/nonexistent/foamy-no-such-command"]
        s.refresh(true, true)
        s.refresh(true, true)
        check(s.inFlight && s.pendingRefresh, "a second refresh queues behind the first")
        break
      case 9:
        if (s.inFlight || s.pendingRefresh) { shell.step--; break }
        check(!s.loading && s.report.error === "Train request failed. Try Refresh.",
              "a request that can't start fails visibly: " + s.report.status + "/" + s.report.error)
        s.deadline = ["timeout", "--kill-after=2s", "18s"]
        s.refresh(true, true)
        break
      case 10:
        if (s.inFlight) { shell.step--; break }
        check(s.report.errorCode === "offline" && s.report.error !== "Train request failed. Try Refresh.",
              "the next request runs normally: " + s.report.errorCode)
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
        if host == "4.0" and not os.environ.get("FOAMY_HOST_40"):
            print("4.0: SKIP (set FOAMY_HOST_40 to a 4.0 shell tree to run it)")
            continue
        qml = SHELL.replace("LOCK", LOCK_45 if host == "4.5" else "").replace("HOST", '"%s"' % host)
        # A stand-in, so the omarchy-shell lock probe (4.0) never reaches a real shell.
        run = harness.Run(host, qml, plugin=PLUGIN, prefix="foamy-train-runtime-",
                          fakebin={"omarchy-shell": "#!/bin/sh\nexit 1\n"})
        # The harness gives qs a private session bus only. On the system bus
        # NetworkManager reports the real connection, and two seconds later
        # the service would ask Entur for real departures. A dead system bus
        # keeps it offline; the non-loopback endpoint override makes any
        # request that still goes out fail before it connects.
        run.env["DBUS_SYSTEM_BUS_ADDRESS"] = f"unix:path={run.base}/no-system-bus"
        run.env["FOAMY_TRAIN_ENTUR_URL"] = "http://entur.invalid"
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
