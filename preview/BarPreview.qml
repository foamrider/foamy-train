import QtQuick
import qs.Commons as Commons
import "../kit"
import ".." as Train
import "../tests/Fixtures.js" as Fixtures

// Bar widget states for the foamy-kit harness:
//   render.py <plugin> --preview preview/BarPreview.qml
// Each row is the real TrainBar on a bar-coloured strip. tests/states.py
// checks the countdown and the notice marker of each state.
Item {
  id: preview
  required property QtObject bar
  required property Item anchorItem
  property var previewStates: ["bar"]
  property string previewState: "bar"
  readonly property var popup: previewPopup
  readonly property var modes: [
    {
      label: "On time",
      mode: "normal"
    },
    {
      label: "Later departure",
      mode: "long"
    },
    {
      label: "Delayed 3 minutes",
      mode: "delay"
    },
    {
      label: "Incident",
      mode: "incident"
    },
    {
      label: "Information",
      mode: "info"
    },
    {
      label: "Route information",
      mode: "route-info"
    },
    {
      label: "Cancellation",
      mode: "cancelled"
    },
    {
      label: "Cached times",
      mode: "stale"
    },
    {
      label: "Outside schedule",
      mode: "schedule"
    },
    {
      label: "Minutes hidden · incident",
      mode: "hidden"
    }
  ]
  function sample(mode) {
    var r = Fixtures.report(mode === "long" ? "long" : "normal")
    if (mode === "delay")
      r.departures[0] = Fixtures.departure("a", 13, "R10", 3)
    if (mode === "incident" || mode === "hidden")
      r.departures[0].notices = [Fixtures.notice("x", "Signal fault", "warning")]
    if (mode === "info")
      r.departures[0].notices = [Fixtures.notice("x", "Shorter train", "info")]
    if (mode === "route-info")
      r.routeNotices = [Fixtures.notice("route", "Lift unavailable", "info")]
    if (mode === "cancelled")
      r.departures[1].cancelled = true
    return r
  }

  FoamyPopup {
    id: previewPopup
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
            Train.TrainText {
              width: 200
              anchors.verticalCenter: parent.verticalCenter
              text: modelData.label
              wrapMode: Text.NoWrap
            }
            Rectangle {
              width: 160
              height: 30
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
              }
            }
          }
        }
      }
    }
  }
}
