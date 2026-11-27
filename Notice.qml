import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Commons as Commons
import "kit"

// A service notice. With detail text it is a cursor stop in the popup and
// expands on click, Enter or Space (the view owns cursor and expanded state).
FoamyCursorSurface {
  id: root
  required property var notice
  property bool cancelled: false
  property bool filled: false
  property string cursorKey: ""
  property Item view: null
  // The opaque colour under the notice (a departure card's fill in a card).
  property color surface: FoamyPalette.background
  // The status icon is read on the cursor's fill, the strongest one, so it
  // keeps one colour with and without the cursor.
  readonly property color iconSurface: Qt.tint(surface, FoamyPalette.hoverFill)
  readonly property bool expandable: notice.detail !== ""
  readonly property bool expanded: !!view && !!view.expanded[cursorKey]

  hasCursor: expandable && !!view && view.cursorKey === cursorKey
  implicitHeight: contents.implicitHeight + FoamyStyle.rowPadding * 2
  color: hasCursor ? FoamyPalette.hoverFill : filled ? Qt.alpha(FoamyPalette.text, 0.045) : "transparent"
  onHasCursorChanged: if (hasCursor && view)
    view.revealRequested(root)
  onExpandedChanged: if (expanded && view)
    view.detailOpened(root)
  onHovered: if (expandable && view)
    view.stopHovered(cursorKey)
  onClicked: if (expandable && view)
    view.toggle(cursorKey)

  Accessible.role: expandable ? Accessible.Button : Accessible.StaticText
  Accessible.name: notice.summary
  Accessible.description: expanded ? notice.detail : ""
  Accessible.onPressAction: if (expandable && view)
    view.toggle(cursorKey)

  Column {
    id: contents
    x: FoamyStyle.rowPadding
    y: FoamyStyle.rowPadding
    width: parent.width - FoamyStyle.rowPadding * 2
    spacing: FoamyStyle.gap
    RowLayout {
      width: parent.width
      spacing: FoamyStyle.gap
      FoamyIcon {
        Layout.alignment: Qt.AlignVCenter
        Layout.preferredWidth: FoamyStyle.iconSize
        Layout.preferredHeight: FoamyStyle.iconSize
        // Information notices keep the announcement (megaphone) shape.
        name: root.notice.kind === "info" ? "megaphone" : root.cancelled ? "cancelled" : "warning"
        color: root.notice.kind === "info" ? Commons.Color.accent : root.cancelled ? FoamyPalette.onSurface(Commons.Color.urgent, root.iconSurface) : FoamyPalette.onSurface(FoamyPalette.warning, root.iconSurface)
      }
      TrainText {
        Layout.fillWidth: true
        text: (root.notice.scopeLabel ? root.notice.scopeLabel + " · " : "") + root.notice.summary
        color: FoamyPalette.secondaryText
      }
      FoamyIcon {
        visible: root.expandable
        Layout.preferredWidth: Style.space(13)
        Layout.preferredHeight: Style.space(13)
        name: root.expanded ? "chevron-down" : "chevron-right"
        color: FoamyPalette.secondaryText
      }
    }
    TrainText {
      visible: root.expanded && root.expandable
      width: parent.width
      text: root.notice.detail
      color: FoamyPalette.secondaryText
    }
  }
}
