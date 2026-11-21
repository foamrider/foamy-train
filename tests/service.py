#!/usr/bin/env python3
"""The real TrainService and helper offscreen on Omarchy 4.5 (foamy-kit
harness), with the network going down and up through the kit's fake
NetworkManager (preview/fake_nm.py) on the run's private system bus, and the
local fake Entur (tests/fake_entur.py) as the endpoint:

- a snooze saved in the state file is read at start;
- offline, only the cache is asked and Entur gets no request;
- when the network is ready the service fetches by itself (there is no lock
  target, so it does not wait for a lock answer), once per connection;
- offline again, the cached departures stay, marked stale;
- every reconnection waits out the network settle delay before it fetches;
- a snooze is written to the state file.

  python3 tests/service.py

Needs foamy-kit (FOAMY_KIT, default ~/GitHub/Personal/foamy-kit),
dbus-daemon, dbus-python and PyGObject. Temporary HOME/XDG dirs; nothing is
sent to Entur.
"""

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
import fake_nm
import harness
from fake_entur import API_PATH, ENDPOINT_ENV, ROUTE, FakeEntur, Reply, base_time, busy

PLUGIN = Path(__file__).resolve().parents[1]
# The shell logs these when a step is checked; main() then changes the network.
OFFLINE_CHECKED = "FOAMY OFFLINE CHECKED"
ONLINE_CHECKED = "FOAMY ONLINE CHECKED"
OFFLINE_AGAIN = "FOAMY OFFLINE AGAIN"

SHELL = r"""
import QtQuick
import Quickshell
import qs.Commons
import "harness"
import "plugin" as Train

ShellRoot {
  id: shell
  function check(ok, what) { console.log((ok ? "FOAMY OK " : "FOAMY FAIL ") + what) }
  MockBar { id: bar; moduleName: "foamy.train" }
  FloatingWindow {
    visible: true; implicitWidth: 120; implicitHeight: 40
    Train.Panel { id: panel; bar: bar; moduleName: "foamy.train"; settings: ({ route: ROUTE, refreshSeconds: 300 }); width: 100; height: 32 }
  }
  readonly property var s: Train.TrainService
  // networkReady right after each connection (after the service's own
  // handlers have run): false while the settle delay runs.
  property var readyAtConnect: []
  property int saves: 0
  Connections {
    target: Train.TrainService
    function onNetworkConnectedChanged() {
      if (shell.s.networkConnected)
        Qt.callLater(function() { shell.readyAtConnect = shell.readyAtConnect.concat([shell.s.networkReady]) })
    }
  }
  Connections {
    target: Train.TrainService.overrideFile
    function onSaved() { shell.saves++ }
  }
  FoamyWait { id: wait }
  // Runs `then` once `condition` holds; a timeout fails the run and ends it.
  function when(condition, label, then) {
    wait.waitFor(condition, 30000, function(ok) {
      if (ok) then()
      else Qt.quit()
    }, label)
  }
  function idle() { return !s.inFlight && !s.statusProcess.running && !s.pendingRefresh }
  Component.onCompleted: when(function() { return s.active && s.configured && s.snoozed && idle() }, "a saved snooze is read at start", step1)
  function step1() {
    IpcRegistry.call("foamy.train", "snooze", [])
    check(!s.snoozed && s.withinSchedule, "IPC snooze again resumes")
    IpcRegistry.call("foamy.train", "refresh", [])
    when(function() { return idle() && s.report.errorCode === "offline" }, "offline, only the cache is asked", function() {
      check(!s.networkReady && s.report.departures.length === 0, "offline with no cache: no departures, no network")
      console.log("FOAMY OFFLINE CHECKED")
      when(function() { return s.networkConnected }, "the network comes up", step2)
    })
  }
  function step2() {
    when(function() { return shell.readyAtConnect.length === 1 }, "the connection is recorded", function() {
      check(shell.readyAtConnect[0] === false, "the first connection waits out the settle delay")
      when(function() { return s.networkReady && idle() && s.report.status === "ok" && s.report.departures.length === 6 && !s.stale },
           "when the network is ready the service fetches by itself", function() {
        console.log("FOAMY ONLINE CHECKED")
        when(function() { return !s.networkConnected && idle() && s.report.errorCode === "offline" }, "the network goes down", step3)
      })
    })
  }
  function step3() {
    check(s.report.departures.length === 6 && s.stale, "offline again, the cached trains stay, marked stale: "
          + s.report.departures.length + " stale " + s.stale)
    console.log("FOAMY OFFLINE AGAIN")
    when(function() { return shell.readyAtConnect.length === 2 }, "the network comes up again", function() {
      check(shell.readyAtConnect[1] === false, "every reconnection waits out the settle delay")
      when(function() { return s.networkReady && idle() && s.report.status === "ok" && !s.stale }, "the second connection fetches", step4)
    })
  }
  function step4() {
    var before = shell.saves
    IpcRegistry.call("foamy.train", "snooze", [])
    check(s.snoozed, "IPC snooze mutes the widget")
    when(function() { return shell.saves > before }, "the snooze is written", function() {
      console.log("FOAMY DONE")
      Qt.quit()
    })
  }
}
"""


def main():
    entur = FakeEntur()
    # Seven direct trains: the short search window is enough, one request per fetch.
    entur.fallback[API_PATH] = Reply(busy(base_time(20)))
    shell = SHELL.replace("ROUTE", json.dumps(ROUTE))
    run = harness.Run("4.5", shell, plugin=PLUGIN, prefix="foamy-train-service-", system_bus="private")
    run.env[ENDPOINT_ENV] = entur.url
    snooze = run.base / "home/.local/state/foamy-train/schedule-override.json"
    snooze.parent.mkdir(parents=True, exist_ok=True)
    snooze.write_text(
        json.dumps({"version": 1, "override": {"on": False, "until": int(time.time() * 1000) + 3600_000}})
    )
    connectivity = run.base / "connectivity"
    fake_nm.set_connectivity(connectivity, fake_nm.NONE)
    problems = []
    # The fake goes on the bus before qs: Quickshell looks for NetworkManager
    # only once, at start.
    run.start_buses()
    try:
        with fake_nm.start(run.system_bus_address, connectivity):
            run.start()
            try:
                if run.wait_for_log(OFFLINE_CHECKED, timeout=60):
                    if entur.taken():
                        problems.append(f"offline, Entur got requests: {entur.taken()}")
                    fake_nm.set_connectivity(connectivity, fake_nm.FULL)
                    if run.wait_for_log(ONLINE_CHECKED, timeout=60):
                        fake_nm.set_connectivity(connectivity, fake_nm.NONE)
                        if run.wait_for_log(OFFLINE_AGAIN, timeout=60):
                            fake_nm.set_connectivity(connectivity, fake_nm.FULL)
                run.wait(60)
            finally:
                run.stop()
    finally:
        entur.close()
    # As harness.Run.run() decides it.
    run.ok = "FOAMY DONE" in run.log and not run.failures()
    # One request per connection, none while offline: the second one is
    # forced, since it comes within the helper's 30 s cache time.
    requests = len(entur.taken())
    if requests != 2:
        problems.append(f"expected one Entur request per connection (2), saw {requests}")
    try:
        override = json.loads(snooze.read_text())["override"]
    except (OSError, ValueError, KeyError) as error:
        override = None
        problems.append(f"the snooze file can't be read: {error}")
    if override is not None and not (override.get("on") is False and override.get("until", 0) > time.time() * 1000):
        problems.append(f"the snooze file holds no snooze: {override}")
    hosts = run.host_commands()
    if hosts:
        problems.append("host commands run: " + "; ".join(hosts))
    if problems:
        run.ok = False
    oks = run.log.count("FOAMY OK")
    if run.ok:
        print(f"4.5: {oks} checks passed")
        run.cleanup()
        return 0
    print(f"4.5: FAILED ({oks} ok)\n" + "\n".join(problems + (run.failures() or run.log.splitlines()[-30:])))
    print(f"log kept at {run.base}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
