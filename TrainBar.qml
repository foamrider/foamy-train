import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "kit"
import "Model.js" as Model

Row {
  id: root
  property color foreground: Commons.Color.foreground
  property string iconFontFamily: Style.font.family
  property real fontSize: Style.font.body
  property bool showMinutes: true
  property string language: "en"
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
    // Departure information belongs to the train shown by the countdown.
    || (next !== null && next.notices.some(function(n) {return n.kind === "info"}))
  readonly property bool hasDelay: departures.some(function(d) {return !d.cancelled && d.delay > 0})
  // Theme yellow on the bar surface (the bar has its own background).
  readonly property color warning: FoamyPalette.warning
  // The countdown color describes only the next train. Other affected departures use a notice marker.
  readonly property bool otherDelay: departures.some(function(d) {return !d.cancelled && d.delay > 0 && (!root.next || d.id !== root.next.id)})
  readonly property string noticeIcon: !live ? "" : hasCancellation ? "cancelled"
    : hasWarning || otherDelay || (hasDelay && (!showMinutes || vertical)) ? "warning" : hasInfo ? "info" : ""
  function noticeColor(icon) {
    return icon === "cancelled" ? Commons.Color.urgent : icon === "info" ? Commons.Color.accent : root.warning
  }
  spacing: Style.space(4)
  OpticalGlyph {
    id: trainGlyph
    width: Style.bar.iconCanvas
    height: width
    text: "󰔬"
    fontFamily: root.iconFontFamily
    fontSize: Style.font.body
    color: root.vertical && root.live && root.noticeIcon !== "" ? root.noticeColor(root.noticeIcon) : root.foreground
  }
  Text {
    objectName: "barCountdown"
    visible: root.showMinutes && !root.vertical && root.withinSchedule
    anchors.verticalCenter: parent.verticalCenter
    text: root.stale || !root.next ? "—" : Model.duration(Model.minutes(root.next, root.nowEpoch), root.language, function(v) { return FoamyI18n.number(v, 0) })
    textFormat: Text.PlainText
    color: root.live && root.next && root.next.delay > 0 ? root.warning : root.foreground
    font.family: FoamyStyle.fontFamily
    font.pixelSize: root.fontSize
  }
  FoamyIcon {
    objectName: "barNotice"
    visible: root.noticeIcon !== "" && !root.vertical
    anchors.verticalCenter: parent.verticalCenter
    // Align the SVG's visible strokes with the text rather than its line box.
    anchors.verticalCenterOffset: -Style.space(1)
    width: trainGlyph.fontSize
    height: width
    name: root.noticeIcon || "info"
    color: root.noticeColor(root.noticeIcon)
  }
}
