import QtQuick
import QtQuick.Controls as Controls
import Quickshell.Io
import qs.Commons
import "Preferences.js" as Preferences
import "Model.js" as Model

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
  signal changed
  function tr(s) {
    return Preferences.text(s, language)
  }
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
    input.forceActiveFocus()
  }
  function runSearch() {
    if (process.running)
      return
    if (input.text.trim().length < 2 || selected) {
      searching = false
      return
    }
    requestedText = input.text
    requestedRevision = revision
    process.command = ["timeout", "--kill-after=2s", "18s", "python3", helperPath, "--search", requestedText]
    process.running = true
  }
  spacing: Style.space(6)
  TrainText {
    text: root.label
    color: Qt.tint(Color.popups.background, Qt.alpha(Color.popups.text, 0.7))
  }
  Controls.TextField {
    id: input
    objectName: "stationInput"
    width: parent.width
    implicitHeight: Style.space(36)
    padding: Style.space(10)
    placeholderText: root.tr("Search stations…")
    color: Color.popups.text
    placeholderTextColor: Qt.alpha(Color.popups.text, 0.5)
    font.family: "sans-serif"
    font.pixelSize: Style.space(13)
    selectByMouse: true
    Accessible.name: root.label
    background: Rectangle {
      radius: Style.space(7)
      color: Qt.alpha(Color.popups.text, 0.055)
      border.width: input.activeFocus ? 1 : 0
      border.color: Color.accent
    }
    onTextEdited: {
      root.selected = null
      root.results = []
      root.error = ""
      root.revision++
      root.searching = text.trim().length >= 2
      debounce.restart()
      root.changed()
    }
  }
  TrainText {
    visible: root.searching || root.error !== ""
    width: parent.width
    text: root.searching ? root.tr("Searching…") : root.error
    color: root.error ? Color.urgent : Color.popups.text
    font.pixelSize: Style.space(11)
  }
  Repeater {
    model: root.results
    Rectangle {
      id: result
      objectName: "stationResult"
      required property var modelData
      width: root.width
      height: resultText.implicitHeight + Style.space(16)
      radius: Style.space(6)
      color: hover.containsMouse || activeFocus ? Qt.alpha(Color.accent, 0.12) : Qt.alpha(Color.popups.text, 0.04)
      border.width: activeFocus ? 1 : 0
      border.color: Color.accent
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
      TrainText {
        id: resultText
        x: Style.space(9)
        y: Style.space(8)
        width: parent.width - Style.space(18)
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
    onExited: function (code) {
      // A completed search may belong to a replaced query or a selected result.
      if (root.requestedRevision !== root.revision) {
        Qt.callLater(root.runSearch)
        return
      }
      root.searching = false
      try {
        if (code !== 0)
          throw Error("search failed")
        var data = JSON.parse(output.text)
        if (data.status !== "ok") {
          root.error = root.tr(data.error || "Station search failed. Try again.")
          return
        }
        if (!Array.isArray(data.stations) || !data.stations.every(function (s) {
          return Model.validStation(s) && typeof s.label === "string"
        }))
          throw Error("invalid stations")
        root.results = data.stations
        root.error = data.stations.length ? "" : root.tr("No stations found.")
      } catch (e) {
        root.error = root.tr("Station search failed. Try again.")
      }
    }
  }
}
