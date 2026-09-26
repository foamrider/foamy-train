import QtQuick
import QtQuick.Layouts
import qs.Commons
import "Preferences.js" as Preferences
import "Model.js" as Model

Rectangle {
  id: root
  required property var departure
  required property string destination
  required property real nowEpoch
  required property string language
  property bool stale: false
  readonly property color secondary: Qt.tint(Color.popups.background, Qt.alpha(Color.popups.text, 0.7))
  readonly property color warning: Color.popups.background.hslLightness > 0.5 ? "#86601b" : "#d7b56d"
  readonly property color success: Color.popups.background.hslLightness > 0.5 ? "#437341" : "#9fbe92"
  function tr(s) {
    return Preferences.text(s, language)
  }
  implicitHeight: body.implicitHeight + Style.space(20)
  radius: Style.space(9)
  color: Qt.alpha(Color.popups.text, 0.05)
  Column {
    id: body
    x: Style.space(12)
    y: Style.space(10)
    width: parent.width - Style.space(24)
    spacing: Style.space(9)
    RowLayout {
      width: parent.width
      spacing: Style.space(12)
      Rectangle {
        width: Math.max(Style.space(34), lineLabel.implicitWidth + Style.space(12))
        height: Style.space(25)
        radius: Style.space(5)
        color: Qt.alpha(Color.accent, 0.15)
        TrainText {
          id: lineLabel
          anchors.centerIn: parent
          text: root.departure.line
          color: Color.accent
          font.pixelSize: Style.space(11)
        }
      }
      ColumnLayout {
        Layout.fillWidth: true
        spacing: Style.space(6)
        RowLayout {
          Layout.fillWidth: true
          TrainText {
            Layout.fillWidth: true
            text: root.destination
            font.pixelSize: Style.space(13)
          }
          TrainText {
            Layout.alignment: Qt.AlignTop
            text: root.departure.cancelled ? root.tr("Cancelled") : root.stale ? root.departure.expectedTime :
                                                                                 Model.minutes(root.departure,
                                                                                               root.nowEpoch) + " min"
            color: root.departure.cancelled ? Color.urgent : Color.popups.text
          }
        }
        Flow {
          Layout.fillWidth: true
          spacing: Style.space(4)
          TrainText {
            text: root.departure.aimedTime
            font.strikeout: root.departure.cancelled || root.departure.delay > 0
            color: root.secondary
            font.pixelSize: Style.space(11)
          }
          TrainText {
            visible: root.departure.delay > 0 && !root.departure.cancelled
            text: "→ " + root.departure.expectedTime
            color: root.secondary
            font.pixelSize: Style.space(11)
          }
          TrainText {
            text: "· " + root.tr("Platform") + " " + root.departure.platform
            color: root.secondary
            font.pixelSize: Style.space(11)
          }
          TrainText {
            visible: !root.departure.cancelled && !root.stale
            text: "· " + (root.departure.delay > 0 ? "+" + root.departure.delay + " min" : root.tr(
                                                       root.departure.realtime ? "On time" : "Scheduled"))
            color: root.departure.delay > 0 ? root.warning : root.departure.realtime ? root.success : root.secondary
            font.pixelSize: Style.space(11)
          }
        }
      }
    }
    Column {
      visible: root.departure.notices.length > 0
      width: parent.width
      Rectangle {
        width: parent.width
        height: 1
        color: Qt.alpha(Color.popups.text, 0.14)
      }
      Repeater {
        model: root.departure.notices
        Notice {
          required property var modelData
          width: body.width
          notice: modelData
          cancelled: root.departure.cancelled
        }
      }
    }
  }
}
