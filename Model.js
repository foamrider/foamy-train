function blank(status) { return {status:status || "loading",route:null,departures:[],routeNotices:[],updatedAt:0,stale:false,error:"",errorCode:""} }
function validStation(s) { return s && typeof s.name==="string" && s.name.trim().length>0 && s.name.length<=160 && !/[\x00-\x1f]/.test(s.name) && typeof s.id==="string" && /^NSR:StopPlace:\d+$/.test(s.id) }
function route(value) {
  if (value === undefined || value === null) return null
  if (!value || !validStation(value.from) || !validStation(value.to)) throw Error("Select both stations from search results.")
  if (value.from.id === value.to.id) throw Error("Choose two different stations.")
  return {from:{id:value.from.id,name:value.from.name.trim()},to:{id:value.to.id,name:value.to.name.trim()}}
}
function validNotice(n) { return n && typeof n.id==="string" && typeof n.summary==="string" && typeof n.detail==="string" && typeof n.scopeLabel==="string" && ["info","warning"].indexOf(n.kind)>=0 }
function finite(n) { return typeof n==="number" && isFinite(n) }
function parse(text) {
  var r=JSON.parse(text)
  if (!r || ["ok","stale","error","ready","unconfigured"].indexOf(r.status)<0 || !Array.isArray(r.departures) || !Array.isArray(r.routeNotices)
      || !finite(r.updatedAt) || typeof r.stale!=="boolean" || typeof r.error!=="string" || typeof r.errorCode!=="string"
      || (r.route!==null && (!validStation(r.route.from)||!validStation(r.route.to)))) throw Error("Invalid train response")
  if (!r.routeNotices.every(validNotice) || !r.departures.every(function(d) {
    return d && typeof d.id==="string" && typeof d.line==="string" && typeof d.platform==="string"
      && [d.aimed,d.expected,d.arrival,d.delay,d.duration].every(finite)
      && [d.aimedTime,d.expectedTime,d.arrivalTime].every(function(t){return typeof t==="string" && /^\d{2}:\d{2}$/.test(t)})
      && typeof d.realtime==="boolean" && typeof d.cancelled==="boolean" && Array.isArray(d.notices) && d.notices.every(validNotice)
  })) throw Error("Invalid train response")
  return r
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
if(typeof module!=="undefined")module.exports={blank:blank,parse:parse,stale:stale,staleAfter:staleAfter,pollInterval:pollInterval,upcoming:upcoming,next:next,minutes:minutes,validStation:validStation,route:route,duration:duration,durationParts:durationParts}
