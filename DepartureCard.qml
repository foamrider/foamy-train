import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Commons as Commons
import "kit"
import "Model.js" as Model

Rectangle {
  id: root
  required property var departure
  required property string destination
  required property real nowEpoch
  required property string language
  property bool stale: false
  property Item view: null
  function formatNumber(value) { return FoamyI18n.number(value, 0) }
  function durationText(minutes) { return Model.duration(minutes, root.language, root.formatNumber) }
  implicitHeight: body.implicitHeight + (root.departure.notices.length > 0 ? FoamyStyle.sectionGap : FoamyStyle.padding)
  radius: FoamyStyle.radius
  color: Qt.alpha(FoamyPalette.text, 0.05)
  Column {
    id: body
    x: FoamyStyle.gapLarge
    y: FoamyStyle.rowPadding
    width: parent.width - FoamyStyle.gapLarge * 2
    spacing: FoamyStyle.gap
    RowLayout {
      width: parent.width
      spacing: FoamyStyle.gapLarge
      Rectangle {
        Layout.preferredWidth: Math.max(Style.space(34), lineLabel.implicitWidth + FoamyStyle.gapLarge)
        Layout.preferredHeight: Style.space(25)
        radius: FoamyStyle.radius
        color: Qt.alpha(Commons.Color.accent, 0.15)
        TrainText {
          id: lineLabel
          anchors.centerIn: parent
          text: root.departure.line
          color: Commons.Color.accent
          font.pixelSize: FoamyStyle.font.bodySmall
          wrapMode: Text.NoWrap
        }
      }
      ColumnLayout {
        Layout.fillWidth: true
        spacing: FoamyStyle.gapSmall
        RowLayout {
          Layout.fillWidth: true
          TrainText {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignVCenter
            text: root.destination
            font.pixelSize: FoamyStyle.font.subtitle
            elide: Text.ElideRight
            wrapMode: Text.NoWrap
          }
          TrainText {
            visible: !root.departure.cancelled
            Layout.alignment: Qt.AlignVCenter
            text: root.stale ? root.departure.expectedTime : root.durationText(Model.minutes(root.departure, root.nowEpoch))
            wrapMode: Text.NoWrap
          }
          Rectangle {
            visible: root.departure.cancelled
            Layout.alignment: Qt.AlignVCenter
            implicitWidth: cancelledLabel.implicitWidth + FoamyStyle.sectionGap
            implicitHeight: cancelledLabel.implicitHeight + FoamyStyle.gap
            radius: FoamyStyle.radius
            color: Qt.alpha(Commons.Color.urgent, 0.1)
            TrainText {
              id: cancelledLabel
              anchors.centerIn: parent
              text: FoamyI18n.t("Cancelled")
              color: Commons.Color.urgent
              wrapMode: Text.NoWrap
            }
          }
        }
        Flow {
          Layout.fillWidth: true
          spacing: FoamyStyle.gapSmall
          TrainText {
            text: root.departure.aimedTime
            font.strikeout: root.departure.cancelled || root.departure.delay > 0
            color: FoamyPalette.secondaryText
            font.pixelSize: FoamyStyle.font.bodySmall
            wrapMode: Text.NoWrap
          }
          TrainText {
            visible: root.departure.delay > 0 && !root.departure.cancelled
            text: "→ " + root.departure.expectedTime
            color: FoamyPalette.secondaryText
            font.pixelSize: FoamyStyle.font.bodySmall
            wrapMode: Text.NoWrap
          }
          TrainText {
            text: "· " + FoamyI18n.t("Platform") + " " + root.departure.platform
            color: FoamyPalette.secondaryText
            font.pixelSize: FoamyStyle.font.bodySmall
            wrapMode: Text.NoWrap
          }
          TrainText {
            visible: !root.departure.cancelled && !root.stale
            text: "· " + (root.departure.delay > 0 ? "+" + root.durationText(root.departure.delay)
                                                    : FoamyI18n.t(root.departure.realtime ? "On time" : "Scheduled"))
            color: root.departure.delay > 0 ? FoamyPalette.onSurface(FoamyPalette.warning)
                   : root.departure.realtime ? FoamyPalette.onSurface(FoamyPalette.success) : FoamyPalette.secondaryText
            font.pixelSize: FoamyStyle.font.bodySmall
            wrapMode: Text.NoWrap
          }
        }
      }
    }
    Column {
      visible: root.departure.notices.length > 0
      width: parent.width
      spacing: FoamyStyle.gapSmall
      Rectangle {
        width: parent.width
        height: 1
        color: FoamyPalette.divider
      }
      Repeater {
        model: root.departure.notices
        Notice {
          required property var modelData
          width: body.width
          notice: modelData
          cancelled: root.departure.cancelled
          cursorKey: "dep/" + root.departure.id + "/" + modelData.id
          view: root.view
        }
      }
    }
  }
}
