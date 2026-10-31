import QtQuick
import qs.Commons as Commons
import "../kit"
import ".." as Train
import "../tests/Fixtures.js" as Fixtures

// Bar widget states for the foamy-kit harness:
//   render.py <plugin> --preview preview/BarPreview.qml
// Each row is the real TrainBar on a bar-coloured strip; the notice marker
// expected for each state is checked (FOAMY FAIL on a mismatch).
Item {
  id: preview
  required property QtObject bar
  required property Item anchorItem
  property var previewStates: ["bar"]
  property string previewState: "bar"
  readonly property Item popup: popup
  readonly property var modes: [
    { label: "On time", mode: "normal", icon: "" },
    { label: "Later departure", mode: "long", icon: "" },
    { label: "Delayed 3 minutes", mode: "delay", icon: "" },
    { label: "Incident", mode: "incident", icon: "warning" },
    { label: "Information", mode: "info", icon: "info" },
    { label: "Route information", mode: "route-info", icon: "info" },
    { label: "Cancellation", mode: "cancelled", icon: "cancelled" },
    { label: "Cached times", mode: "stale", icon: "" },
    { label: "Outside schedule", mode: "schedule", icon: "" },
    { label: "Minutes hidden · incident", mode: "hidden", icon: "warning" }
  ]
  function sample(mode) {
    var r = Fixtures.report(mode === "long" ? "long" : "normal")
    if (mode === "delay") r.departures[0] = Fixtures.departure("a", 13, "R10", 3)
    if (mode === "incident" || mode === "hidden") r.departures[0].notices = [Fixtures.notice("x", "Signal fault", "warning")]
    if (mode === "info") r.departures[0].notices = [Fixtures.notice("x", "Shorter train", "info")]
    if (mode === "route-info") r.routeNotices = [Fixtures.notice("route", "Lift unavailable", "info")]
    if (mode === "cancelled") r.departures[1].cancelled = true
    return r
  }

  FoamyPopup {
    id: popup
    anchorItem: preview.anchorItem
    bar: preview.bar
    open: true
    body: Component {
      Column {
        width: FoamyStyle.popupWidth
        padding: FoamyStyle.padding
        spacing: FoamyStyle.gap
        Repeater {
          model: preview.modes
          Row {
            required property var modelData
            spacing: FoamyStyle.gapLarge
            Train.TrainText { width: 200; anchors.verticalCenter: parent.verticalCenter; text: modelData.label; wrapMode: Text.NoWrap }
            Rectangle {
              width: 160; height: 30
              radius: FoamyStyle.radiusSmall
              color: Commons.Color.bar.background
              Train.TrainBar {
                id: trainBar
                readonly property var data: preview.sample(modelData.mode)
                anchors.left: parent.left
                anchors.leftMargin: FoamyStyle.gapLarge
                anchors.verticalCenter: parent.verticalCenter
                foreground: Commons.Color.bar.text
                next: data.departures[0]
                departures: data.departures
                routeNotices: data.routeNotices
                nowEpoch: Fixtures.now
                stale: modelData.mode === "stale"
                withinSchedule: modelData.mode !== "schedule"
                showMinutes: modelData.mode !== "hidden"
                opacity: withinSchedule && !stale ? 1 : 0.45
                Component.onCompleted: if (noticeIcon !== modelData.icon)
                  console.log("FOAMY FAIL " + modelData.mode + " notice icon was '" + noticeIcon + "'")
              }
            }
          }
        }
      }
    }
  }
}
