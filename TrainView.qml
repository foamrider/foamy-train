import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Commons as Commons
import "kit"
import "Model.js" as Model

// Departures: header, the next train (hero), its details and notices, route
// notices, following departures and the footer. Stops for the popup cursor
// are listed in `stops` in visual order; `cursorKey` says which one is lit.
Column {
  id: root
  required property var report
  required property real nowEpoch
  property bool stale: false
  property var departures: []
  property var next: null
  property string language: "en"
  property bool loading: false
  property bool outsideSchedule: false
  property bool routeBusy: false
  property string cursorKey: ""
  // Expanded notice keys (notice detail shown).
  property var expanded: ({})

  // The hero countdown is the plugin's one display numeral; FoamyStyle's
  // type scale stops at 28 (kit issue filed for a display numeral token).
  readonly property int heroNumber: Style.space(52)
  readonly property int heroTime: Style.space(46)
  readonly property int heroUnit: Style.space(20)

  readonly property var following: departures.filter(function(d) { return !root.next || d.id !== root.next.id })
  readonly property bool paused: outsideSchedule
  readonly property bool unconfigured: report.status === "unconfigured"
  readonly property color warningText: FoamyPalette.onSurface(FoamyPalette.warning)

  function formatNumber(value) { return FoamyI18n.number(value, 0) }
  function durationText(minutes) { return Model.duration(minutes, root.language, root.formatNumber) }
  function updatedText() {
    var minutes = Math.max(0, Math.floor((nowEpoch - report.updatedAt) / 60))
    return minutes === 0 ? FoamyI18n.t("Updated just now") : FoamyI18n.tn("Updated %1 minutes ago", minutes)
  }
  function noticeStops(prefix, notices) {
    return notices.filter(function(n) { return n.detail !== "" }).map(function(n) { return prefix + n.id })
  }
  readonly property var stops: {
    var list = []
    if (report.route) list.push("swap")
    list.push("settings")
    if (unconfigured) list.push("choose")
    if (!paused) {
      if (next) list = list.concat(noticeStops("next/", next.notices))
      list = list.concat(noticeStops("route/", report.routeNotices))
      following.forEach(function(d) { list = list.concat(root.noticeStops("dep/" + d.id + "/", d.notices)) })
      list.push("refresh")
    }
    return list
  }

  signal settingsRequested()
  signal swapRequested()
  signal refreshRequested()
  signal stopHovered(string key)
  signal revealRequested(Item item)

  function toggle(key) {
    var state = Object.assign({}, expanded)
    state[key] = !state[key]
    expanded = state
  }
  function activate(key) {
    if (key === "swap") { if (!routeBusy) swapRequested() }
    else if (key === "settings" || key === "choose") settingsRequested()
    else if (key === "refresh") { if (!loading && !routeBusy) refreshRequested() }
    else if (key !== "") toggle(key)
  }

  spacing: 0

  Rectangle {
    width: parent.width
    height: header.height + hero.implicitHeight + FoamyStyle.padding
    color: Qt.alpha(FoamyPalette.text, 0.045)
    topLeftRadius: FoamyStyle.innerRadius(FoamyStyle.radius, FoamyStyle.borderWidth)
    topRightRadius: topLeftRadius

    FoamyHeader {
      id: header
      width: parent.width
      iconName: "train"
      title: FoamyI18n.t("Trains")
      meta: root.report.route ? FoamyI18n.t("%1 → %2", [root.report.route.from.name, root.report.route.to.name]) : ""
      settingsHasCursor: root.cursorKey === "settings"
      onSettingsClicked: root.settingsRequested()
      onSettingsHovered: function(hovered) { if (hovered) root.stopHovered("settings") }
      FoamyAction {
        objectName: "directionAction"
        visible: !!root.report.route
        iconName: "swap"
        tooltipText: FoamyI18n.t("Switch direction")
        foreground: FoamyPalette.secondaryText
        actionEnabled: !root.routeBusy
        hasCursor: root.cursorKey === "swap"
        onHoveredChanged: if (hovered) root.stopHovered("swap")
        onClicked: root.swapRequested()
      }
    }

    Column {
      id: hero
      anchors.top: header.bottom
      x: FoamyStyle.padding
      width: parent.width - FoamyStyle.padding * 2
      spacing: FoamyStyle.gap

      Column {
        visible: !!root.next && !root.paused
        width: parent.width
        spacing: FoamyStyle.rowPadding
        Row {
          objectName: "heroCountdown"
          anchors.horizontalCenter: parent.horizontalCenter
          spacing: FoamyStyle.rowPadding
          TrainText {
            visible: root.stale
            text: root.next ? root.next.expectedTime : ""
            font.pixelSize: root.heroTime
            font.weight: Font.Light
            wrapMode: Text.NoWrap
          }
          Repeater {
            model: root.next && !root.stale ? Model.durationParts(Model.minutes(root.next, root.nowEpoch), root.language) : []
            Row {
              required property var modelData
              spacing: FoamyStyle.gapSmall
              TrainText {
                id: amount
                text: root.formatNumber(parent.modelData.value)
                font.pixelSize: root.heroNumber
                font.weight: Font.Light
                wrapMode: Text.NoWrap
              }
              TrainText {
                text: parent.modelData.unit
                font.pixelSize: root.heroUnit
                anchors.baseline: amount.baseline
                wrapMode: Text.NoWrap
              }
            }
          }
        }
        TrainText {
          width: parent.width
          horizontalAlignment: Text.AlignHCenter
          text: root.report.route ? FoamyI18n.t(root.stale ? "Last known to" : "Next to") + " " + root.report.route.to.name : ""
          font.pixelSize: FoamyStyle.font.iconLarge
        }
        Row {
          anchors.horizontalCenter: parent.horizontalCenter
          spacing: FoamyStyle.gapSmall
          TrainText {
            text: root.next ? root.next.line + " ·" : ""
            color: FoamyPalette.secondaryText
            wrapMode: Text.NoWrap
          }
          TrainText {
            text: root.next ? root.next.aimedTime : ""
            font.strikeout: !!root.next && root.next.delay > 0
            color: FoamyPalette.secondaryText
            wrapMode: Text.NoWrap
          }
          TrainText {
            visible: !!root.next && root.next.delay > 0
            text: root.next ? "→ " + root.next.expectedTime : ""
            color: FoamyPalette.secondaryText
            wrapMode: Text.NoWrap
          }
          TrainText {
            visible: !!root.next && !root.stale
            text: root.next ? "· " + (root.next.delay > 0 ? root.durationText(root.next.delay) + " " + FoamyI18n.t("late")
                                                          : FoamyI18n.t(root.next.realtime ? "On time" : "Scheduled")) : ""
            color: root.next && root.next.delay > 0 ? root.warningText : FoamyPalette.secondaryText
            wrapMode: Text.NoWrap
          }
        }
      }

      Column {
        visible: !root.next || root.paused
        width: parent.width
        spacing: FoamyStyle.gapLarge
        FoamyIcon {
          objectName: root.paused ? "sleepIcon" : "emptyIcon"
          anchors.horizontalCenter: parent.horizontalCenter
          width: Style.space(32)
          height: width
          name: root.paused ? "moon" : "train"
          color: FoamyPalette.secondaryText
        }
        TrainText {
          width: parent.width
          horizontalAlignment: Text.AlignHCenter
          font.pixelSize: FoamyStyle.font.heading
          text: root.unconfigured ? FoamyI18n.t("Choose your stations")
                : root.paused ? FoamyI18n.t("Outside your schedule")
                : root.loading ? FoamyI18n.t("Loading departures…")
                : root.report.status === "error" ? FoamyI18n.t("No departures available")
                : root.departures.length ? FoamyI18n.t("All upcoming trains are cancelled")
                : FoamyI18n.t("No direct trains found")
        }
        TrainText {
          visible: !!root.report.route
          width: parent.width
          horizontalAlignment: Text.AlignHCenter
          color: FoamyPalette.secondaryText
          text: root.report.route ? FoamyI18n.t("To") + " " + root.report.route.to.name : ""
        }
        TrainText {
          visible: root.unconfigured && !root.paused
          width: parent.width
          horizontalAlignment: Text.AlignHCenter
          color: FoamyPalette.mutedText
          font.pixelSize: FoamyStyle.font.bodySmall
          text: FoamyI18n.t("Choose two stations to see direct trains.")
        }
        FoamyAction {
          visible: root.unconfigured
          anchors.horizontalCenter: parent.horizontalCenter
          iconName: "settings"
          label: FoamyI18n.t("Choose stations")
          foreground: Commons.Color.accent
          hasCursor: root.cursorKey === "choose"
          onHoveredChanged: if (hovered) root.stopHovered("choose")
          onClicked: root.settingsRequested()
        }
      }
    }
  }

  Column {
    id: details
    objectName: "departureDetails"
    visible: !root.paused
    width: parent.width
    padding: FoamyStyle.padding
    spacing: FoamyStyle.font.heading
    readonly property real innerWidth: width - padding * 2

    RowLayout {
      visible: !!root.next
      width: details.innerWidth
      Repeater {
        model: root.next ? [
          { label: "Platform", value: root.next.platform },
          { label: "Arrival", value: root.next.arrivalTime },
          { label: "Journey", value: root.durationText(root.next.duration) }
        ] : []
        Column {
          required property var modelData
          Layout.fillWidth: true
          Layout.preferredWidth: 1
          spacing: FoamyStyle.gap
          TrainText {
            width: parent.width
            text: FoamyI18n.t(modelData.label)
            horizontalAlignment: Text.AlignHCenter
            color: FoamyPalette.secondaryText
            font.pixelSize: FoamyStyle.font.bodySmall
          }
          TrainText {
            width: parent.width
            text: modelData.value
            horizontalAlignment: Text.AlignHCenter
            font.pixelSize: FoamyStyle.font.heading
          }
        }
      }
    }

    Rectangle {
      visible: root.stale || root.report.error !== ""
      width: details.innerWidth
      height: warningLabel.implicitHeight + FoamyStyle.rowPadding * 2
      radius: FoamyStyle.radius
      color: Qt.alpha(FoamyPalette.warning, 0.08)
      TrainText {
        id: warningLabel
        x: FoamyStyle.rowPadding
        y: FoamyStyle.rowPadding
        width: parent.width - FoamyStyle.rowPadding * 2
        color: root.warningText
        Accessible.role: Accessible.AlertMessage
        text: (root.stale ? FoamyI18n.t("Cached times; live predictions unavailable.") + (root.report.error ? "\n" : "") : "")
          + (root.report.error ? FoamyI18n.t(root.report.error) : "")
      }
    }

    Column {
      visible: !!root.next && root.next.notices.length > 0
      width: details.innerWidth
      spacing: FoamyStyle.gapTiny
      Repeater {
        model: root.next ? root.next.notices : []
        Notice {
          required property var modelData
          width: parent.width
          notice: modelData
          filled: true
          cursorKey: "next/" + modelData.id
          view: root
        }
      }
    }

    Column {
      visible: root.report.routeNotices.length > 0
      width: details.innerWidth
      spacing: FoamyStyle.gapSmall
      TrainText {
        text: FoamyI18n.t("Route notices")
        color: FoamyPalette.secondaryText
        font.pixelSize: FoamyStyle.font.bodySmall
      }
      Repeater {
        model: root.report.routeNotices
        Notice {
          required property var modelData
          width: parent.width
          notice: modelData
          filled: true
          cursorKey: "route/" + modelData.id
          view: root
        }
      }
    }

    Column {
      visible: root.following.length > 0
      width: details.innerWidth
      spacing: FoamyStyle.rowPadding
      TrainText {
        text: FoamyI18n.t(root.stale ? "Last known departures" : root.following.some(function(d) {
          return root.next && d.expected < root.next.expected
        }) ? "Other departures" : "Following departures")
        color: FoamyPalette.secondaryText
        font.pixelSize: FoamyStyle.font.bodySmall
      }
      Repeater {
        model: root.following
        DepartureCard {
          required property var modelData
          width: parent.width
          departure: modelData
          destination: root.report.route ? root.report.route.to.name : ""
          nowEpoch: root.nowEpoch
          language: root.language
          stale: root.stale
          view: root
        }
      }
    }

    Rectangle {
      width: details.innerWidth
      height: 1
      color: FoamyPalette.divider
    }

    RowLayout {
      width: details.innerWidth
      spacing: FoamyStyle.gap
      TrainText {
        text: "Entur"
        color: FoamyPalette.secondaryText
        font.pixelSize: FoamyStyle.font.bodySmall
        wrapMode: Text.NoWrap
      }
      TrainText {
        Layout.fillWidth: true
        horizontalAlignment: Text.AlignRight
        visible: root.report.updatedAt > 0
        text: root.report.updatedAt > 0 ? root.updatedText() : ""
        color: FoamyPalette.secondaryText
        font.pixelSize: FoamyStyle.font.bodySmall
      }
      FoamyAction {
        id: refreshAction
        objectName: "refreshAction"
        iconName: "refresh-cw"
        tooltipText: FoamyI18n.t(root.loading ? "Refreshing…" : "Refresh")
        foreground: FoamyPalette.secondaryText
        spinning: root.loading
        actionEnabled: !root.loading && !root.routeBusy
        hasCursor: root.cursorKey === "refresh"
        onHasCursorChanged: if (hasCursor) root.revealRequested(refreshAction)
        onHoveredChanged: if (hovered) root.stopHovered("refresh")
        onClicked: root.refreshRequested()
      }
    }
  }
}
