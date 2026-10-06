import QtQuick
import QtQuick.Controls as Controls
import Quickshell
import Quickshell.Io
import Quickshell.Networking
import qs.Commons
import qs.Ui
import "Preferences.js" as Preferences
import "Schedule.js" as Schedule
import "Model.js" as Model

Panel {
  id: root
  moduleName: "foamy.train"
  ipcTarget: "foamy.train"
  manageIpc: false
  readonly property bool vertical: bar && (bar.position === "left" || bar.position === "right")
  readonly property color foreground: bar ? bar.barForeground : Color.foreground
  readonly property string helperPath: decodeURIComponent(Qt.resolvedUrl("train_fetch.py").toString().replace(
                                                            /^file:\/\//, ""))
  readonly property var lockService: bar?.shell?.firstPartyServiceFor("omarchy.lock")
  readonly property bool sessionLocked: lockService ? lockService.locked === true : false
  readonly property bool networkConnected: Networking.connectivity === NetworkConnectivity.Full
    || Networking.connectivity === NetworkConnectivity.Limited
  property bool networkSettled: false
  readonly property bool networkReady: networkConnected && networkSettled
  onNetworkConnectedChanged: networkSettled = false
  Timer {
    // NetworkManager can report a connection before DNS and routes are usable.
    interval: 2000
    running: root.networkConnected && !root.networkSettled
    onTriggered: root.networkSettled = true
  }
  function preference(key) {
    return Preferences.value(settings, key)
  }
  readonly property int lookAheadHours: preference("lookAheadHours")
  onLookAheadHoursChanged: if (initialized) syncRoute()
  readonly property string language: Preferences.language(preference("language"), Qt.locale().name)
  function tr(s) {
    return Preferences.text(s, language)
  }
  property var report: Model.blank("loading")
  property bool initialized: false
  property bool editingSettings: false
  property string settingsError: ""
  property var pendingPreferences: ({})
  property bool routeSaving: false
  property string savingKey: ""
  readonly property string configuredRoute: JSON.stringify(settings.route === undefined ? null : settings.route)
  onConfiguredRouteChanged: if (initialized) syncRoute()
  Component.onCompleted: { initialized = true; syncRoute() }
  function syncRoute() {
    resetNetworkRetry()
    // shell.json is authoritative; discard results for a route that was replaced externally.
    generation++
    statusProcess.running = false
    pendingRefresh = false
    pendingForce = false
    try {
      var route = Model.route(settings.route)
      report = Object.assign(Model.blank(route ? "ready" : "unconfigured"), {route:route})
    } catch (error) {
      report = Object.assign(Model.blank("error"), {error:error.message})
    }
    settingsPane.resetRoute()
    if (report.route) refresh(true)
  }
  property int generation: 0
  property int requestedGeneration: 0
  property bool pendingRefresh: false
  property bool pendingForce: false
  property bool requestOffline: false
  property int networkRetries: 0
  function resetNetworkRetry() {
    networkRetry.stop()
    networkRetries = 0
  }
  function retryNetworkRequest() {
    if (!networkReady || sessionLocked || !withinSchedule || networkRetries >= 3) return
    // Bound startup recovery without overlapping the existing serialized worker.
    networkRetry.interval = 2500 * Math.pow(2, networkRetries++)
    networkRetry.restart()
  }
  Timer {
    id: networkRetry
    onTriggered: root.refresh(true)
  }
  SystemClock {
    id: clock
    precision: SystemClock.Seconds
  }
  readonly property real nowEpoch: clock.date.getTime() / 1000
  readonly property bool withinSchedule: Schedule.withinWeek(clock.date, preference("scheduleEnabled"), Schedule.week(
                                                               settings))

  readonly property bool stale: Model.stale(report, nowEpoch, !networkReady)
  readonly property var departures: Model.upcoming(report, nowEpoch, stale)
  readonly property var next: Model.next(departures)
  readonly property bool alert: withinSchedule && !stale && (departures.some(function (d) {
    return d.cancelled || d.delay > 0 || d.notices.some(function (n) {
      return n.kind === "warning"
    })
  }) || report.routeNotices.some(function (n) {
    return n.kind === "warning"
  }))
  visible: opened || withinSchedule || preference("scheduleOutsideMode") !== "hide" || !report.route
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  function savePreference(key, value) {
    if (!Preferences.valid(key, value)) {
      settingsError = tr("Invalid setting.")
      return
    }
    settingsError = ""
    pendingPreferences[key] = value
    flushPreferences()
  }
  function flushPreferences() {
    if (preferencesSave.running)
      return
    var keys = Object.keys(pendingPreferences)
    if (!keys.length)
      return
    var key = keys[0], value = pendingPreferences[key]
    delete pendingPreferences[key]
    savingKey = key
    preferencesSave.command = ["omarchy-shell", "shell", "setBarWidget", moduleName, key, " " + JSON.stringify(value),
                               "{}"]
    preferencesSave.running = true
  }
  function openSettings() {
    editingSettings = true
    settingsPane.resetRoute()
    open()
    panelScroll.contentY = 0
    Qt.callLater(function () {
      settingsPane.focusBack()
    })
  }
  function closeSettings() {
    editingSettings = false
    panelScroll.contentY = 0
    Qt.callLater(function () {
      view.settingsTarget.forceActiveFocus()
    })
  }
  function changeRoute(route) {
    if (routeSaving) return
    settingsError = ""
    try {
      var nextRoute = Model.route(route || (report.route ? {from:report.route.to,to:report.route.from} : null))
      if (!nextRoute) return
      generation++
      // Persist both endpoints in one shell setting and serialize with other preference writes.
      routeSaving = true
      pendingPreferences.route = nextRoute
      flushPreferences()
    } catch (error) {settingsError = tr(error.message)}
  }
  function refresh(force) {
    if (!initialized || sessionLocked || !withinSchedule || !report.route)
      return
    if (statusProcess.running || root.routeSaving) {
      pendingRefresh = true
      pendingForce = pendingForce || force
      return
    }
    requestedGeneration = generation
    requestOffline = !networkReady
    statusProcess.command = ["timeout", "--kill-after=2s", "18s", "python3", helperPath, "--language", language, "--hours", String(lookAheadHours), "--route", JSON.stringify(report.route)].concat(force
                                                                                                                        ? ["--force"] :
                                                                                                                          []).concat(
          requestOffline ? ["--offline"] : [])
    statusProcess.running = true
  }
  function fail(message) {
    var updated = Object.assign({}, report)
    updated.status = report.updatedAt ? "stale" : "error"
    updated.stale = !!report.updatedAt
    updated.error = message
    report = updated
  }
  function drainRefresh() {
    if (pendingRefresh) {
      var force = pendingForce
      pendingRefresh = false
      pendingForce = false
      refresh(force)
    }
  }
  Process {
    id: preferencesSave
    stdout: StdioCollector {
      id: saveOutput
      waitForEnd: true
    }
    onExited: function (code) {
      if (code !== 0 || saveOutput.text.trim() !== "ok")
        root.settingsError = root.tr("Could not save settings.")
      if (root.savingKey === "route") root.routeSaving = false
      Qt.callLater(root.flushPreferences)
      Qt.callLater(root.drainRefresh)
    }
  }
  Process {
    id: statusProcess
    objectName: "departureProcess"
    stdout: StdioCollector {
      id: statusOutput
      waitForEnd: true
    }
    onExited: function (code) {
      try {
        if (root.requestedGeneration !== root.generation)
          return
        if (code !== 0) {
          root.fail("Train request failed. Try Refresh.")
          root.retryNetworkRequest()
          return
        }
        root.report = Model.parse(statusOutput.text)
        if (["network_error", "http_error"].indexOf(root.report.errorCode) >= 0)
          root.retryNetworkRequest()
        else root.resetNetworkRetry()
      } catch (e) {
        root.fail("Invalid train response.")
      } finally {
        Qt.callLater(root.drainRefresh)
      }
    }
  }
  Timer {
    interval: root.preference("refreshSeconds") * 1000
    running: root.initialized && root.networkReady && !root.sessionLocked && root.withinSchedule
    repeat: true
    onTriggered: root.refresh(false)
  }
  onNetworkReadyChanged: if (initialized) {
                           resetNetworkRetry()
                           generation++
                           refresh(true)
                         }
  onLanguageChanged: if (initialized) {
                       generation++
                       refresh(true)
                     }
  onWithinScheduleChanged: {
    if (!initialized) return
    resetNetworkRetry()
    // Leaving the schedule cancels work and invalidates any already queued response.
    generation++
    pendingRefresh = false
    pendingForce = false
    if (withinSchedule) refresh(true)
    else statusProcess.running = false
  }
  onSessionLockedChanged: {
    resetNetworkRetry()
    if (initialized && !sessionLocked) refresh(false)
  }
  onOpenedChanged: {
    panelScroll.contentY = 0
    if (!opened)
      editingSettings = false
    else {
      refresh(false)
      Qt.callLater(function () {
        if (!root.editingSettings)
          panelScroll.forceActiveFocus()
      })
    }
  }
  IpcHandler {
    target: "foamy.train"
    function open(): void {
    root.open()
  }
    function close(): void {
                        root.close()
                      }
    function toggle(): void {
    root.toggle()
  }
    function settings(): void {
                           root.openSettings()
                         }
    function refresh(): void {
    root.refresh(true)
  }
    function swap(): void {
                       if (root.report.route)
                       root.changeRoute(null)
                     }
  }
  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: ""
    labelVisible: false
    hasVisualContent: true
    active: root.alert
    activeColor: Color.urgent
    dimmed: !root.withinSchedule || root.stale || !root.next
    fixedWidth: root.vertical ? -1 : Math.max(Style.bar.iconSlot, barContent.implicitWidth + Style.bar.iconSlot
                                              - Style.bar.iconCanvas)
    tooltipText: root.tr("Trains") + (root.report.route ? " · " + root.report.route.from.name + " → "
                                                          + root.report.route.to.name : "") + (root.stale ? " · "
                                                                                                            + root.tr(
                                                                                                              "Cached times; live predictions unavailable.") :
                                                                                                            "")
    TrainBar {
      id: barContent
      anchors.centerIn: parent
      foreground: root.foreground
      iconFontFamily: button.fontFamily
      fontSize: button.fontSize
      showMinutes: root.preference("showBarMinutes")
      language: root.language
      withinSchedule: root.withinSchedule
      vertical: root.vertical
      stale: root.stale
      next: root.next
      departures: root.departures
      routeNotices: root.report.routeNotices
      nowEpoch: root.nowEpoch
    }
    onPressed: function (b) {
      if (b === Qt.RightButton)
        root.openSettings()
      else
        root.toggle()
    }
  }
  TrainPopup {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: root.editingSettings ? settingsPane.backTarget : panelScroll
    padding: 0
    borderSpec: Border.flat(Qt.alpha(Color.popups.text, 0.15), 1)
    contentWidth: panel.fittedContentWidth(Style.space(480))
    contentHeight: panel.fittedContentHeight(Math.min(Style.space(820), root.editingSettings
                                                      ? settingsPane.implicitHeight : view.implicitHeight))
    Flickable {
      id: panelScroll
      anchors.fill: parent
      clip: true
      contentWidth: width
      contentHeight: root.editingSettings ? settingsPane.implicitHeight : view.implicitHeight
      boundsBehavior: Flickable.StopAtBounds
      flickableDirection: Flickable.VerticalFlick
      onContentHeightChanged: contentY = Math.max(0, Math.min(contentY, contentHeight - height))
      onHeightChanged: contentY = Math.max(0, Math.min(contentY, contentHeight - height))
      Keys.onEscapePressed: root.editingSettings ? root.closeSettings() : root.close()
      Keys.onPressed: function (event) {
        if (!root.editingSettings && event.key === Qt.Key_R) {
          root.refresh(true)
          event.accepted = true
        }
      }
      Connections {
        target: panelScroll.Window.window
        function onActiveFocusItemChanged() {
          var item = target.activeFocusItem
          if (!item)
            return
          var point = item.mapToItem(panelScroll.contentItem, 0, 0)
          if (point.y < panelScroll.contentY)
            panelScroll.contentY = Math.max(0, point.y - Style.space(8))
          else if (point.y + item.height > panelScroll.contentY + panelScroll.height)
            panelScroll.contentY = Math.max(0, Math.min(panelScroll.contentHeight - panelScroll.height, point.y + item.height
                                                        - panelScroll.height + Style.space(8)))
        }
      }
      Controls.ScrollBar.vertical: Controls.ScrollBar {
        policy: Controls.ScrollBar.AsNeeded
      }
      SettingsPane {
        id: settingsPane
        visible: root.editingSettings
        width: panelScroll.width
        route: root.report.route
        settings: root.settings
        language: root.language
        helperPath: root.helperPath
        saving: preferencesSave.running
        routeSaving: root.routeSaving
        error: root.settingsError
        onSave: function (key, value) {
          root.savePreference(key, value)
        }
        onApplyRoute: function (route) {
          root.changeRoute(route)
        }
        onClearError: root.settingsError = ""
        onBack: root.closeSettings()
      }
      TrainView {
        id: view
        cornerRadius: Math.max(0, panel.cornerRadius - Border.top(panel.borderSpec))
        visible: !root.editingSettings
        width: panelScroll.width
        report: root.report
        nowEpoch: root.nowEpoch
        language: root.language
        loading: statusProcess.running
        offline: !root.networkReady
        outsideSchedule: !root.withinSchedule
        routeBusy: root.routeSaving
        onSettingsRequested: root.openSettings()
        onSwapRequested: root.changeRoute(null)
        onRefreshRequested: root.refresh(true)
      }
    }
  }
}
