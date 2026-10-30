import QtQuick
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "kit"
import "kit/FoamyPrefs.js" as Prefs
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
    return Prefs.value(Schema.fields, settings, key)
  }
  readonly property string configuredRoute: JSON.stringify(settings && settings.route !== undefined ? settings.route : null)
  readonly property var config: ({
    routeJson: configuredRoute,
    lookAheadHours: preference("lookAheadHours"),
    refreshSeconds: preference("refreshSeconds"),
    scheduleEnabled: preference("scheduleEnabled"),
    week: Schedule.week(settings || ({})),
    language: FoamyI18n.language
  })

  property bool editingSettings: false
  property string settingsError: ""
  property var lastSave: null
  property var queuedSaves: []
  property string savingKey: ""
  readonly property bool saving: saveProcess.running
  readonly property bool routeSaving: saveProcess.running && savingKey === "route"
  readonly property alias popup: popup

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
    editingSettings = true
    open()
  }
  function closeSettings() {
    editingSettings = false
  }
  function swapDirection() {
    var current = TrainService.route
    if (current && !routeSaving) save("route", { from: current.to, to: current.from })
  }

  // The station pair is an object, which FoamyPrefs' schema types don't
  // cover: validate it with Model.route() and save it the same way (inline
  // first, else `omarchy bar set … --json`).
  function routeSave(next) {
    var result = { ok: false, changed: false, inline: false, command: [], settings: null, error: "" }
    if (!root.moduleName) {
      result.error = "Settings can't be saved: this widget has no bar entry."
      return result
    }
    try {
      next = Model.route(next)
    } catch (error) {
      result.error = error.message
      return result
    }
    if (!next) {
      result.error = "Select both stations from search results."
      return result
    }
    result.settings = Prefs.merged(root.settings, "route", next)
    result.ok = true
    if (JSON.stringify(root.settings ? root.settings.route : null) === JSON.stringify(next)) return result
    result.changed = true
    if (Prefs.canSaveInline(root.bar)) {
      try {
        if (root.bar.shell.updateEntryInline(String(root.moduleName), result.settings) === true) {
          result.inline = true
          return result
        }
      } catch (error) {
        console.warn("foamy.train: inline save failed, using omarchy bar set:", error)
      }
    }
    result.command = Prefs.saveCommand(root.moduleName, "route", next)
    return result
  }

  function save(key, next) {
    settingsError = ""
    lastSave = { key: key, value: next }
    var result = key === "route" ? routeSave(next) : Prefs.save(root.bar, root.moduleName, Schema.fields, root.settings, key, next)
    if (!result.ok) {
      settingsError = FoamyI18n.t(result.error)
      return
    }
    if (result.command.length === 0) {
      lastSave = null
      return
    }
    queuedSaves = queuedSaves.concat([{ key: key, command: result.command }])
    flushSaves()
  }
  function retrySave() {
    if (lastSave) save(lastSave.key, lastSave.value)
  }
  // CLI saves run one at a time, in order.
  function flushSaves() {
    if (saveProcess.running || queuedSaves.length === 0) return
    var nextSave = queuedSaves[0]
    queuedSaves = queuedSaves.slice(1)
    savingKey = nextSave.key
    saveProcess.command = nextSave.command
    saveProcess.running = true
  }

  Process {
    id: saveProcess
    onExited: function(code) {
      if (code !== 0) root.settingsError = FoamyI18n.t("Couldn't save the setting.")
      else if (root.queuedSaves.length === 0) root.lastSave = null
      root.savingKey = ""
      Qt.callLater(root.flushSaves)
    }
  }

  onOpenedChanged: {
    if (!opened) editingSettings = false
    else TrainService.refresh(false, true)
  }

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
        settings: root.settings
        helperPath: TrainService.helperPath
        editingSettings: root.editingSettings
        saving: root.saving
        routeSaving: root.routeSaving
        settingsError: root.settingsError
        retryable: root.lastSave !== null && root.settingsError !== ""
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
