import QtQuick
import Quickshell
import Quickshell.Io
import QtTest
import qs.Commons
import "plugin" as Train

Scope {
  FileView {
    id: settingsFile
    path: Quickshell.env("XDG_CONFIG_HOME") + "/omarchy/shell.json"
    atomicWrites: true
    onSaveFailed: console.error("SAVE FAILED")
  }
  IpcHandler {
    target: "shell"
    function setBarWidget(id: string, key: string, valueJson: string, selectorJson: string): string {
      if (id !== "foamy.train" || selectorJson !== "{}") return "Invalid target"
      if (test.rejectSave) return "Test write failure"
      var entry = Object.assign({}, widget.settings)
      entry[key] = JSON.parse(valueJson)
      settingsFile.setText(JSON.stringify({bar:{layout:{right:[Object.assign({id:id},entry)]}}}))
      widget.settings = entry
      return "ok"
    }
  }
  FloatingWindow {
    id: window
    visible: true
    implicitWidth: 500
    implicitHeight: 900
    color: Color.popups.background
    Train.Panel {
      id: widget
      width: 100
      height: 32
    }
    Train.Notice {
      id: notice
      y: 100
      width: 300
      notice: ({
                 id: "test",
                 summary: "Signal fault",
                 detail: "A longer explanation.",
                 kind: "warning",
                 scopeLabel: ""
               })
    }
    Train.ScheduleDay {
      id:day
      visible:false
      y:200
      width:320
      label:"Monday"
      property bool invalidSeen:false
      onChanged:function(range){value=range}
      onInvalid:invalidSeen=true
    }
    Timer {
      interval: 1000
      running: true
      onTriggered: {
        try {
          test.exerciseFlow()
        } catch (e) {
          console.error("INTERACTION FAILED", e.message, e.stack)
          Qt.quit()
        }
      }
    }
    TestCase {
      id: test
      name: "TrainInteractions"
      when: false
      property bool rejectSave: false
      function exerciseFlow() {
        tryCompare(widget, "initialized", true, 5000)
        compare(widget.report.status, "unconfigured")
        notice.forceActiveFocus()
        keyClick(Qt.Key_Space)
        verify(notice.expanded)
        keyClick(Qt.Key_Return)
        verify(!notice.expanded)
        day.visible=true
        day.forceActiveFocus()
        var toggle=findChild(day,"daySwitch")
        toggle.forceActiveFocus();keyClick(Qt.Key_Space)
        compare(day.value,"06:00-18:00")
        var start=findChild(day,"fromTime"),end=findChild(day,"toTime")
        start.text="22:00";end.text="02:00";end.editingFinished()
        compare(day.value,"22:00-02:00")
        toggle.toggled();compare(day.value,"")
        toggle.toggled();compare(day.value,"22:00-02:00")
        start.text="25:00";start.editingFinished()
        compare(day.value,"22:00-02:00");verify(day.invalidSeen)
        day.visible=false
        widget.openSettings()
        wait(300)
        verify(widget.opened)
        var from = findChild(widget, "fromSearch"), to = findChild(widget, "toSearch")
        verify(!!from)
        verify(!!to)
        var input = findChild(from, "stationInput")
        input.forceActiveFocus()
        verify(input.activeFocus)
        input.text = "Oslo S"
        input.textEdited()
        tryVerify(function () {
          return from.results.length > 0 || from.error !== ""
        }, 18000)
        compare(from.error, "")
        var result = findChild(from, "stationResult")
        verify(!!result)
        result.forceActiveFocus()
        keyClick(Qt.Key_Return)
        verify(!!from.selected)
        input = findChild(to, "stationInput")
        input.forceActiveFocus()
        input.text = "Lillestrøm"
        input.textEdited()
        tryVerify(function () {
          return to.results.length > 0 || to.error !== ""
        }, 18000)
        compare(to.error, "")
        result = findChild(to, "stationResult")
        result.forceActiveFocus()
        keyClick(Qt.Key_Return)
        verify(!!to.selected)
        verify(!findChild(widget, "applyRoute"))
        tryVerify(function () {
          return widget.report.route !== null
        }, 5000)
        tryVerify(function () {
          return widget.report.status === "ok"
        }, 18000)
        verify(widget.report.departures.length > 0)
        var origin = widget.report.route.from.id, destination = widget.report.route.to.id
        widget.closeSettings()
        widget.changeRoute(null)
        tryVerify(function () {
          return widget.report.route.from.id === destination
        }, 5000)
        compare(widget.report.route.to.id, origin)
        tryCompare(widget, "routeSaving", false, 5000)
        compare(widget.settings.route.from.id, destination)
        // A failed shell write keeps the previously saved route and surfaces the error.
        rejectSave = true
        widget.changeRoute(null)
        tryCompare(widget, "routeSaving", false, 5000)
        verify(widget.settingsError !== "")
        compare(widget.report.route.from.id, destination)
        rejectSave = false
        // Reload the persisted shell entry, as happens when the shell starts again.
        settingsFile.reload()
        var saved = JSON.parse(settingsFile.text()).bar.layout.right[0]
        widget.settings = {}
        compare(widget.report.status, "unconfigured")
        widget.settings = saved
        compare(widget.report.route.from.id, destination)
        widget.settings = Object.assign({}, widget.settings, {showBarMinutes:false})
        wait(50)
        verify(!findChild(widget,"barCountdown").visible)
        verify(!findChild(widget,"barDelay"))
        widget.settings = Object.assign({}, widget.settings, {showBarMinutes:true})
        wait(50)
        verify(findChild(widget,"barCountdown").visible)
        // A schedule change must immediately hide predictions and block even forced refreshes.
        widget.savePreference("scheduleEnabled", true)
        tryVerify(function () { return widget.settings.scheduleEnabled === true }, 5000)
        compare(widget.settings.route.from.id, destination)
        wait(100)
        verify(!widget.withinSchedule)
        widget.refresh(true)
        wait(200)
        verify(!findChild(widget,"departureProcess").running)
        verify(!findChild(widget,"barCountdown").visible)
        verify(findChild(widget,"sleepIcon").visible)
        verify(!findChild(widget,"departureDetails").visible)
        widget.close()
        console.log("INTERACTION COMPLETE")
        Qt.quit()
      }
    }
  }
}
