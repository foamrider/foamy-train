import QtQuick
import QtQuick.Layouts
import qs.Commons

Rectangle {
  id: root
  required property var notice
  property bool expanded: false
  property bool cancelled: false
  property bool filled: false
  property color warning: Color.popups.background.hslLightness > 0.5 ? "#86601b" : "#d7b56d"
  readonly property color secondary: Qt.tint(Color.popups.background, Qt.alpha(Color.popups.text, 0.72))
  implicitHeight: contents.implicitHeight + Style.space(18)
  radius: Style.cornerRadius * 2
  color: filled ? Qt.alpha(Color.popups.text, 0.045) : "transparent"
  border.width: activeFocus ? 1 : 0
  border.color: Color.accent
  activeFocusOnTab: notice.detail !== ""
  Accessible.role: Accessible.Button
  Accessible.name: notice.summary
  Accessible.description: expanded ? notice.detail : ""
  Accessible.onPressAction: if (notice.detail)
                              expanded = !expanded
  Keys.onSpacePressed: if (notice.detail)
                         expanded = !expanded
  Keys.onReturnPressed: if (notice.detail)
                          expanded = !expanded
  Keys.onEnterPressed: if (notice.detail)
                         expanded = !expanded
  Column {
    id: contents
    x: Style.space(10)
    y: Style.space(9)
    width: parent.width - Style.space(20)
    spacing: Style.space(9)
    RowLayout {
      width: parent.width
      spacing: Style.space(8)
      TrainIcon {
        Layout.alignment: Qt.AlignTop
        width: Style.space(15)
        height: width
        name: root.cancelled && root.notice.kind === "warning" ? "cancelled" : root.notice.kind
        color: root.notice.kind === "info" ? Color.accent : root.cancelled ? Color.urgent : root.warning
      }
      TrainText {
        Layout.fillWidth: true
        text: (root.notice.scopeLabel ? root.notice.scopeLabel + " · " : "") + root.notice.summary
        color: root.secondary
      }
      TrainIcon {
        visible: root.notice.detail !== ""
        width: Style.space(13)
        height: width
        name: root.expanded ? "chevron-down" : "chevron-right"
        color: root.secondary
      }
    }
    TrainText {
      visible: root.expanded && root.notice.detail !== ""
      width: parent.width
      text: root.notice.detail
      color: root.secondary
    }
  }
  MouseArea {
    anchors.fill: parent
    enabled: root.notice.detail !== ""
    cursorShape: Qt.PointingHandCursor
    onClicked: {
      root.forceActiveFocus()
      root.expanded = !root.expanded
    }
  }
}
