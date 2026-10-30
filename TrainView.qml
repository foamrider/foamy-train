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
    if (!paused && !unconfigured) {
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

  // Header and footer stops scroll into view here; notices reveal themselves.
  onCursorKeyChanged: {
    var item = cursorKey === "swap" || cursorKey === "settings" ? band
      : cursorKey === "choose" ? chooseAction
      : cursorKey === "refresh" ? refreshAction : null
    if (item) revealRequested(item)
  }

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

  FoamyHeroBand {
    id: band
    objectName: "heroBand"
    width: parent.width
    iconName: "train"
    title: FoamyI18n.t("Trains")
    meta: root.report.route ? FoamyI18n.t("%1 → %2", [root.report.route.from.name, root.report.route.to.name]) : ""
    settingsHasCursor: root.cursorKey === "settings"
    onSettingsClicked: root.settingsRequested()
    onSettingsHovered: function(hovered) { if (hovered) root.stopHovered("settings") }
    trailing: [
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
    ]

    // Hero: the next departure (countdown, destination, line and time), or
    // the empty / paused state.
    Column {
      id: hero
      Layout.fillWidth: true
      spacing: FoamyStyle.gap

      Column {
        visible: !!root.next && !root.paused
        width: parent.width
        spacing: FoamyStyle.gapSmall
        Row {
          objectName: "heroCountdown"
          anchors.horizontalCenter: parent.horizontalCenter
          spacing: FoamyStyle.rowPadding
          TrainText {
            visible: root.stale
            text: root.next ? root.next.expectedTime : ""
            font.pixelSize: FoamyStyle.font.numeralCompact
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
                font.pixelSize: FoamyStyle.font.numeral
                font.weight: Font.Light
                wrapMode: Text.NoWrap
              }
              TrainText {
                text: parent.modelData.unit
                font.pixelSize: FoamyStyle.font.display
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
          font.pixelSize: FoamyStyle.font.heading
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
        spacing: FoamyStyle.gap
        FoamyIcon {
          objectName: root.paused ? "sleepIcon" : "emptyIcon"
          anchors.horizontalCenter: parent.horizontalCenter
          width: Style.space(28)
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
          id: chooseAction
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

  // With no details below, a strip of plain surface keeps the band's square
  // bottom off the card's rounded corners (the band rounds only its top).
  Item {
    visible: !details.visible
    width: parent.width
    height: FoamyStyle.radius
  }

  Column {
    id: details
    objectName: "departureDetails"
    // Nothing to refresh before stations are chosen.
    visible: !root.paused && !root.unconfigured
    width: parent.width
    padding: FoamyStyle.padding
    topPadding: FoamyStyle.sectionGap
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
        onHoveredChanged: if (hovered) root.stopHovered("refresh")
        onClicked: root.refreshRequested()
      }
    }
  }
}
