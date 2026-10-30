import QtQuick
import "../kit"
import ".." as Train
import "../tests/Fixtures.js" as Fixtures
import "../Model.js" as Model

// Preview states for the foamy-kit preview harness (mock data only: no
// processes, no network). See foamy-kit README, "Preview".
Item {
  id: preview
  required property QtObject bar
  required property Item anchorItem
  property var previewStates: ["departures", "delayed", "incidents", "route", "cancelled", "offline", "error", "unconfigured",
    "schedule", "loading", "cursor", "settings", "settings-schedule", "settings-error"]
  property string previewState: "departures"
  readonly property Item popup: popup

  readonly property string fixture: previewState === "cursor" ? "incidents" : previewState
  readonly property var report: Fixtures.report(fixture)
  readonly property bool stale: Model.stale(report, Fixtures.now, false, 60)
  readonly property var departures: Model.upcoming(report, Fixtures.now, stale)

  FoamyPopup {
    id: popup
    anchorItem: preview.anchorItem
    bar: preview.bar
    open: true
    body: Component {
      Train.TrainBody {
        id: body
        report: preview.report
        nowEpoch: Fixtures.now
        stale: preview.stale
        departures: preview.departures
        next: Model.next(preview.departures)
        loading: preview.previewState === "loading"
        outsideSchedule: preview.previewState === "schedule"
        route: Fixtures.route
        editingSettings: preview.previewState.indexOf("settings") === 0
        settingsError: preview.previewState === "settings-error" ? "Couldn't save the setting." : ""
        retryable: preview.previewState === "settings-error"
        settings: ({
          route: Fixtures.route,
          scheduleEnabled: preview.previewState === "settings-schedule",
          scheduleMonday: "06:00-18:00", scheduleTuesday: "06:00-18:00", scheduleWednesday: "06:00-18:00",
          scheduleThursday: "22:00-02:00", scheduleFriday: "06:00-18:00"
        })
        Connections {
          target: preview
          function onPreviewStateChanged() { body.applyCursorState() }
        }
        function applyCursorState() {
          if (preview.previewState === "cursor") {
            // Keyboard cursor on the first notice, expanded.
            moveRequested(0, 1); moveRequested(0, 1); moveRequested(0, 1)
            activateRequested()
          }
        }
        Component.onCompleted: applyCursorState()
      }
    }
  }
}
