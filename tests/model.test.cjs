const test=require('node:test');
function loadPrefs(){const fs=require('node:fs'),vm=require('node:vm');const module={exports:{}};vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname,'../kit/FoamyPrefs.js'),'utf8').replace(/^\.pragma library\s*$/m,''),{module,console});return module.exports}const assert=require('node:assert/strict');
const Model=require('../Model.js'),Schema=require('../Preferences.js'),Prefs=loadPrefs();
// The kit's FoamySchedule, which the service and the panel import. Its
// objects come from the loader's vm realm, so results are compared as plain data.
const KitSchedule=require('../kit/node-loader.cjs').load('FoamySchedule');
const plain=v=>v===null||v===undefined?v:JSON.parse(JSON.stringify(v));
const Schedule=Object.fromEntries(Object.entries(KitSchedule).map(([k,f])=>[k,typeof f==='function'?(...a)=>plain(f(...a)):f]));
const Preferences={valid:(k,v)=>Prefs.valid(Schema.fields,k,v),value:(s,k)=>Prefs.value(Schema.fields,s,k)};
test('schedule supports overnight carry and explicit days off',()=>{
 const week=['22:00-02:00','','','','','',''];
 assert.equal(Schedule.withinWeek(new Date(2026,8,28,23),true,week),true);
 assert.equal(Schedule.withinWeek(new Date(2026,8,29,1),true,week),true);
 assert.equal(Schedule.withinWeek(new Date(2026,8,29,2),true,week),false);
 assert.equal(Schedule.withinWeek(new Date(2026,8,29,1),false,[]),true);
 assert.deepEqual(Schedule.week({}),['','','','','','','']);
});
test('preferences validate clock ranges, integers and language',()=>{
 assert.equal(Preferences.valid('scheduleMonday','23:00-24:00'),true);
 for(const value of ['24:00-24:00','09:80-10:00','9:00-10:00'])assert.equal(Preferences.valid('scheduleMonday',value),false);
 assert.equal(Preferences.valid('refreshSeconds',0),false);
 assert.equal(Preferences.value({},'showBarMinutes'),true);
 assert.equal(Preferences.valid('showBarMinutes',false),true);
 assert.equal(Preferences.valid('showBarMinutes','false'),false);
 assert.equal(Preferences.valid('refreshSeconds','60'),false);
});
test('stale snapshots do not imply live predictions',()=>{
 const r={...Model.blank('ok'),updatedAt:100,departures:[{id:'a',expected:120,aimed:120,cancelled:false},{id:'b',expected:500,aimed:500,cancelled:true}]};
 assert.equal(Model.stale(r,281,false,60),true);
 assert.equal(Model.stale(r,281,false),true);
 assert.equal(Model.stale(r,110,true),true);
 assert.equal(Model.upcoming(r,200,false).length,1);
 assert.equal(Model.upcoming(r,200,true).length,2);
 assert.equal(Model.next(Model.upcoming(r,200,false)),null);
 assert.equal(Model.next(r.departures).id,'a');
});
test('reject malformed protocol rather than render misleading defaults',()=>{
 assert.throws(()=>Model.parse('{}'));
 assert.throws(()=>Model.parse(JSON.stringify({...Model.blank('ok'),departures:[{}]})));
 assert.deepEqual(Model.parse(JSON.stringify(Model.blank('unconfigured'))),Model.blank('unconfigured'));
});

test('route settings are a validated ordered station pair',()=>{
 const from={id:'NSR:StopPlace:1',name:'Central'},to={id:'NSR:StopPlace:2',name:'Airport'};
 assert.equal(Model.route(undefined),null);
 assert.equal(Model.route(null),null);
 assert.deepEqual(Model.route({from:{...from,name:' Central ',label:'Search label'},to}),{from,to});
 assert.deepEqual(Model.route({from:to,to:from}),{from:to,to:from});
 for(const value of [{},false,{from,to:from},{from:{...from,id:'bad'},to},{from:{...from,name:'\nCentral'},to}])assert.throws(()=>Model.route(value));
});

test('countdowns normalize whole hours and remaining minutes',()=>{
 for(const [minutes,expected] of [[0,'0 min'],[59,'59 min'],[60,'1 h'],[61,'1 h 1 min'],[724,'12 h 4 min'],[1440,'24 h']])
  assert.equal(Model.duration(minutes,'en'),expected);
 assert.equal(Model.duration(724,'no'),'12 t 4 min');
 assert.equal(Model.duration(Model.minutes({expected:60*60},1),'en'),'1 h');
 assert.equal(Model.duration(Model.minutes({expected:60*60},61),'en'),'59 min');
});
test('look-ahead hours accept only whole values from one to twenty-four',()=>{
 assert.equal(Preferences.value({},'lookAheadHours'),24);
 for(const value of [1,3,24])assert.equal(Preferences.valid('lookAheadHours',value),true);
 for(const value of [0,25,1.5,'3',true])assert.equal(Preferences.valid('lookAheadHours',value),false);
});

test('stale threshold follows the refresh interval',()=>{
 const r={...Model.blank('ok'),updatedAt:1000,departures:[]};
 assert.equal(Model.staleAfter(60),180);
 assert.equal(Model.staleAfter(300),630);
 assert.equal(Model.staleAfter(900),1830);
 // A 300 s interval no longer reads as stale between two ordinary polls.
 for(const age of [0,210,299,300,600])assert.equal(Model.stale(r,1000+age,false,300),false,String(age));
 assert.equal(Model.stale(r,1000+631,false,300),true);
 assert.equal(Model.stale(r,1001,true,900),true);
 assert.equal(Model.stale({...r,stale:true},1001,false,900),true);
});
test('polling adapts to popup, distance to the next train and lock',()=>{
 const now=100000, dep=(m,extra)=>({id:'d'+m,expected:now+m*60,aimed:now+m*60,cancelled:false,delay:0,notices:[],...extra});
 const report=(...d)=>({...Model.blank('ok'),updatedAt:now,departures:d});
 const p=(base,state)=>Model.pollInterval(base,{now,...state});
 assert.equal(p(60,{report:report(dep(10))}),60);
 assert.equal(p(60,{report:report(dep(45))}),300);
 assert.equal(p(60,{report:report(dep(200))}),900);
 assert.equal(p(60,{report:report()}),900);
 assert.equal(p(60,{open:true,report:report(dep(200))}),60);
 assert.equal(p(600,{report:report(dep(10))}),600);
 assert.equal(p(60,{report:report(dep(45,{cancelled:true}),dep(200))}),900,'a cancelled train is not the next departure');
 assert.equal(p(60,{report:report(dep(20,{cancelled:true}))}),60,'only cancelled trains: watch the first one');
 assert.equal(p(60,{report:{...report(dep(-5)),departures:[dep(-5)]}}),60,'every cached train left: refresh at the base pace');
 assert.equal(p(60,{locked:true,lockSeconds:10,report:report(dep(5))}),10);
 assert.equal(p(60,{report:Model.blank('ready')}),60,'first answer pending');
 assert.equal(p(60,{report:Model.blank('error')}),300,'errors without data back off');
 assert.equal(p(5,{report:report(dep(1))}),30,'base is clamped to the schema range');
});
test('schema fields match the manifest',()=>{
 const manifest=require('../manifest.json');
 for(const field of Schema.fields){
  assert.deepEqual(manifest.barWidget.defaults[field.key],field.defaultValue,field.key);
  const declared=manifest.barWidget.schema.find(f=>f.key===field.key);
  assert.ok(declared,field.key);
  if(field.min!==undefined)assert.deepEqual([declared.min,declared.max],[field.min,field.max],field.key);
 }
 for(const value of Schema.refreshChoices)assert.equal(Preferences.valid('refreshSeconds',value),true);
 for(const value of Schema.hourChoices)assert.equal(Preferences.valid('lookAheadHours',value),true);
});
test('durations take a number formatter',()=>{
 assert.equal(Model.duration(61,'en',v=>'<'+v+'>'),'<1> h <1> min');
});

test('schedule: snoozing and resuming override the schedule until the next day', () => {
  const at = (day, hour, minute) => new Date(2026, 10, day, hour, minute || 0);
  const week = ['08:00-16:00', '22:00-06:00', '', '', '', '', '']; // Monday, Tuesday night
  // Within the hours: a snooze lasts until they end, then the schedule rules again.
  const snooze = Schedule.toggled(at(2, 10), true, week, null);
  assert.deepEqual(snooze, { on: false, until: at(2, 16).getTime() });
  assert.equal(Schedule.effective(at(2, 15, 59), true, week, snooze), false);
  assert.equal(Schedule.effective(at(3, 8), true, week, snooze), false);
  // Pressing again goes back to the schedule: no override.
  assert.equal(Schedule.toggled(at(2, 11), true, week, snooze), null);
  // Outside the hours: resuming lasts until midnight...
  const evening = Schedule.toggled(at(2, 19), true, week, null);
  assert.deepEqual(evening, { on: true, until: at(3, 0).getTime() });
  assert.equal(Schedule.effective(at(2, 23, 59), true, week, evening), true);
  assert.equal(Schedule.effective(at(3, 0), true, week, evening), false);
  // ...or until the schedule starts, if that is sooner.
  assert.deepEqual(Schedule.toggled(at(2, 6), true, week, null), { on: true, until: at(2, 8).getTime() });
  // An overnight range: the snooze runs on past midnight to its end.
  assert.deepEqual(Schedule.toggled(at(3, 23), true, week, null), { on: false, until: at(4, 6).getTime() });
  // No schedule: snoozed until midnight.
  assert.deepEqual(Schedule.toggled(at(4, 12), false, [], null), { on: false, until: at(5, 0).getTime() });
  // The state file: expired or malformed overrides are dropped.
  const text = Schedule.serializeOverride(snooze);
  assert.deepEqual(Schedule.parseOverride(text, at(2, 12).getTime()), snooze);
  assert.equal(Schedule.parseOverride(text, at(2, 16).getTime()), null);
  assert.equal(Schedule.parseOverride('{"version":1,"override":{"on":"no","until":1}}', 0), null);
  assert.equal(Schedule.parseOverride('not json', 0), null);
  assert.equal(Schedule.serializeOverride(null), '{"version":1,"override":null}\n');
});

// The report contract (Model.limits, the numbers in native/src/entur.rs).
const notice=(id,text='x',extra)=>({id,summary:text,detail:text,kind:'warning',scopeLabel:text,...extra});
const departure=(id,notices=[])=>({id,line:'R10',platform:'1',aimed:1,expected:1,arrival:1,delay:0,duration:10,
  aimedTime:'10:00',expectedTime:'10:00',arrivalTime:'10:10',realtime:true,cancelled:false,notices});
const reply=(changes)=>JSON.stringify({...Model.blank('ok'),updatedAt:100,...changes});
const codePoints=s=>[...s].length;
test('clip cuts whole code points and marks the cut',()=>{
 for(const [text,limit,expected] of [['ab',5,'ab'],['abc',3,'abc'],['abcd',3,'ab…'],['øøøø',2,'ø…'],['🚆🚆🚆',2,'🚆…'],['x',1,'x'],['xy',1,'…']])
  assert.equal(Model.clip(text,limit),expected,text);
 assert.deepEqual(Model.limits,{stations:8,departures:6,notices:3,routeNotices:5,summary:200,detail:600,scope:100,id:100,code:20,label:160});
});
test('a reply within the contract is unchanged',()=>{
 const r={...Model.blank('ok'),updatedAt:100,searchHours:3,departures:[departure('a',[notice('n1')])],routeNotices:[notice('r1')]};
 assert.deepEqual(Model.parse(JSON.stringify(r)),r);
});
test('oversized notice lists keep the first distinct ones and say so',()=>{
 // The marketplace review's shape: 10,000 unique route notices, below the 2 MB reply cap.
 const many=n=>Array.from({length:n},(_,i)=>notice('n'+i));
 const text=reply({departures:Array.from({length:20},(_,d)=>departure('d'+d,[notice('n0'),...many(100)])),routeNotices:many(10000)});
 assert.ok(text.length<2000000,String(text.length));
 const r=Model.parse(text);
 assert.deepEqual(r.departures.map(d=>d.id),['d0','d1','d2','d3','d4','d5']);
 for(const d of r.departures)assert.deepEqual(d.notices.map(n=>n.id),['n0','n1','n2'],'deduplicated before counting');
 assert.deepEqual(r.routeNotices.map(n=>n.id),['n0','n1','n2','n3','n4']);
 assert.equal(r.noticesOmitted,true);
 // Duplicates alone never count as left out.
 const same=Model.parse(reply({departures:[departure('a',[notice('n1'),notice('n1'),notice('n2')])],routeNotices:[notice('r'),notice('r')]}));
 assert.equal(same.departures[0].notices.length,2);
 assert.equal(same.routeNotices.length,1);
 assert.equal(same.noticesOmitted,undefined);
 // Exactly at the limits: nothing is left out.
 assert.equal(Model.parse(reply({departures:[departure('a',many(3))],routeNotices:many(5)})).noticesOmitted,undefined);
});
test('oversized notice text is cut, never inside a surrogate pair',()=>{
 const long='🚆'.repeat(5000);
 const r=Model.parse(reply({departures:[{...departure(long,[notice(long,long)]),line:long,platform:long}],routeNotices:[notice('r',long)]}));
 const d=r.departures[0],n=d.notices[0],route=r.routeNotices[0];
 for(const [value,limit] of [[n.id,100],[n.summary,200],[n.detail,600],[n.scopeLabel,100],[route.summary,200],[d.id,100],[d.line,20],[d.platform,20]]){
  assert.equal(codePoints(value),limit);
  assert.ok(value.endsWith('🚆…'),value.slice(-4));
  assert.ok(!/[\ud800-\udbff](?![\udc00-\udfff])/.test(value),'no lone high surrogate');
 }
 assert.equal(r.noticesOmitted,undefined,'cutting text leaves nothing out');
 assert.deepEqual(Model.parse(JSON.stringify(r)),r,'the cut report is within the contract');
});
test('a cached report from an older helper is bounded like a live one',()=>{
 // The helper serves the stored snapshot as stale when Entur can't be reached.
 const old={...Model.blank('stale'),stale:true,updatedAt:100,error:'Offline. Showing the last available update.',errorCode:'offline',
  route:{from:{id:'NSR:StopPlace:1',name:'Central'},to:{id:'NSR:StopPlace:2',name:'Airport'}},searchHours:24,wideSince:90,
  departures:Array.from({length:12},(_,d)=>departure('d'+d,Array.from({length:500},(_,i)=>notice('n'+i,'x'.repeat(2000))))),
  routeNotices:Array.from({length:500},(_,i)=>notice('r'+i))};
 const r=Model.parse(JSON.stringify(old));
 assert.equal(r.status,'stale');
 assert.equal(r.departures.length,6);
 assert.ok(r.departures.every(d=>d.notices.length===3&&codePoints(d.notices[0].detail)===600));
 assert.equal(r.routeNotices.length,5);
 assert.equal(r.noticesOmitted,true);
 assert.deepEqual([r.searchHours,r.wideSince,r.errorCode],[24,90,'offline']);
 assert.throws(()=>Model.parse(reply({noticesOmitted:'yes'})));
 assert.throws(()=>Model.parse(reply({routeNotices:[...Array.from({length:10},(_,i)=>notice('r'+i)),{id:'bad'}]})),'every notice is checked');
});
test('station search keeps the first eight distinct stations',()=>{
 const station=i=>({id:'NSR:StopPlace:'+i,name:'Station '+i,label:'Station '+i+', Norway'});
 const stations=Array.from({length:10000},(_,i)=>station(Math.floor(i/2)));
 assert.ok(JSON.stringify({status:'ok',stations}).length<2000000);
 const found=Model.stations({status:'ok',stations});
 assert.deepEqual(found.map(s=>s.id),Array.from({length:8},(_,i)=>'NSR:StopPlace:'+i));
 assert.equal(codePoints(Model.stations({stations:[{...station(1),label:'ø'.repeat(400)}]})[0].label),160);
 assert.deepEqual(Model.stations({stations:[{...station(1),name:'🚆'.repeat(160)}]}).length,1,'names count code points');
 for(const bad of [{},{stations:{}},{stations:[{...station(1),label:5}]},{stations:[{id:'x',name:'y',label:'z'}]}])
  assert.throws(()=>Model.stations(bad));
});
