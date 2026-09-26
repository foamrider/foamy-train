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
function stale(report,now,offline) { return report.updatedAt>0 && (report.stale || offline || now-report.updatedAt>180) }
function upcoming(report,now,isStale) { return isStale ? report.departures : report.departures.filter(function(d){return Math.max(d.expected,d.aimed)>=now-30}) }
function next(departures) { return departures.find(function(d){return !d.cancelled}) || null }
function minutes(d,now) { return Math.max(0,Math.ceil((d.expected-now)/60)) }
if(typeof module!=="undefined")module.exports={blank:blank,parse:parse,stale:stale,upcoming:upcoming,next:next,minutes:minutes,validStation:validStation,route:route}
