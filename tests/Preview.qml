import QtQuick
import Quickshell
import qs.Commons
import "plugin" as Train
import "plugin/tests/Fixtures.js" as Fixtures

Scope {
  id: root
  property var states: ["normal", "delayed", "incidents", "route", "cancelled", "offline", "error", "empty", "loading", "unconfigured",
    "schedule", "settings", "settings-off"]
  property int index: 0
  property string state: states[index % states.length]
  property bool narrow: index >= states.length
  property bool light: index >= states.length * 2
  property string output: Quickshell.env("TRAIN_PREVIEW_DIR") || "/tmp"
  function advance() {
    if (index >= states.length * 3) {
      console.log("PREVIEW COMPLETE")
      Qt.quit()
      return
    }
    Color.popups.background = light ? "#f3f4f2" : "#141818"
    Color.popups.text = light ? "#303936" : "#ced2ce"
    Color.accent = light ? "#38629b" : "#88a8d8"
    Color.urgent = light ? "#a14040" : "#e08a8a"
    settings.resetRoute()
    capture.restart()
  }
  FloatingWindow {
    id: window
    visible: true
    implicitWidth: root.narrow ? 320 : 480
    implicitHeight: Math.ceil(root.state.indexOf("settings")===0 ? settings.implicitHeight : view.implicitHeight)
    color: Color.popups.background
    Rectangle {
      id: surface
      width: root.narrow ? 320 : 480
      height: Math.ceil(root.state.indexOf("settings")===0 ? settings.implicitHeight : view.implicitHeight)
      color: Color.popups.background
      Train.TrainView {
        id: view
        visible: root.state.indexOf("settings")!==0
        width: parent.width
        report: Fixtures.report(root.state)
        nowEpoch: Fixtures.now
        loading: root.state === "loading"
        outsideSchedule: root.state === "schedule"
        language: root.light ? "nb" : "en"
      }
      Train.SettingsPane {
        id: settings
        visible: root.state.indexOf("settings")===0
        width: parent.width
        route: Fixtures.route
        language: root.light ? "nb" : "en"
        settings: ({
                     scheduleEnabled: root.state!=="settings-off",
                     scheduleMonday: "06:00-18:00",
                     scheduleTuesday: "06:00-18:00",
                     scheduleWednesday: "06:00-18:00",
                     scheduleThursday: "22:00-02:00",
                     scheduleFriday: "06:00-18:00"
                   })
      }
    }
  }
  Timer {
    interval: 600
    running: true
    onTriggered: root.advance()
  }
  Timer {
    id: capture
    interval: 120
    onTriggered: surface.grabToImage(function (result) {
      var name = root.state + (root.light ? "-light-nb" : root.narrow ? "-narrow" : "")
      if (!result.saveToFile(root.output + "/" + name + ".png"))
        console.error("SAVE FAILED", name)
      root.index++
      root.advance()
    })
  }
}
