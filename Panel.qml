import QtQuick
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "kit"
import "Preferences.js" as Schema
import "Schedule.js" as Schedule
import "Model.js" as Model

// One bar instance (4.5 draws one per monitor). Data, polling and the lock
// probe live in the TrainService singleton; the leader instance configures it
// and owns the IPC target. Every instance shows the bar countdown and its own
// popup, and any instance can save settings.
Panel {
  id: root
  ipcTarget: "foamy.train"
  manageIpc: false

  readonly property bool vertical: bar && (bar.position === "left" || bar.position === "right")
  readonly property color foreground: bar ? bar.barForeground : Commons.Color.foreground
  function preference(key) {
    return prefs.value(key)
  }
  // The station pair is an object field: Model.route() validates it.
  readonly property var fields: Schema.fields.concat([{
    key: "route", type: "object", defaultValue: null,
    validate: function(value) {
      try {
        return Model.route(value) !== null || "Select both stations from search results."
      } catch (error) {
        return error.message
      }
    }
  }])
  // Saved values show at once, before the host reflects them back.
  readonly property var effectiveSettings: prefs.effectiveSettings
  readonly property string configuredRoute: JSON.stringify(effectiveSettings && effectiveSettings.route !== undefined ? effectiveSettings.route : null)
  readonly property var config: ({
    routeJson: configuredRoute,
    lookAheadHours: preference("lookAheadHours"),
    refreshSeconds: preference("refreshSeconds"),
    scheduleEnabled: preference("scheduleEnabled"),
    week: Schedule.week(effectiveSettings || ({})),
    language: FoamyI18n.language
  })

  readonly property alias editingSettings: settingsState.editing
  readonly property string settingsError: prefs.error !== "" ? FoamyI18n.t(prefs.error) : ""
  readonly property bool saving: prefs.busy
  readonly property bool routeSaving: prefs.busy
  readonly property alias popup: popup

  FoamySettingsState { id: settingsState; panel: root }
  FoamyPrefsQueue {
    id: prefs
    bar: root.bar
    moduleName: root.moduleName
    fields: root.fields
    settings: root.settings
  }

  FoamyMember {
    id: member
    scope: TrainService.memberScope
    demanding: root.opened
    onIsLeaderChanged: root.pushConfig()
  }
  onConfigChanged: pushConfig()
  Component.onCompleted: pushConfig()
  function pushConfig() {
    if (member.isLeader) TrainService.configure(config)
  }

  visible: opened || TrainService.withinSchedule || preference("scheduleOutsideMode") !== "hide" || !TrainService.route
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  function openSettings() {
    settingsState.show()
  }
  function closeSettings() {
    settingsState.hide()
  }
  function swapDirection() {
    var current = TrainService.route
    if (current && !routeSaving) save("route", { from: current.to, to: current.from })
  }
  function save(key, next) {
    // Store the normalized pair (trimmed names, no search labels).
    if (key === "route") {
      try { next = Model.route(next) } catch (error) {}
    }
    prefs.save(key, next)
  }
  function retrySave() {
    prefs.retry()
  }

  onOpenedChanged: if (opened) TrainService.refresh(false, true)

  FoamyIpc {
    target: "foamy.train"
    enabled: member.isLeader
    function open(): void { root.open() }
    function close(): void { root.close() }
    function toggle(): void { root.toggle() }
    function settings(): void { root.openSettings() }
    function refresh(): void { TrainService.refresh(true, true) }
    function swap(): void { root.swapDirection() }
    function status(): string { return JSON.stringify(TrainService.statusObject()) }
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: ""
    labelVisible: false
    hasVisualContent: true
    active: TrainService.alert
    activeColor: Commons.Color.urgent
    dimmed: !TrainService.withinSchedule || TrainService.stale || !TrainService.next
    fixedWidth: root.vertical ? -1 : Math.max(Style.bar.iconSlot, barContent.implicitWidth + Style.bar.iconSlot - Style.bar.iconCanvas)
    tooltipText: FoamyI18n.t("Trains")
      + (TrainService.route ? " · " + FoamyI18n.t("%1 → %2", [TrainService.route.from.name, TrainService.route.to.name]) : "")
      + (TrainService.stale ? " · " + FoamyI18n.t("Cached times; live predictions unavailable.") : "")
    TrainBar {
      id: barContent
      anchors.centerIn: parent
      foreground: root.foreground
      iconFontFamily: button.fontFamily
      fontSize: button.fontSize
      showMinutes: root.preference("showBarMinutes")
      language: FoamyI18n.language
      withinSchedule: TrainService.withinSchedule
      vertical: root.vertical
      stale: TrainService.stale
      next: TrainService.next
      departures: TrainService.departures
      routeNotices: TrainService.report.routeNotices
      nowEpoch: TrainService.nowEpoch
    }
    onPressed: function(b) {
      if (b === Qt.RightButton) root.openSettings()
      else root.toggle()
    }
  }

  FoamyPopup {
    id: popup
    anchorItem: button
    bar: root.bar
    owner: root
    open: root.opened
    body: Component {
      TrainBody {
        report: TrainService.report
        nowEpoch: TrainService.nowEpoch
        stale: TrainService.stale
        departures: TrainService.departures
        next: TrainService.next
        language: FoamyI18n.language
        loading: TrainService.loading
        offline: !TrainService.networkReady
        outsideSchedule: !TrainService.withinSchedule
        route: TrainService.route
        settings: root.effectiveSettings
        helperPath: TrainService.helperPath
        editingSettings: root.editingSettings
        saving: root.saving
        routeSaving: root.routeSaving
        settingsError: root.settingsError
        retryable: prefs.canRetry
        onCloseRequestedByView: root.editingSettings ? root.closeSettings() : root.close()
        onSettingsRequested: root.openSettings()
        onSettingsClosed: root.closeSettings()
        onRefreshRequested: TrainService.refresh(true, true)
        onSwapRequested: root.swapDirection()
        onSaveRequested: function(key, value) { root.save(key, value) }
        onRetryRequested: root.retrySave()
        onSwitchPanelRequested: function(direction) { root.switchPanel(direction) }
      }
    }
  }
}
