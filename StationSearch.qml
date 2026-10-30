import QtQuick
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import "kit"
import "Model.js" as Model

// Station search for the settings page: a SafeTextField (bounded,
// out-of-process paste) with debounced Entur geocoder results below it.
Column {
  id: root
  property string label: ""
  property string language: "en"
  property var selected: null
  property string helperPath: ""
  property var results: []
  property string error: ""
  property string requestedText: ""
  property int revision: 0
  property int requestedRevision: 0
  property bool searching: false
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
    process.command = ["timeout", "--kill-after=2s", "18s", "python3", helperPath, "--search=" + requestedText]
    process.running = true
  }
  spacing: FoamyStyle.gapSmall
  TrainText {
    text: root.label
    color: FoamyPalette.secondaryText
    font.pixelSize: FoamyStyle.font.bodySmall
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
    onExited: function(code) {
      // A completed search may belong to a replaced query or a selected result.
      if (root.requestedRevision !== root.revision) {
        Qt.callLater(root.runSearch)
        return
      }
      root.searching = false
      try {
        if (code !== 0) throw Error("search failed")
        var data = JSON.parse(output.text)
        if (data.status !== "ok") {
          root.error = FoamyI18n.t(data.error || "Station search failed. Try again.")
          return
        }
        if (!Array.isArray(data.stations) || !data.stations.every(function(s) {
          return Model.validStation(s) && typeof s.label === "string" && s.label.length <= 160
        })) throw Error("invalid stations")
        root.results = data.stations
        root.error = data.stations.length ? "" : FoamyI18n.t("No stations found.")
      } catch (e) {
        root.error = FoamyI18n.t("Station search failed. Try again.")
      }
    }
  }
}
