pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Networking
import "kit"
import "kit/FoamyIpcResolver.js" as IpcResolver
import "kit/FoamyNative.js" as FoamyNative
import "Model.js" as Model
import "kit/FoamySchedule.js" as Schedule

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
// is asked in-process through the shell's IpcRegistry, where both the stock
// lock and foamy-lock answer "true" or "false". When no lock target answers,
// the session counts as unlocked.
QtObject {
  id: root

  readonly property string memberScope: "poller"
  readonly property bool active: FoamyShared.memberCount(memberScope) > 0
  // Someone has a train popup open on some monitor.
  readonly property bool demanded: FoamyShared.demandCount(memberScope) > 0
  // The native helper is bin/<arch>/foamy-train-helper under this directory.
  readonly property string pluginDir: FoamyNative.localPath(Qt.resolvedUrl("."))
  // No helper for this CPU (exit 126/127): say so once and stop fetching.
  property bool helperUnavailable: false

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
  property FoamyWallClock clock: FoamyWallClock {
    step: root.demanded ? 1000 : 60000
  }
  readonly property real nowEpoch: clock.date.getTime() / 1000
  // The schedule, or the popup's snooze/resume while it lasts (Schedule.toggled).
  // Outside it nothing is fetched in the background; an open popup still fetches.
  property var scheduleOverride: null
  readonly property bool withinSchedule: Schedule.effective(clock.date, scheduleEnabled, week, scheduleOverride)
  // Snoozed from the popup (not just outside the scheduled hours).
  readonly property bool snoozed: !withinSchedule && !!scheduleOverride && clock.date.getTime() < scheduleOverride.until
  // Someone is looking, or the schedule is in force: fetching is allowed.
  readonly property bool live: withinSchedule || demanded

  // Snoozing is kept beside the shell, never in shell.json, so it is not a setting.
  readonly property string stateHome: Quickshell.env("XDG_STATE_HOME") || Quickshell.env("HOME") + "/.local/state"
  property string overridePath: stateHome + "/foamy-train/schedule-override.json"
  property FileView overrideFile: FileView {
    path: root.overridePath
    atomicWrites: true
    printErrors: false
    onLoaded: root.scheduleOverride = Schedule.parseOverride(text(), Date.now())
    // The snooze still applies in memory, but a restart forgets it.
    onSaveFailed: function(error) {
      console.warn("foamy-train: couldn't save the snooze state to " + path + " (" + FileViewError.toString(error)
        + "); it lasts until the shell restarts")
    }
  }
  function toggleSnooze() {
    var now = new Date()
    scheduleOverride = Schedule.toggled(now, scheduleEnabled, week, scheduleOverride)
    clock.refresh()
    overrideFile.setText(Schedule.serializeOverride(scheduleOverride))
  }

  // --- network -------------------------------------------------------------------
  readonly property bool networkConnected: Networking.connectivity === NetworkConnectivity.Full
    || Networking.connectivity === NetworkConnectivity.Limited
  property bool networkSettled: false
  readonly property bool networkReady: networkConnected && networkSettled
  // Every (re)connection waits out the settle delay, not just the first.
  onNetworkConnectedChanged: networkSettled = false
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
  // A fetch started and not yet finished (exited, or failed to start).
  property bool inFlight: false
  // The fetch's outer deadline; the helper command follows it.
  property var deadline: ["timeout", "--kill-after=2s", "18s"]
  readonly property bool loading: statusProcess.running

  // --- session lock ----------------------------------------------------------------
  property bool sessionLocked: false
  // The last probe reached a lock target (false: none answers, so unlocked).
  property bool lockInProcess: false
  // While locked, only this cheap in-process probe ticks.
  readonly property int lockProbeSeconds: 10

  readonly property int pollInterval: Model.pollInterval(refreshSeconds, {
    open: demanded, locked: sessionLocked, lockSeconds: lockProbeSeconds, report: report, now: nowEpoch
  })
  readonly property bool stale: Model.stale(report, nowEpoch, !networkReady, Math.max(pollInterval, fetchInterval))
  readonly property var departures: Model.upcoming(report, nowEpoch, stale)
  readonly property var next: Model.next(departures)
  readonly property bool alert: withinSchedule && !stale && (departures.some(function(d) {
    return d.cancelled || d.delay > 0 || d.notices.some(function(n) { return n.kind === "warning" })
  }) || report.routeNotices.some(function(n) { return n.kind === "warning" }))
  readonly property bool canPoll: active && configured && !!route && networkReady && live && !helperUnavailable

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
    if (!networkReady || sessionLocked || !live || helperUnavailable || networkRetries >= 3) return
    // Bound startup recovery without overlapping the serialized worker.
    networkRetry.interval = 2500 * Math.pow(2, networkRetries++)
    networkRetry.restart()
  }

  // force skips the helper's 30 s cache; present means someone is at the
  // screen (popup opened, Refresh, IPC), so the lock probe is skipped.
  // Fetching is allowed: some bar shows the widget, a route is set and the
  // schedule is on or a popup is open. Checked again after every asynchronous step.
  function canFetch() {
    return active && configured && live && !!route && !helperUnavailable
  }

  function refresh(force, present) {
    if (!canFetch()) return
    if (statusProcess.running) {
      pendingRefresh = true
      pendingForce = pendingForce || force
      return
    }
    if (present || demanded) sessionLocked = false
    else if (lockAnswered(lockedInProcess())) return
    fetch(force)
  }

  // The lock target's answer through the shell's own IpcRegistry; false
  // when no lock target answers.
  function lockedInProcess() {
    var answer = IpcResolver.call(root, "lock", "isLocked", [])
    lockInProcess = answer.ran
    return answer.ran && String(answer.output).trim() === "true"
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

  function fetch(force) {
    if (!canFetch()) return
    requestedGeneration = generation
    requestOffline = !networkReady
    lastAttempt = Date.now() / 1000
    fetchInterval = pollInterval
    statusProcess.requestInput = JSON.stringify(route) + "\n"
    statusProcess.command = deadline.concat(FoamyNative.command(pluginDir, "foamy-train-helper",
      ["--language", language === "no" || language === "nb" ? "nb" : "en",
       "--hours", String(lookAheadHours), "--route-stdin"]
      .concat(force ? ["--force"] : []).concat(requestOffline ? ["--offline"] : [])))
    statusProcess.stdinEnabled = true
    inFlight = true
    statusProcess.running = true
    schedule()
  }

  // The one end of a fetch: exited, or never started (Quickshell then emits
  // no exited(), only running -> false). The running -> false that follows
  // exited() finds nothing in flight. Queued refreshes drain either way.
  function finishFetch(code, started) {
    if (!inFlight) return
    inFlight = false
    try {
      if (requestedGeneration !== generation) return
      if (started && FoamyNative.unavailable(code)) {
        helperFailed()
        return
      }
      if (!started || code !== 0) {
        fail("Train request failed. Try Refresh.")
        retryNetworkRequest()
        return
      }
      report = Model.parse(statusOutput.text)
      if (["network_error", "http_error"].indexOf(report.errorCode) >= 0) retryNetworkRequest()
      else resetNetworkRetry()
    } catch (e) {
      fail("Invalid train response.")
    } finally {
      Qt.callLater(root.drainRefresh)
    }
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

  // Exit 126/127: no helper binary for this CPU. Shown once; never retried.
  function helperFailed() {
    helperUnavailable = true
    resetNetworkRetry()
    pendingRefresh = false
    pollTimer.stop()
    fail(FoamyNative.UNAVAILABLE_TEXT)
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
      lockProbe: lockInProcess ? "in-process" : "none",
      pollSeconds: pollInterval, withinSchedule: withinSchedule, snoozed: snoozed, networkReady: networkReady
    }
  }

  onCanPollChanged: schedule()
  onPollIntervalChanged: schedule()
  onActiveChanged: if (!active) {
    generation++
    pendingRefresh = false
    pollTimer.stop()
    networkRetry.stop()
    statusProcess.running = false
  }
  onNetworkReadyChanged: if (configured) {
    resetNetworkRetry()
    generation++
    refresh(true, false)
  }
  onWithinScheduleChanged: if (configured && withinSchedule) {
    resetNetworkRetry()
    refresh(true, false)
  }
  // Outside the schedule with the last popup closed: cancel work and
  // invalidate any queued response. (An open popup keeps fetching.)
  onLiveChanged: if (configured && !live) {
    resetNetworkRetry()
    generation++
    pendingRefresh = false
    pendingForce = false
    statusProcess.running = false
  }
  onSessionLockedChanged: if (!sessionLocked) resetNetworkRetry()

  property Timer pollTimer: Timer {
    repeat: false
    onTriggered: root.refresh(false, false)
  }
  property Timer networkRetry: Timer {
    onTriggered: root.refresh(true, false)
  }

  property Process statusProcess: Process {
    objectName: "departureProcess"
    property string requestInput: ""
    onStarted: {
      write(requestInput)
      stdinEnabled = false
    }
    stdout: StdioCollector { id: statusOutput; waitForEnd: true }
    onExited: function(code) { root.finishFetch(code, true) }
    onRunningChanged: if (!running) root.finishFetch(-1, false)
  }
}
