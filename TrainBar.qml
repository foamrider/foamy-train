import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model

Row {
  id: root
  property color foreground: Color.foreground
  property string iconFontFamily: Style.font.family
  property real fontSize: Style.font.body
  property bool showMinutes: true
  property bool withinSchedule: true
  property bool vertical: false
  property bool stale: false
  property var next: null
  property var departures: []
  property var routeNotices: []
  property real nowEpoch: 0
  readonly property bool live: withinSchedule && !stale
  readonly property bool hasCancellation: departures.some(function(d) {return d.cancelled})
  readonly property bool hasWarning: routeNotices.some(function(n) {return n.kind === "warning"})
    || departures.some(function(d) {return d.notices.some(function(n) {return n.kind === "warning"})})
  readonly property bool hasInfo: routeNotices.some(function(n) {return n.kind === "info"})
    || departures.some(function(d) {return d.notices.some(function(n) {return n.kind === "info"})})
  readonly property bool hasDelay: departures.some(function(d) {return !d.cancelled && d.delay > 0})
  readonly property color warning: Color.background.hslLightness > 0.5 ? "#86601b" : "#d7b56d"
  // The countdown color describes only the next train. Other affected departures use a notice marker.
  readonly property bool otherDelay: departures.some(function(d) {return !d.cancelled && d.delay > 0 && (!root.next || d.id !== root.next.id)})
  readonly property string noticeIcon: !live ? "" : hasCancellation ? "cancelled"
    : hasWarning || otherDelay || (hasDelay && (!showMinutes || vertical)) ? "warning" : hasInfo ? "info" : ""
  spacing: Style.space(2)
  OpticalGlyph {
    width: Style.bar.iconCanvas
    height: width
    text: "󰔬"
    fontFamily: root.iconFontFamily
    fontSize: Style.font.body
    color: root.vertical && root.live && root.noticeIcon !== "" ? (root.noticeIcon === "cancelled" ? Color.urgent : root.noticeIcon === "info" ? Color.accent : root.warning) : root.foreground
  }
  Text {
    objectName: "barCountdown"
    visible: root.showMinutes && !root.vertical && root.withinSchedule
    anchors.verticalCenter: parent.verticalCenter
    text: root.stale ? "—" : root.next ? Model.minutes(root.next, root.nowEpoch) + " min" : "—"
    color: root.live && root.next && root.next.delay > 0 ? root.warning : root.foreground
    font.family: "sans-serif"
    font.pixelSize: root.fontSize
  }
  TrainIcon {
    objectName: "barNotice"
    visible: root.noticeIcon !== "" && !root.vertical
    anchors.verticalCenter: parent.verticalCenter
    width: Style.space(14)
    height: width
    name: root.noticeIcon
    color: root.noticeIcon === "cancelled" ? Color.urgent : root.noticeIcon === "info" ? Color.accent : root.warning
  }
}
