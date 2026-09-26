import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import qs.Ui
import qs.Commons
import "Preferences.js" as Preferences

Column {
  id: root
  required property var settings
  required property string language
  property var route: null
  property string helperPath: ""
  property bool routeSaving: false
  signal applyRoute(var route)
  function saveRoute() {
    // Editing search text is not a station change; persist only a selected pair.
    if (!fromSearch.selected || !toSearch.selected || routeSaving) return
    if (route && fromSearch.selected.id === route.from.id && toSearch.selected.id === route.to.id) return
    applyRoute({from: fromSearch.selected, to: toSearch.selected})
  }
  function resetRoute() {
    fromSearch.selectStation(route ? route.from : null)
    toSearch.selectStation(route ? route.to : null)
  }
  property bool saving: false
  property string error: ""
  property alias backTarget: backButton
  signal save(string key, var value)
  signal back
  signal clearError
  function tr(label) {
    return Preferences.text(label, language)
  }
  function focusBack() {
    backButton.forceActiveFocus()
  }
  readonly property color secondary: Qt.tint(Color.popups.background, Qt.alpha(Color.popups.text, 0.7))
  padding: Style.space(20)
  spacing: Style.space(14)
  RowLayout {
    width: root.width - root.padding * 2
    TrainAction {
      id: backButton
      iconName: "arrow-left"
      foreground: root.secondary
      tooltipText: root.tr("Back")
      onClicked: root.back()
    }
    Text {
      text: root.tr("Settings")
      color: root.secondary
      font.family: "sans-serif"
      font.pixelSize: Style.space(13)
      Layout.fillWidth: true
    }
    Text {
      visible: root.saving || root.routeSaving
      text: root.tr("Saving…")
      color: root.secondary
      font.family: "sans-serif"
      font.pixelSize: Style.space(11)
    }
  }
  Text {
    width: root.width - root.padding * 2
    visible: root.error !== ""
    text: root.error
    textFormat: Text.PlainText
    wrapMode: Text.WordWrap
    color: Color.urgent
    font.family: "sans-serif"
    font.pixelSize: Style.space(12)
    Accessible.role: Accessible.AlertMessage
  }
  StationSearch {
    id: fromSearch
    objectName: "fromSearch"
    width: root.width - root.padding * 2
    label: root.tr("From")
    language: root.language
    helperPath: root.helperPath
    enabled: !root.routeSaving
    onChanged: root.saveRoute()
  }
  StationSearch {
    id: toSearch
    objectName: "toSearch"
    width: root.width - root.padding * 2
    label: root.tr("To")
    language: root.language
    helperPath: root.helperPath
    enabled: !root.routeSaving
    onChanged: root.saveRoute()
  }
  RowLayout {
    width: root.width - root.padding * 2
    TrainAction {
      iconName: "swap"
      label: root.tr("Switch direction")
      foreground: root.secondary
      enabled: !root.routeSaving
      onClicked: {
        var from = fromSearch.selected
        fromSearch.selectStation(toSearch.selected)
        toSearch.selectStation(from)
        root.saveRoute()
      }
    }
    Item {
      Layout.fillWidth: true
    }
  }
  Rectangle {
    width: root.width - root.padding * 2
    height: 1
    color: Qt.alpha(Color.popups.text, 0.14)
  }
  Repeater {
    model: Preferences.fields.filter(function(f) { return f.type !== "string" })
    Column {
      id: fieldRow
      objectName: modelData.key
      required property var modelData
      readonly property var current: Preferences.value(root.settings, modelData.key)
      width: root.width - root.padding * 2
      visible: modelData.key !== "scheduleOutsideMode" || Preferences.value(root.settings, "scheduleEnabled")
      enabled: !root.saving
      opacity: enabled ? 1 : 0.55
      TrainDropdown {
        width: parent.width
        visible: fieldRow.modelData.type === "enum"
        label: root.tr(fieldRow.modelData.label)
        fontFamily: "sans-serif"
        value: String(fieldRow.current)
        options: (fieldRow.modelData.options || []).map(function (v) {
          return {
            value: v,
            label: root.tr(Preferences.optionLabel(v))
          }
        })
        onChanged: function (value) {
          root.save(fieldRow.modelData.key, value)
        }
      }
      Toggle {
        width: parent.width
        visible: fieldRow.modelData.type === "boolean"
        implicitHeight: Style.space(36)
        color: "transparent"
        borderSpec: activeFocus ? Border.flat(Color.accent, 1) : Border.none()
        radius: Style.space(7)
        fontFamily: "sans-serif"
        foreground: Color.popups.text
        titleSize: Style.space(13)
        label: root.tr(fieldRow.modelData.label)
        checked: fieldRow.current === true
        onClicked: root.save(fieldRow.modelData.key, !checked)
      }
      RowLayout {
        width: parent.width
        visible: fieldRow.modelData.type === "integer"
        spacing: Style.space(12)
        Text {
          Layout.fillWidth: true
          text: root.tr(fieldRow.modelData.label)
          wrapMode: Text.WordWrap
          color: Color.popups.text
          font.family: "sans-serif"
          font.pixelSize: Style.space(13)
        }
        Controls.TextField {
          id: input
          Layout.preferredWidth: Style.space(68)
          implicitHeight: Style.space(34)
          text: String(fieldRow.current)
          placeholderTextColor: Qt.alpha(Color.popups.text, 0.5)
          selectByMouse: true
          color: Color.popups.text
          font.family: "sans-serif"
          font.pixelSize: Style.space(12)
          padding: Style.space(7)
          Accessible.name: root.tr(fieldRow.modelData.label)
          background: Rectangle {
            radius: Style.space(7)
            color: Qt.alpha(Color.popups.text, 0.055)
            border.width: input.activeFocus ? 1 : 0
            border.color: Color.accent
          }
          onTextEdited: root.clearError()
          onEditingFinished: {
            if (!visible)
              return
            var next = text.trim() === "" ? NaN : Number(text)
            if (next !== fieldRow.current)
              root.save(fieldRow.modelData.key, next)
          }
          Keys.onEscapePressed: {
            text = String(fieldRow.current)
            root.back()
          }
          HoverHandler {
            id: numberHover
          }
          PanelToolTip {
            visible: numberHover.hovered || input.activeFocus
            text: fieldRow.modelData.type === "string" ? root.tr("Off") + " / 00:00–24:00" : fieldRow.modelData.min
                                                         + "–" + fieldRow.modelData.max
            fontFamily: "sans-serif"
          }
        }
      }
    }
  }
  Column {
    visible: Preferences.value(root.settings, "scheduleEnabled")
    width: root.width - root.padding * 2
    spacing: Style.space(8)
    RowLayout {
      width: parent.width
      Item {Layout.fillWidth:true}
      TrainText {Layout.preferredWidth:Style.space(58);text:root.tr("From");color:root.secondary;horizontalAlignment:Text.AlignHCenter;font.pixelSize:Style.space(11)}
      TrainText {Layout.preferredWidth:Style.space(58);text:root.tr("To");color:root.secondary;horizontalAlignment:Text.AlignHCenter;font.pixelSize:Style.space(11)}
    }
    Repeater {
      model: Preferences.fields.filter(function(f) {return f.type === "string"})
      ScheduleDay {
        required property var modelData
        width: parent.width
        objectName: modelData.key
        label: root.tr(modelData.label)
        fromLabel: root.tr("From")
        toLabel: root.tr("To")
        value: Preferences.value(root.settings, modelData.key)
        enabled: !root.saving
        onChanged: function(value) {root.save(modelData.key,value)}
        onInvalid: root.save(modelData.key, "invalid")
      }
    }
  }
}
