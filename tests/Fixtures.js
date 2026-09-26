var now=1790406240
var route={from:{id:"NSR:StopPlace:59872",name:"Oslo S"},to:{id:"NSR:StopPlace:62339",name:"Lillestrøm"}}
function notice(id,summary,kind,detail,scope){return {id:id,summary:summary,kind:kind||"warning",detail:detail||"",scopeLabel:scope||""}}
function departure(id,minutes,line,delay,cancelled,notices){
 var aimed=now+(minutes-(delay||0))*60,expected=now+minutes*60
 function time(epoch){var date=new Date(epoch*1000);return String(date.getUTCHours()+2).padStart(2,"0")+":"+String(date.getUTCMinutes()).padStart(2,"0")}
 return {id:id,line:line,aimed:aimed,expected:expected,arrival:expected+600,aimedTime:time(aimed),expectedTime:time(expected),arrivalTime:time(expected+600),delay:delay||0,duration:10,platform:id==="b"?"10":"11",realtime:true,cancelled:!!cancelled,notices:notices||[]}
}
function report(state){
 var r={status:"ok",route:route,departures:[departure('a',11,'R10'),departure('b',20,'R11'),departure('c',28,'R10'),departure('d',38,'R10')],routeNotices:[],updatedAt:now,stale:false,error:"",errorCode:""}
 if(state==="long")r.departures=[departure("a",724,"R12"),departure("b",780,"R12"),departure("c",1439,"R12")]
 if(state==="delayed"||state==="incidents"){
 r.departures[0]=departure('a',11,'R10',3,false,[notice('signal','Delayed by a signal fault at Oslo S.','warning','The departure is waiting for a clear signal. Check the platform display before boarding.'),notice('carriage','Rear carriage closed. Board towards the front.','info')])
 r.departures[1]=departure('b',20,'R11',3,false,[notice('signal2','Signal fault at Oslo S','warning','Staff are working to restore normal service.')])
 }
 if(state==="incidents"){
 r.departures[2]=departure('c',28,'R10',0,true,[notice('withdrawn','Train withdrawn from service','warning','Use the next available departure.')])
 r.departures[3].notices=[notice('short','Shorter train than usual','info','Allow extra time to board. There may be limited seating.')]
 }
 if(state==="route")r.routeNotices=[notice('station','Lift to the platforms out of service','info','Use the staffed station entrance for assistance.','Oslo S')]
 if(state==="cancelled"){r.departures.forEach(function(d){d.cancelled=true;d.notices=[notice(d.id,'Train withdrawn from service','warning')]})}
 if(state==="offline"){r.stale=true;r.status="stale";r.updatedAt=now-720;r.error="Offline. Showing the last available update."}
 if(["empty","error","loading","unconfigured","schedule"].indexOf(state)>=0)r.departures=[]
 if(state==="error"){r.status="error";r.updatedAt=0;r.error="Cannot reach Entur. Check your connection and try Refresh."}
 if(state==="unconfigured"){r.status="unconfigured";r.route=null;r.updatedAt=0}
 if(state==="loading"||state==="schedule"){r.status="ready";r.updatedAt=0}
 return r
}
if(typeof module!=="undefined")module.exports={report:report,now:now,route:route}
