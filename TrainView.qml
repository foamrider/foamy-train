import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Preferences.js" as Preferences
import "Model.js" as Model

Column {
  id: root
  required property var report
  required property real nowEpoch
  property string language: "en"
  property bool loading: false
  property bool offline: false
  property bool outsideSchedule: false
  property bool routeBusy: false
  readonly property bool stale: Model.stale(report, nowEpoch, offline)
  readonly property var departures: Model.upcoming(report, nowEpoch, stale)
  readonly property var next: Model.next(departures)
  readonly property var following: departures.filter(function (d) {
    return !root.next || d.id !== root.next.id
  })
  readonly property bool paused: outsideSchedule
  readonly property color secondary: Qt.tint(Color.popups.background, Qt.alpha(Color.popups.text, 0.7))
  readonly property color warning: Color.popups.background.hslLightness > 0.5 ? "#86601b" : "#d7b56d"
  property alias settingsTarget: settingsAction
  signal settingsRequested
  signal swapRequested
  signal refreshRequested
  function tr(s) {
    return Preferences.text(s, language)
  }
  spacing: 0
  Rectangle {
    width: parent.width
    height: hero.implicitHeight + Style.space(36)
    color: Qt.alpha(Color.popups.text, 0.045)
    Column {
      id: hero
      x: Style.space(20)
      y: Style.space(18)
      width: parent.width - Style.space(40)
      spacing: Style.space(14)
      RowLayout {
        width: parent.width
        Item {
          width: root.report.route ? Style.space(60) : Style.space(28)
          height: Style.space(28)
        }
        TrainText {
          Layout.fillWidth: true
          horizontalAlignment: Text.AlignHCenter
          text: root.tr("Trains") + (root.report.route ? " · " + root.report.route.from.name : "")
          color: root.secondary
          font.pixelSize: Style.space(14)
        }
        TrainAction {
          id: directionAction
          objectName: "directionAction"
          visible: !!root.report.route
          iconName: "swap"
          tooltipText: root.tr("Switch direction")
          foreground: root.secondary
          enabled: !root.routeBusy
          onClicked: root.swapRequested()
        }
        TrainAction {
          id: settingsAction
          tooltipText: root.tr("Settings")
          foreground: root.secondary
          onClicked: root.settingsRequested()
        }
      }
      Column {
        visible: !!root.next && !root.paused
        width: parent.width
        spacing: Style.space(10)
        Row {
          anchors.horizontalCenter: parent.horizontalCenter
          spacing: Style.space(5)
          TrainText {
            id: countdown
            text: root.next ? (root.stale ? root.next.expectedTime : String(Model.minutes(root.next, root.nowEpoch))) :
                              ""
            font.pixelSize: Style.space(root.stale ? 46 : 52)
            font.weight: Font.Light
          }
          TrainText {
            visible: !root.stale
            text: "min"
            font.pixelSize: Style.space(20)
            anchors.baseline: countdown.baseline
          }
        }
        RowLayout {
          width: parent.width
          spacing: Style.space(4)
          Item {
            Layout.fillWidth: true
          }
          TrainText {
            Layout.maximumWidth: hero.width - Style.space(40)
            horizontalAlignment: Text.AlignHCenter
            text: root.report.route ? root.tr(root.stale ? "Last known to" : "Next to") + " " + root.report.route.to.name :
                                      ""
            font.pixelSize: Style.space(18)
          }
          Item {
            Layout.fillWidth: true
          }
        }
        Row {
          anchors.horizontalCenter: parent.horizontalCenter
          spacing: Style.space(4)
          TrainText {
            text: root.next ? root.next.line + " ·" : ""
            color: root.secondary
          }
          TrainText {
            text: root.next ? root.next.aimedTime : ""
            font.strikeout: !!root.next && root.next.delay > 0
            color: root.secondary
          }
          TrainText {
            visible: !!root.next && root.next.delay > 0
            text: root.next ? "→ " + root.next.expectedTime : ""
            color: root.secondary
          }
          TrainText {
            visible: !!root.next && !root.stale
            text: root.next ? "· " + (root.next.delay > 0 ? root.next.delay + " " + root.tr("min late") : root.tr(
                                                              root.next.realtime ? "On time" : "Scheduled")) : ""
            color: root.next && root.next.delay > 0 ? root.warning : root.secondary
          }
        }
      }
      Column {
        visible: !root.next || root.paused
        width: parent.width
        spacing: Style.space(16)
        OpticalGlyph {
          objectName: "sleepIcon"
          visible: root.paused
          anchors.horizontalCenter: parent.horizontalCenter
          width: Style.space(80)
          height: width
          text: "󰒲"
          fontFamily: Style.font.family
          fontSize: Style.space(64)
          color: root.secondary
        }
        TrainIcon {
          visible: !root.paused
          anchors.horizontalCenter: parent.horizontalCenter
          width: Style.space(32)
          height: width
          name: "train"
          color: root.secondary
        }
        TrainText {
          width: parent.width
          horizontalAlignment: Text.AlignHCenter
          font.pixelSize: Style.space(17)
          text: root.report.status === "unconfigured" ? root.tr("Choose your stations") : root.paused ? root.tr(
                                                                                                          "Outside your schedule") :
                                                                                                        root.loading
                                                                                                        ? root.tr(
                                                                                                            "Loading departures…") :
                                                                                                          root.report.status
                                                                                                          === "error"
                                                                                                          ? root.tr(
                                                                                                              "No departures available.") :
                                                                                                            root.departures.length
                                                                                                            ? root.tr(
                                                                                                                "All upcoming trains are cancelled.") :
                                                                                                              root.tr("No direct trains found.")
        }
        TrainText {
          visible: !!root.report.route
          width: parent.width
          horizontalAlignment: Text.AlignHCenter
          color: root.secondary
          text: root.report.route ? root.tr("To") + " " + root.report.route.to.name : ""
        }
        TrainText {
          visible: root.report.status === "unconfigured" && !root.paused
          width: parent.width
          horizontalAlignment: Text.AlignHCenter
          color: root.secondary
          text: root.tr("Choose two stations to see direct trains.")
        }
        RowLayout {
          width: parent.width
          Item {
            Layout.fillWidth: true
          }
          TrainAction {
            visible: root.report.status === "unconfigured"
            iconName: "settings"
            label: root.tr("Choose stations")
            foreground: Color.accent
            onClicked: root.settingsRequested()
          }
          Item {
            Layout.fillWidth: true
          }
        }
      }
    }
  }
  Column {
    objectName: "departureDetails"
    visible: !root.paused
    width: parent.width
    padding: Style.space(20)
    spacing: Style.space(16)
    RowLayout {
      visible: !!root.next && !root.paused
      width: parent.width - parent.padding * 2
      Repeater {
        model: root.next ? [
                             {
                               label: "Platform",
                               value: root.next.platform
                             },
                             {
                               label: "Arrival",
                               value: root.next.arrivalTime
                             },
                             {
                               label: "Journey",
                               value: root.next.duration + " min"
                             }
                           ] : []
        Column {
          required property var modelData
          Layout.fillWidth: true
          Layout.preferredWidth: 1
          spacing: Style.space(8)
          TrainText {
            width: parent.width
            text: root.tr(modelData.label)
            horizontalAlignment: Text.AlignHCenter
            color: root.secondary
            font.pixelSize: Style.space(11)
          }
          TrainText {
            width: parent.width
            text: modelData.value
            horizontalAlignment: Text.AlignHCenter
            font.pixelSize: Style.space(16)
          }
        }
      }
    }
    Rectangle {
      visible: root.stale || root.report.error !== ""
      width: parent.width - parent.padding * 2
      height: warningText.implicitHeight + Style.space(20)
      radius: Style.space(8)
      color: Qt.alpha(root.warning, 0.08)
      TrainText {
        id: warningText
        x: Style.space(10)
        y: Style.space(10)
        width: parent.width - Style.space(20)
        color: root.warning
        text: (root.stale ? root.tr("Cached times; live predictions unavailable.") + "\n" : "") + root.tr(
                root.report.error)
      }
    }
    Column {
      visible: !!root.next && root.next.notices.length > 0
      width: parent.width - parent.padding * 2
      spacing: Style.space(2)
      Repeater {
        model: root.next ? root.next.notices : []
        Notice {
          required property var modelData
          width: parent.width
          notice: modelData
          filled: true
        }
      }
    }
    Column {
      visible: root.report.routeNotices.length > 0
      width: parent.width - parent.padding * 2
      spacing: Style.space(6)
      TrainText {
        text: root.tr("Route notices")
        color: root.secondary
      }
      Repeater {
        model: root.report.routeNotices
        Notice {
          required property var modelData
          width: parent.width
          notice: modelData
          filled: true
        }
      }
    }
    Column {
      visible: root.following.length > 0
      width: parent.width - parent.padding * 2
      spacing: Style.space(10)
      TrainText {
        text: root.tr(root.stale ? "Last known departures" : root.following.some(function (d) {
          return root.next && d.expected < root.next.expected
        }) ? "Other departures" : "Following departures")
        color: root.secondary
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
        }
      }
    }
    Rectangle {
      width: parent.width - parent.padding * 2
      height: 1
      color: Qt.alpha(Color.popups.text, 0.14)
    }
    RowLayout {
      width: parent.width - parent.padding * 2
      spacing: Style.space(8)
      TrainText {
        text: "Entur"
        color: root.secondary
        font.pixelSize: Style.space(11)
      }
      Item {
        Layout.fillWidth: true
      }
      TrainText {
        Layout.fillWidth: true
        horizontalAlignment: Text.AlignRight
        visible: root.report.updatedAt > 0
        text: Preferences.updatedText(root.report.updatedAt, root.nowEpoch, root.language)
        color: root.secondary
        font.pixelSize: Style.space(11)
      }
      TrainAction {
        iconName: "refresh-cw"
        tooltipText: root.tr(root.loading ? "Refreshing…" : "Refresh")
        foreground: root.secondary
        spinning: root.loading
        enabled: !root.loading && !root.routeBusy
        onClicked: root.refreshRequested()
      }
    }
  }
}
