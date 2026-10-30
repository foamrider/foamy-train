import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Commons as Commons
import "kit"
import "kit/FoamyPrefs.js" as Prefs
import "Preferences.js" as Schema

// Settings: the foamy page skeleton (back, "Settings", "Saving…", error with
// Retry) with route, bar, departures, refresh and schedule sections.
FoamySettingsPage {
  id: root
  required property var settings
  required property string language
  property var route: null
  property string helperPath: ""
  property bool routeSaving: false
  signal saveRequested(string key, var value)

  function value(key) { return Prefs.value(Schema.fields, root.settings, key) }
  function saveRoute() {
    // Editing search text is not a station change; persist only a selected pair.
    if (!fromSearch.selected || !toSearch.selected || routeSaving) return
    if (route && fromSearch.selected.id === route.from.id && toSearch.selected.id === route.to.id) return
    saveRequested("route", { from: fromSearch.selected, to: toSearch.selected })
  }
  function resetRoute() {
    fromSearch.selectStation(route ? route.from : null)
    toSearch.selectStation(route ? route.to : null)
  }
  onRouteChanged: resetRoute()
  // Choices plus a value saved outside them (from the CLI), in order.
  function choices(list, current) {
    return list.indexOf(current) >= 0 ? list : list.concat([current]).sort(function(a, b) { return a - b })
  }
  function secondsLabel(seconds) {
    return seconds % 60 === 0 ? FoamyI18n.tn("%1 minutes", seconds / 60) : FoamyI18n.tn("%1 seconds", seconds)
  }


  FoamySettingsSection {
    width: parent.width
    title: FoamyI18n.t("Route")
    StationSearch {
      id: fromSearch
      objectName: "fromSearch"
      width: parent.width
      label: FoamyI18n.t("From")
      language: root.language
      helperPath: root.helperPath
      enabled: !root.routeSaving
      onChanged: root.saveRoute()
    }
    StationSearch {
      id: toSearch
      objectName: "toSearch"
      width: parent.width
      label: FoamyI18n.t("To")
      language: root.language
      helperPath: root.helperPath
      enabled: !root.routeSaving
      onChanged: root.saveRoute()
    }
    FoamyAction {
      iconName: "swap"
      label: FoamyI18n.t("Switch direction")
      foreground: FoamyPalette.secondaryText
      focusable: true
      enabled: !root.routeSaving
      onClicked: {
        var from = fromSearch.selected
        fromSearch.selectStation(toSearch.selected)
        toSearch.selectStation(from)
        root.saveRoute()
      }
    }
  }

  FoamySettingsSection {
    width: parent.width
    title: FoamyI18n.t("Bar")
    FoamyToggle {
      objectName: "showBarMinutes"
      width: parent.width
      label: FoamyI18n.t("Show minutes in the bar")
      checked: root.value("showBarMinutes") === true
      enabled: !root.saving
      onClicked: root.saveRequested("showBarMinutes", !checked)
    }
  }

  FoamySettingsSection {
    width: parent.width
    title: FoamyI18n.t("Departures")
    description: FoamyI18n.t("Only direct trains are shown. Times are in Norway.")
    FoamyDropdown {
      objectName: "lookAheadHours"
      width: parent.width
      label: FoamyI18n.t("Show trains in the next")
      value: String(root.value("lookAheadHours"))
      enabled: !root.saving
      options: root.choices(Schema.hourChoices, root.value("lookAheadHours")).map(function(hours) {
        return { value: String(hours), label: FoamyI18n.tn("%1 hours", hours) }
      })
      onChanged: function(v) { root.saveRequested("lookAheadHours", Number(v)) }
    }
  }

  FoamySettingsSection {
    width: parent.width
    title: FoamyI18n.t("Refresh")
    description: FoamyI18n.t("Checks less often while the popup is closed and the next train is more than 30 minutes away. Paused while the screen is locked.")
    FoamyDropdown {
      objectName: "refreshSeconds"
      width: parent.width
      label: FoamyI18n.t("Refresh every")
      value: String(root.value("refreshSeconds"))
      enabled: !root.saving
      options: root.choices(Schema.refreshChoices, root.value("refreshSeconds")).map(function(seconds) {
        return { value: String(seconds), label: root.secondsLabel(seconds) }
      })
      onChanged: function(v) { root.saveRequested("refreshSeconds", Number(v)) }
    }
  }

  FoamySettingsSection {
    width: parent.width
    title: FoamyI18n.t("Schedule")
    description: root.value("scheduleEnabled") ? FoamyI18n.t("Local time. Turn a day off to skip it. Overnight ranges are supported.") : ""
    FoamyToggle {
      objectName: "scheduleEnabled"
      width: parent.width
      label: FoamyI18n.t("Use a weekly schedule")
      checked: root.value("scheduleEnabled") === true
      enabled: !root.saving
      onClicked: root.saveRequested("scheduleEnabled", !checked)
    }
    FoamyDropdown {
      objectName: "scheduleOutsideMode"
      visible: root.value("scheduleEnabled")
      width: parent.width
      label: FoamyI18n.t("Outside the schedule")
      value: root.value("scheduleOutsideMode")
      enabled: !root.saving
      options: [{ value: "mute", label: FoamyI18n.t("Dim") }, { value: "hide", label: FoamyI18n.t("Hide") }]
      onChanged: function(v) { root.saveRequested("scheduleOutsideMode", v) }
    }
    RowLayout {
      visible: root.value("scheduleEnabled")
      width: parent.width
      spacing: FoamyStyle.gap
      Item { Layout.fillWidth: true }
      TrainText {
        Layout.preferredWidth: Style.space(64)
        text: FoamyI18n.t("From")
        color: FoamyPalette.secondaryText
        horizontalAlignment: Text.AlignHCenter
        font.pixelSize: FoamyStyle.font.bodySmall
      }
      TrainText {
        Layout.preferredWidth: Style.space(64)
        text: FoamyI18n.t("To")
        color: FoamyPalette.secondaryText
        horizontalAlignment: Text.AlignHCenter
        font.pixelSize: FoamyStyle.font.bodySmall
      }
    }
    Repeater {
      model: root.value("scheduleEnabled") ? Schema.dayKeys : []
      ScheduleDay {
        required property string modelData
        required property int index
        width: parent.width
        objectName: modelData
        label: FoamyI18n.t(Schema.dayLabels[index])
        fromLabel: FoamyI18n.t("From")
        toLabel: FoamyI18n.t("To")
        value: root.value(modelData)
        enabled: !root.saving
        onChanged: function(range) { root.saveRequested(modelData, range) }
        onInvalid: root.saveRequested(modelData, "invalid")
      }
    }
  }
}
