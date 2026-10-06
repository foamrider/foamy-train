import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Schedule.js" as Schedule

RowLayout {
  id: root
  property string label: ""
  property string fromLabel: "From"
  property string toLabel: "To"
  property string value: ""
  property string lastRange: "06:00-18:00"
  readonly property bool dayEnabled: value !== ""
  signal changed(string value)
  signal invalid()
  spacing: Style.space(6)
  function restoreInputs(force) {
    if (value !== "" && Schedule.validRange(value)) lastRange = value
    var parts = lastRange.split("-")
    if (force || !fromInput.activeFocus) fromInput.text = parts[0]
    if (force || !toInput.activeFocus) toInput.text = parts[1]
  }
  function saveInputs() {
    if (!dayEnabled) return
    var range = fromInput.text.trim() + "-" + toInput.text.trim()
    if (!Schedule.validRange(range)) {invalid();return}
    if (range !== value) changed(range)
  }
  onValueChanged: restoreInputs()
  Component.onCompleted: restoreInputs()
  TrainText {
    Layout.fillWidth: true
    text: root.label
    font.pixelSize: Style.space(12)
  }
  ToggleSwitch {
    objectName: "daySwitch"
    checked: root.dayEnabled
    trackHeight: Style.space(17)
    foreground: Color.popups.text
    activeFocusOnTab: true
    Accessible.role: Accessible.CheckBox
    Accessible.name: root.label
    Accessible.checked: checked
    Accessible.onToggleAction: toggled()
    Keys.onSpacePressed: toggled()
    Keys.onReturnPressed: toggled()
    Keys.onEnterPressed: toggled()
    onToggled: root.changed(checked ? "" : root.lastRange)
    Rectangle {anchors.fill:parent;color:"transparent";radius:Style.cornerRadius * 2;border.width:parent.activeFocus?1:0;border.color:Color.accent}
  }
  Controls.TextField {
    id: fromInput
    objectName: "fromTime"
    Layout.preferredWidth: Style.space(58)
    implicitHeight: Style.space(32)
    enabled: root.dayEnabled
    opacity: enabled ? 1 : 0.4
    color: Color.popups.text
    font.family: "sans-serif"
    font.pixelSize: Style.space(12)
    padding: Style.space(6)
    selectByMouse: true
    maximumLength: 5
    Accessible.name: root.label + " · " + root.fromLabel
    background: Rectangle {radius:Style.cornerRadius * 2;color:Qt.alpha(Color.popups.text,0.055);border.width:fromInput.activeFocus?1:0;border.color:Color.accent}
    onEditingFinished: root.saveInputs()
    Keys.onEscapePressed: root.restoreInputs(true)
  }
  Controls.TextField {
    id: toInput
    objectName: "toTime"
    Layout.preferredWidth: Style.space(58)
    implicitHeight: Style.space(32)
    enabled: root.dayEnabled
    opacity: enabled ? 1 : 0.4
    color: Color.popups.text
    font.family: "sans-serif"
    font.pixelSize: Style.space(12)
    padding: Style.space(6)
    selectByMouse: true
    maximumLength: 5
    Accessible.name: root.label + " · " + root.toLabel
    background: Rectangle {radius:Style.cornerRadius * 2;color:Qt.alpha(Color.popups.text,0.055);border.width:toInput.activeFocus?1:0;border.color:Color.accent}
    onEditingFinished: root.saveInputs()
    Keys.onEscapePressed: root.restoreInputs(true)
  }
}
