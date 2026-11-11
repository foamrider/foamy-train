import QtQuick
import Quickshell.Io
import qs.Commons as Commons
import "kit"
import "kit/FoamyNative.js" as FoamyNative
import "Model.js" as Model

// Station search for the settings page: a SafeTextField (bounded,
// out-of-process paste) with debounced Entur geocoder results below it.
Column {
  id: root
  property string label: ""
  property string language: "en"
  property var selected: null
  // The plugin directory; the search runs bin/<arch>/foamy-train-helper.
  property string pluginDir: ""
  // At most Model.limits.stations (the helper asks Entur for limit=8 and
  // keeps that many; Model.stations applies the same limit to each reply).
  property var results: []
  property string error: ""
  property string requestedText: ""
  property int revision: 0
  property int requestedRevision: 0
  property bool searching: false
  // A search started and not yet finished (exited, or failed to start).
  property bool inFlight: false
  // The search's deadline; the helper command follows it.
  property var deadline: ["timeout", "--kill-after=2s", "18s"]
  property alias input: input
  signal changed
  function selectStation(value) {
    selected = value
    input.text = value ? value.name : ""
    results = []
    error = ""
    revision++
    searching = false
    debounce.stop()
  }
  function choose(value) {
    selectStation(value)
    changed()
    input.focusInput()
  }
  function runSearch() {
    if (process.running) return
    if (input.text.trim().length < 2 || selected) {
      searching = false
      return
    }
    requestedText = input.text
    requestedRevision = revision
    // `--search=` keeps a query that starts with "-" from parsing as an option.
    process.command = deadline.concat(
      FoamyNative.command(pluginDir, "foamy-train-helper", ["--search=" + requestedText]))
    inFlight = true
    process.running = true
  }
  // The one end of a search: exited, or never started (Quickshell then emits
  // no exited(), only running -> false). Later calls for the same search
  // (the running -> false after exited()) find nothing in flight.
  function finishSearch(code, started) {
    if (!root.inFlight) return
    root.inFlight = false
    // A completed search may belong to a replaced query or a selected result.
    if (root.requestedRevision !== root.revision) {
      Qt.callLater(root.runSearch)
      return
    }
    root.searching = false
    if (!started) {
      root.error = FoamyI18n.t("Station search failed. Try again.")
      return
    }
    if (FoamyNative.unavailable(code)) {
      // No helper for this CPU: say so; searches only run on typing, never retried.
      root.error = FoamyI18n.t(FoamyNative.UNAVAILABLE_TEXT)
      return
    }
    try {
      if (code !== 0) throw Error("search failed")
      var data = JSON.parse(output.text)
      if (data.status !== "ok") {
        root.error = FoamyI18n.t(data.error || "Station search failed. Try again.")
        return
      }
      var stations = Model.stations(data)
      root.results = stations
      root.error = stations.length ? "" : FoamyI18n.t("No stations found.")
    } catch (e) {
      root.error = FoamyI18n.t("Station search failed. Try again.")
    }
  }
  spacing: FoamyStyle.gapSmall
  TrainText {
    text: root.label
    color: FoamyPalette.secondaryText
    font.pixelSize: FoamyStyle.font.bodySmall
    font.bold: true
  }
  SafeTextField {
    id: input
    objectName: "stationInput"
    width: parent.width
    placeholderText: FoamyI18n.t("Search stations…")
    translate: FoamyI18n.t
    Accessible.name: root.label
    onTextEdited: {
      root.selected = null
      root.results = []
      root.error = ""
      root.revision++
      root.searching = text.trim().length >= 2
      debounce.restart()
      root.changed()
    }
    onKeyPressed: function(event) {
      if (event.key === Qt.Key_Down && resultRepeater.count > 0) {
        resultRepeater.itemAt(0).forceActiveFocus()
        event.accepted = true
      }
    }
  }
  TrainText {
    visible: root.searching || root.error !== "" || input.pasteError !== ""
    width: parent.width
    text: root.searching ? FoamyI18n.t("Searching…") : root.error !== "" ? root.error : FoamyI18n.t(input.pasteError)
    color: root.searching ? FoamyPalette.mutedText : Commons.Color.urgent
    font.pixelSize: FoamyStyle.font.bodySmall
  }
  Repeater {
    id: resultRepeater
    model: root.results
    Rectangle {
      id: result
      objectName: "stationResult"
      required property var modelData
      required property int index
      width: root.width
      height: resultText.implicitHeight + FoamyStyle.gap * 2
      radius: FoamyStyle.radius
      color: hover.containsMouse || activeFocus ? FoamyPalette.selectedFill : Qt.alpha(FoamyPalette.text, 0.04)
      border.width: activeFocus ? 1 : 0
      border.color: Commons.Color.accent
      activeFocusOnTab: true
      function choose() {
        root.choose(modelData)
      }
      Accessible.role: Accessible.Button
      Accessible.name: modelData.label
      Accessible.onPressAction: choose()
      Keys.onReturnPressed: choose()
      Keys.onEnterPressed: choose()
      Keys.onSpacePressed: choose()
      Keys.onDownPressed: if (index + 1 < resultRepeater.count) resultRepeater.itemAt(index + 1).forceActiveFocus()
      Keys.onUpPressed: index > 0 ? resultRepeater.itemAt(index - 1).forceActiveFocus() : input.focusInput()
      TrainText {
        id: resultText
        x: FoamyStyle.gap
        y: FoamyStyle.gap
        width: parent.width - FoamyStyle.gap * 2
        text: result.modelData.label
      }
      MouseArea {
        id: hover
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: result.choose()
      }
    }
  }
  Timer {
    id: debounce
    interval: 350
    onTriggered: root.runSearch()
  }
  Process {
    id: process
    stdout: StdioCollector {
      id: output
      waitForEnd: true
    }
    onExited: function(code) { root.finishSearch(code, true) }
    onRunningChanged: if (!running) root.finishSearch(-1, false)
  }
}
