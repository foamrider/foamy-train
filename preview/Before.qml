import QtQuick
import qs.Commons
import qs.Commons as Commons
import ".." as Dev
import "../tests/Fixtures.js" as Fixtures

// The dev-branch UI for the --trio "Before" column (rendered from origin/dev,
// the forked TrainPopup with TrainView / SettingsPane). State names match
// preview/Preview.qml.
Item {
  id: preview
  required property QtObject bar
  required property Item anchorItem
  property var previewStates: ["departures", "incidents", "offline", "error", "unconfigured", "schedule", "settings"]
  property string previewState: "departures"
  readonly property Item popup: popup
  readonly property bool settingsState: previewState === "settings"

  Dev.TrainPopup {
    id: popup
    anchorItem: preview.anchorItem; bar: preview.bar; open: true; padding: 0
    borderSpec: Border.flat(Qt.alpha(Commons.Color.popups.text, 0.15), 1)
    contentWidth: popup.fittedContentWidth(Style.space(480))
    contentHeight: popup.fittedContentHeight(Math.min(Style.space(820), preview.settingsState ? pane.implicitHeight : view.implicitHeight))
    Dev.TrainView {
      id: view
      visible: !preview.settingsState
      width: parent.width
      report: Fixtures.report(preview.previewState === "departures" ? "normal" : preview.previewState)
      nowEpoch: Fixtures.now
      outsideSchedule: preview.previewState === "schedule"
      language: "en"
    }
    Dev.SettingsPane {
      id: pane
      visible: preview.settingsState
      width: parent.width
      route: Fixtures.route
      language: "en"
      settings: ({})
    }
  }
}
