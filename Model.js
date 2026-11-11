// The report contract (native/src/entur.rs, the same numbers): the popup
// builds every station row and notice eagerly (QML Repeaters), so a reply
// keeps at most these many, deduplicated by id before they count, and text of
// at most these many code points, cut with a trailing "…". The helper already
// applies them; this keeps the popup bounded whatever the reply says.
var limits = {stations:8, departures:6, notices:3, routeNotices:5, summary:200, detail:600, scope:100, id:100, code:20, label:160}
// `text` in at most `limit` code points; cut text ends in "…" (entur.rs clip).
function clip(text, limit) {
  if (text.length <= limit) return text
  var head = "", count = 0
  for (var c of text) {
    if (++count > limit) return head + "…"
    if (count < limit) head += c
  }
  return text
}
function codePoints(text) { var n = 0; for (var c of text) n++; return n }
function blank(status) { return {status:status || "loading",route:null,departures:[],routeNotices:[],updatedAt:0,stale:false,error:"",errorCode:""} }
function validStation(s) { return s && typeof s.name==="string" && s.name.trim().length>0 && codePoints(s.name)<=160 && !/[\x00-\x1f]/.test(s.name) && typeof s.id==="string" && /^NSR:StopPlace:\d+$/.test(s.id) }
function route(value) {
  if (value === undefined || value === null) return null
  if (!value || !validStation(value.from) || !validStation(value.to)) throw Error("Select both stations from search results.")
  if (value.from.id === value.to.id) throw Error("Choose two different stations.")
  return {from:{id:value.from.id,name:value.from.name.trim()},to:{id:value.to.id,name:value.to.name.trim()}}
}
// A station search reply's stations: the first `limits.stations` distinct
// ids, labels cut. Throws on an invalid one.
function stations(data) {
  if (!data || !Array.isArray(data.stations)) throw Error("invalid stations")
  var out = []
  for (var i = 0; i < data.stations.length && out.length < limits.stations; i++) {
    var s = data.stations[i]
    if (!validStation(s) || typeof s.label !== "string") throw Error("invalid stations")
    if (out.some(function(o) { return o.id === s.id })) continue
    out.push({id:s.id, name:s.name, label:clip(s.label, limits.label)})
  }
  return out
}
function validNotice(n) { return n && typeof n.id==="string" && typeof n.summary==="string" && typeof n.detail==="string" && typeof n.scopeLabel==="string" && ["info","warning"].indexOf(n.kind)>=0 }
function finite(n) { return typeof n==="number" && isFinite(n) }
// The first `limit` notices of `list` with distinct (cut) ids, fields cut.
// state.omitted is set when a further distinct one is left out.
function boundNotices(list, limit, state) {
  var out = []
  for (var i = 0; i < list.length; i++) {
    var n = list[i], id = clip(n.id, limits.id)
    if (out.some(function(o) { return o.id === id })) continue
    if (out.length === limit) { state.omitted = true; break }
    out.push({id:id, summary:clip(n.summary, limits.summary), detail:clip(n.detail, limits.detail), kind:n.kind,
              scopeLabel:clip(n.scopeLabel, limits.scope)})
  }
  return out
}
function parse(text) {
  var r=JSON.parse(text)
  if (!r || ["ok","stale","error","ready","unconfigured"].indexOf(r.status)<0 || !Array.isArray(r.departures) || !Array.isArray(r.routeNotices)
      || !finite(r.updatedAt) || typeof r.stale!=="boolean" || typeof r.error!=="string" || typeof r.errorCode!=="string"
      || (r.noticesOmitted!==undefined && typeof r.noticesOmitted!=="boolean")
      || (r.route!==null && (!validStation(r.route.from)||!validStation(r.route.to)))) throw Error("Invalid train response")
  if (!r.routeNotices.every(validNotice) || !r.departures.every(function(d) {
    return d && typeof d.id==="string" && typeof d.line==="string" && typeof d.platform==="string"
      && [d.aimed,d.expected,d.arrival,d.delay,d.duration].every(finite)
      && [d.aimedTime,d.expectedTime,d.arrivalTime].every(function(t){return typeof t==="string" && /^\d{2}:\d{2}$/.test(t)})
      && typeof d.realtime==="boolean" && typeof d.cancelled==="boolean" && Array.isArray(d.notices) && d.notices.every(validNotice)
  })) throw Error("Invalid train response")
  // Within the contract, the same cut as entur.rs bound_report: departures
  // in their order, deduplicated by (cut) id.
  var state = {omitted: r.noticesOmitted === true}, departures = []
  for (var i = 0; i < r.departures.length && departures.length < limits.departures; i++) {
    var d = r.departures[i], id = clip(d.id, limits.id)
    if (departures.some(function(o) { return o.id === id })) continue
    departures.push(Object.assign({}, d, {id:id, line:clip(d.line, limits.code), platform:clip(d.platform, limits.code),
                                          notices:boundNotices(d.notices, limits.notices, state)}))
  }
  var bounded = Object.assign({}, r, {departures:departures, routeNotices:boundNotices(r.routeNotices, limits.routeNotices, state)})
  if (state.omitted) bounded.noticesOmitted = true
  return bounded
}
// Cached times count as stale once two polls in a row are overdue, so a long
// refresh interval never turns the bar "stale" between ordinary polls.
var minimumStaleSeconds = 180
function staleAfter(intervalSeconds) {
  var interval = finite(intervalSeconds) && intervalSeconds > 0 ? intervalSeconds : 60
  return Math.max(minimumStaleSeconds, 2 * interval + 30)
}
function stale(report,now,offline,intervalSeconds) { return report.updatedAt>0 && (report.stale || offline || now-report.updatedAt>staleAfter(intervalSeconds)) }

// Adaptive Entur polling. The configured interval applies while someone is
// looking (a popup is open) and while the next train is close; far-off or
// missing departures are checked less often. Locked sessions do not fetch at
// all (the caller only probes the lock, at lockSeconds).
var nearSeconds = 30 * 60
var soonSeconds = 2 * 3600
var soonPollSeconds = 5 * 60
var farPollSeconds = 15 * 60
function pollInterval(baseSeconds, state) {
  var base = finite(baseSeconds) ? Math.max(30, Math.min(900, Math.round(baseSeconds))) : 60
  state = state || {}
  if (state.locked) return state.lockSeconds || 60
  if (state.open) return base
  var report = state.report || blank("loading")
  // No data yet: keep the configured pace until the first answer arrives.
  if (!report.updatedAt) return report.status === "error" ? Math.max(base, soonPollSeconds) : base
  var now = state.now || 0
  var departures = upcoming(report, now, false)
  // Every cached train has left: the list needs replacing now.
  if (report.departures.length > 0 && departures.length === 0) return base
  var first = next(departures) || departures[0]
  if (!first) return Math.max(base, farPollSeconds)
  var away = first.expected - now
  if (away <= nearSeconds) return base
  if (away <= soonSeconds) return Math.max(base, soonPollSeconds)
  return Math.max(base, farPollSeconds)
}
function upcoming(report,now,isStale) { return isStale ? report.departures : report.departures.filter(function(d){return Math.max(d.expected,d.aimed)>=now-30}) }
function next(departures) { return departures.find(function(d){return !d.cancelled}) || null }
function minutes(d,now) { return Math.max(0,Math.ceil((d.expected-now)/60)) }
function durationParts(totalMinutes, language) {
  var total = Math.max(0, Math.floor(totalMinutes)), hours = Math.floor(total / 60), minutes = total % 60
  var parts = []
  if (hours) parts.push({value:hours, unit:language === "no" ? "t" : "h"})
  if (minutes || !hours) parts.push({value:minutes, unit:"min"})
  return parts
}
function duration(totalMinutes, language, format) {
  format = format || String
  return durationParts(totalMinutes, language).map(function(part) {return format(part.value) + " " + part.unit}).join(" ")
}
if(typeof module!=="undefined")module.exports={limits:limits,clip:clip,stations:stations,blank:blank,parse:parse,stale:stale,staleAfter:staleAfter,pollInterval:pollInterval,upcoming:upcoming,next:next,minutes:minutes,validStation:validStation,route:route,duration:duration,durationParts:durationParts}
