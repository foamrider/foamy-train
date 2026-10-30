pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Networking
import "kit"
import "kit/FoamyIpcResolver.js" as IpcResolver
import "Model.js" as Model
import "Schedule.js" as Schedule

// The one Entur client per shell. 4.5 draws a bar per monitor, and a qmldir
// singleton is shared by every bar instance of this plugin, so the clock, the
// fetch helper, the lock probe and the poll timer exist once. The leader Panel
// (FoamyMember scope "poller") pushes its settings with configure(); every
// Panel reads report/nowEpoch/departures from here.
//
// Polling is adaptive (Model.pollInterval): the configured interval while a
// popup is open or the next train is within 30 minutes, 5 minutes when it is
// within 2 hours, 15 minutes otherwise. Nothing is fetched while the session
// is locked: before each unattended poll the public `lock isLocked` IPC target
// is asked (in-process through 4.5's IpcRegistry, else `omarchy-shell`), which
// both the stock lock and foamy-lock answer (see /tmp/foamy-fix/contracts.md).
QtObject {
  id: root

  readonly property string memberScope: "poller"
  readonly property bool active: FoamyShared.memberCount(memberScope) > 0
  // Someone has a train popup open on some monitor.
  readonly property bool demanded: FoamyShared.demandCount(memberScope) > 0
  readonly property string helperPath: decodeURIComponent(Qt.resolvedUrl("train_fetch.py").toString().replace(/^file:\/\//, ""))

  // --- configuration (from the leader Panel) -----------------------------------
  property bool configured: false
  property string configuredRoute: "null"
  property var route: null
  property int lookAheadHours: 24
  property int refreshSeconds: 60
  property bool scheduleEnabled: false
  property var week: ["", "", "", "", "", "", ""]
  property string language: "en"

  // --- clock: whole minutes while every popup is closed (the bar shows minutes) ---
  property SystemClock clock: SystemClock {
    precision: root.demanded ? SystemClock.Seconds : SystemClock.Minutes
  }
  readonly property real nowEpoch: clock.date.getTime() / 1000
  readonly property bool withinSchedule: Schedule.withinWeek(clock.date, scheduleEnabled, week)

  // --- network -------------------------------------------------------------------
  readonly property bool networkConnected: Networking.connectivity === NetworkConnectivity.Full
    || Networking.connectivity === NetworkConnectivity.Limited
  property bool networkSettled: false
  readonly property bool networkReady: networkConnected && networkSettled
  // NetworkManager can report a connection before DNS and routes are usable.
  property Timer settleTimer: Timer {
    interval: 2000
    running: root.networkConnected && !root.networkSettled
    onTriggered: root.networkSettled = true
  }

  // --- departures ----------------------------------------------------------------
  property var report: Model.blank("loading")
  property int generation: 0
  property int requestedGeneration: 0
  property bool pendingRefresh: false
  property bool pendingForce: false
  property bool requestOffline: false
  property int networkRetries: 0
  property real lastAttempt: 0
  // The poll interval in force when the shown data was requested.
  property int fetchInterval: 60
  readonly property bool loading: statusProcess.running

  // --- session lock ----------------------------------------------------------------
  property bool sessionLocked: false
  property bool lockInProcess: false
  property bool lockProbeAvailable: true
  property int lockProbeFailures: 0
  property bool lockForce: false
  readonly property int lockProbeSeconds: lockInProcess ? 10 : 60

  readonly property int pollInterval: Model.pollInterval(refreshSeconds, {
    open: demanded, locked: sessionLocked, lockSeconds: lockProbeSeconds, report: report, now: nowEpoch
  })
  readonly property bool stale: Model.stale(report, nowEpoch, !networkReady, Math.max(pollInterval, fetchInterval))
  readonly property var departures: Model.upcoming(report, nowEpoch, stale)
  readonly property var next: Model.next(departures)
  readonly property bool alert: withinSchedule && !stale && (departures.some(function(d) {
    return d.cancelled || d.delay > 0 || d.notices.some(function(n) { return n.kind === "warning" })
  }) || report.routeNotices.some(function(n) { return n.kind === "warning" }))
  readonly property bool canPoll: active && configured && !!route && networkReady && withinSchedule

  function configure(config) {
    var reset = !configured || config.routeJson !== configuredRoute || config.lookAheadHours !== lookAheadHours
    var relabel = configured && config.language !== language
    refreshSeconds = config.refreshSeconds
    scheduleEnabled = config.scheduleEnabled
    week = config.week
    lookAheadHours = config.lookAheadHours
    language = config.language
    configuredRoute = config.routeJson
    configured = true
    if (reset) syncRoute()
    else if (relabel) {
      generation++
      refresh(true, false)
    }
    schedule()
  }

  function syncRoute() {
    resetNetworkRetry()
    // shell.json is authoritative; discard results for a route that was replaced.
    generation++
    statusProcess.running = false
    pendingRefresh = false
    pendingForce = false
    try {
      var parsed = Model.route(JSON.parse(configuredRoute))
      report = Object.assign(Model.blank(parsed ? "ready" : "unconfigured"), { route: parsed })
    } catch (error) {
      report = Object.assign(Model.blank("error"), { error: error.message })
    }
    route = report.route
    if (route) refresh(true, false)
  }

  function resetNetworkRetry() {
    networkRetry.stop()
    networkRetries = 0
  }

  function retryNetworkRequest() {
    if (!networkReady || sessionLocked || !withinSchedule || networkRetries >= 3) return
    // Bound startup recovery without overlapping the serialized worker.
    networkRetry.interval = 2500 * Math.pow(2, networkRetries++)
    networkRetry.restart()
  }

  // force skips the helper's 30 s cache; present means someone is at the
  // screen (popup opened, Refresh, IPC), so the lock probe is skipped.
  function refresh(force, present) {
    if (!active || !configured || !withinSchedule || !route) return
    if (statusProcess.running || lockProcess.running) {
      pendingRefresh = true
      pendingForce = pendingForce || force
      return
    }
    if (present || demanded) {
      sessionLocked = false
    } else if (lockProbeAvailable) {
      var locked = lockedInProcess()
      if (locked === null) {
        lockForce = force
        lockProcess.running = true
        return
      }
      if (lockAnswered(locked)) return
    }
    fetch(force)
  }

  // true/false from the shell's own IpcRegistry (4.5), or null when it can't tell.
  function lockedInProcess() {
    var registry = IpcResolver.registry(root)
    if (!registry || typeof registry.call !== "function") return null
    var answer = registry.call("lock", "isLocked", [])
    if (!answer || !answer.ran) return null
    lockInProcess = true
    return String(answer.output).trim() === "true"
  }

  // Records the lock state; true when the poll must wait.
  function lockAnswered(locked) {
    sessionLocked = locked
    if (!locked) return false
    resetNetworkRetry()
    lastAttempt = Date.now() / 1000
    schedule()
    return true
  }

  function lockProbeFailed() {
    // No lock service answers: stop asking after a few tries and poll as usual.
    if (++lockProbeFailures >= 3) lockProbeAvailable = false
    sessionLocked = false
  }

  function fetch(force) {
    requestedGeneration = generation
    requestOffline = !networkReady
    lastAttempt = Date.now() / 1000
    fetchInterval = pollInterval
    statusProcess.requestInput = JSON.stringify(route) + "\n"
    statusProcess.command = ["timeout", "--kill-after=2s", "18s", "python3", helperPath,
      "--language", language === "no" || language === "nb" ? "nb" : "en",
      "--hours", String(lookAheadHours), "--route-stdin"]
      .concat(force ? ["--force"] : []).concat(requestOffline ? ["--offline"] : [])
    statusProcess.stdinEnabled = true
    statusProcess.running = true
    schedule()
  }

  function schedule() {
    if (!canPoll) {
      pollTimer.stop()
      return
    }
    var wait = Math.max(1, lastAttempt + pollInterval - Date.now() / 1000)
    pollTimer.interval = Math.round(wait * 1000)
    pollTimer.restart()
  }

  function fail(message) {
    var updated = Object.assign({}, report)
    updated.status = report.updatedAt ? "stale" : "error"
    updated.stale = !!report.updatedAt
    updated.error = message
    report = updated
  }

  function drainRefresh() {
    if (!pendingRefresh) return
    var force = pendingForce
    pendingRefresh = false
    pendingForce = false
    refresh(force, false)
  }

  function statusObject() {
    return {
      status: report.status, departures: departures.length, stale: stale, locked: sessionLocked,
      lockProbe: !lockProbeAvailable ? "off" : lockInProcess ? "in-process" : "omarchy-shell",
      pollSeconds: pollInterval, withinSchedule: withinSchedule, networkReady: networkReady
    }
  }

  onCanPollChanged: schedule()
  onPollIntervalChanged: schedule()
  onActiveChanged: if (!active) {
    pollTimer.stop()
    networkRetry.stop()
    statusProcess.running = false
  }
  onNetworkReadyChanged: if (configured) {
    resetNetworkRetry()
    generation++
    refresh(true, false)
  }
  onWithinScheduleChanged: {
    if (!configured) return
    resetNetworkRetry()
    // Leaving the schedule cancels work and invalidates any queued response.
    generation++
    pendingRefresh = false
    pendingForce = false
    if (withinSchedule) refresh(true, false)
    else statusProcess.running = false
  }
  onSessionLockedChanged: if (!sessionLocked) resetNetworkRetry()

  property Timer pollTimer: Timer {
    repeat: false
    onTriggered: root.refresh(false, false)
  }
  property Timer networkRetry: Timer {
    onTriggered: root.refresh(true, false)
  }

  property Process lockProcess: Process {
    command: ["timeout", "--kill-after=1s", "3s", "omarchy-shell", "lock", "isLocked"]
    stdout: StdioCollector { id: lockOutput; waitForEnd: true }
    onExited: function(code) {
      var answer = lockOutput.text.trim()
      if (code === 0 && (answer === "true" || answer === "false")) {
        root.lockProbeFailures = 0
        if (!root.lockAnswered(answer === "true")) root.fetch(root.lockForce)
      } else {
        root.lockProbeFailed()
        root.fetch(root.lockForce)
      }
      Qt.callLater(root.drainRefresh)
    }
  }

  property Process statusProcess: Process {
    objectName: "departureProcess"
    property string requestInput: ""
    onStarted: {
      write(requestInput)
      stdinEnabled = false
    }
    stdout: StdioCollector { id: statusOutput; waitForEnd: true }
    onExited: function(code) {
      try {
        if (root.requestedGeneration !== root.generation) return
        if (code !== 0) {
          root.fail("Train request failed. Try Refresh.")
          root.retryNetworkRequest()
          return
        }
        root.report = Model.parse(statusOutput.text)
        if (["network_error", "http_error"].indexOf(root.report.errorCode) >= 0) root.retryNetworkRequest()
        else root.resetNetworkRetry()
      } catch (e) {
        root.fail("Invalid train response.")
      } finally {
        Qt.callLater(root.drainRefresh)
      }
    }
  }
}
