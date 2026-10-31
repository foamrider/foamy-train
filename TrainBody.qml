import QtQuick
import QtQuick.Controls as Controls
import qs.Ui
import "kit"
import "Model.js" as Model

// The popup body: departures (TrainView) or the settings page, behind one
// key catcher with a single cursor. Arrows/hjkl move, Enter/Space activate,
// Esc closes (or leaves Settings), Tab/Shift-Tab switch bar panels, `s` opens
// Settings, `r` refreshes. Data comes in through properties so the preview
// can feed mock states; Panel.qml owns saving, TrainService the data.
PanelKeyCatcher {
  id: root

  property var report: Model.blank("loading")
  property real nowEpoch: 0
  property bool stale: false
  property var departures: []
  property var next: null
  property string language: "en"
  property bool loading: false
  property bool offline: false
  property bool outsideSchedule: false
  property var route: null
  property var settings: ({})
  property string helperPath: ""
  property bool editingSettings: false
  property bool saving: false
  property bool routeSaving: false
  property string settingsError: ""
  property bool retryable: false

  signal closeRequestedByView()
  signal settingsRequested()
  signal settingsClosed()
  signal refreshRequested()
  signal swapRequested()
  signal saveRequested(string key, var value)
  signal retryRequested()
  signal switchPanelRequested(int direction)

  implicitWidth: FoamyStyle.popupWidth
  implicitHeight: editingSettings ? settingsPane.implicitHeight : view.implicitHeight
  blocked: editingSettings

  readonly property string cursorKey: keyAt(cursor.index)
  // The stop the keyboard or pointer last chose. `stops` is rebuilt on every
  // clock tick (TrainService.departures is a new array each second), and the
  // cursor is put back on this key each time. Set only where a stop is
  // chosen, from `stops` directly: reading the cursorKey binding from the
  // cursor's own indexChanged handler can see the previous stop (the binding
  // is not re-evaluated yet), and the next tick then sends the cursor back
  // there, so it ping-ponged between the last two stops once a second.
  property string heldKey: ""
  function keyAt(index) { return index >= 0 && index < view.stops.length ? view.stops[index] : "" }
  function hold() { heldKey = keyAt(cursor.index) }

  FoamyCursor {
    id: cursor
    count: view.stops.length
  }
  // Keep the cursor on the same stop when a tick or refresh rebuilds the
  // stops; drop it when that stop is gone.
  Connections {
    target: view
    function onStopsChanged() {
      if (root.heldKey === "") return
      cursor.index = view.stops.indexOf(root.heldKey)
      if (cursor.index < 0) root.heldKey = ""
    }
  }

  onMoveRequested: function(dx, dy) { cursor.move(dy !== 0 ? dy : dx); hold() }
  onActivateRequested: view.activate(root.cursorKey)
  onCloseRequested: root.closeRequestedByView()
  onTabRequested: function(direction) { root.switchPanelRequested(direction) }
  onTextKey: function(text) {
    if (text === "s") root.settingsRequested()
    else if (text === "r") root.refreshRequested()
  }

  onEditingSettingsChanged: {
    scroll.contentY = 0
    if (editingSettings) {
      settingsPane.resetRoute()
      settingsPane.resetScroll()
      Qt.callLater(settingsPane.focusBack)
    } else {
      Qt.callLater(root.forceActiveFocus)
    }
  }
  onVisibleChanged: if (!visible) { cursor.reset(); heldKey = "" }

  // The departures scroller (tests check that cursor stops stay visible).
  readonly property Flickable scroller: scroll

  Flickable {
    id: scroll
    visible: !root.editingSettings
    anchors.fill: parent
    clip: true
    contentWidth: width
    contentHeight: view.implicitHeight
    boundsBehavior: Flickable.StopAtBounds
    flickableDirection: Flickable.VerticalFlick
    onContentHeightChanged: contentY = Math.max(0, Math.min(contentY, contentHeight - height))
    onHeightChanged: contentY = Math.max(0, Math.min(contentY, contentHeight - height))
    Controls.ScrollBar.vertical: Controls.ScrollBar { policy: Controls.ScrollBar.AsNeeded }

    TrainView {
      id: view
      width: scroll.width
      report: root.report
      nowEpoch: root.nowEpoch
      stale: root.stale
      departures: root.departures
      next: root.next
      language: root.language
      loading: root.loading
      outsideSchedule: root.outsideSchedule
      routeBusy: root.routeSaving
      cursorKey: root.cursorKey
      onStopHovered: function(key) { cursor.hover(view.stops.indexOf(key)); root.hold() }
      onRevealRequested: function(item) {
        var point = item.mapToItem(view, 0, 0)
        var margin = FoamyStyle.gap
        if (point.y < scroll.contentY) scroll.contentY = Math.max(0, point.y - margin)
        else if (point.y + item.height > scroll.contentY + scroll.height)
          scroll.contentY = Math.max(0, Math.min(scroll.contentHeight - scroll.height, point.y + item.height - scroll.height + margin))
      }
      onSettingsRequested: root.settingsRequested()
      onSwapRequested: root.swapRequested()
      onRefreshRequested: root.refreshRequested()
    }
  }

  SettingsPane {
    id: settingsPane
    visible: root.editingSettings
    width: parent.width
    height: parent.height
    route: root.route
    settings: root.settings
    language: root.language
    helperPath: root.helperPath
    saving: root.saving
    routeSaving: root.routeSaving
    error: root.settingsError
    retryable: root.retryable
    onSaveRequested: function(key, value) { root.saveRequested(key, value) }
    onRetry: root.retryRequested()
    onBack: root.settingsClosed()
  }
}
