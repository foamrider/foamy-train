const test=require('node:test');
function loadPrefs(){const fs=require('node:fs'),vm=require('node:vm');const module={exports:{}};vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname,'../kit/FoamyPrefs.js'),'utf8').replace(/^\.pragma library\s*$/m,''),{module,console});return module.exports}const assert=require('node:assert/strict');
const Model=require('../Model.js'),Schema=require('../Preferences.js'),Prefs=loadPrefs();
const Preferences={valid:(k,v)=>Prefs.valid(Schema.fields,k,v),value:(s,k)=>Prefs.value(Schema.fields,s,k)};
test('preferences validate clock ranges and integers',()=>{
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
// The report contract (Model.limits, the numbers in native/src/entur.rs).
const notice=(id,text='x',extra)=>({id,summary:text,detail:text,kind:'warning',scopeLabel:text,...extra});
const departure=(id,notices=[])=>({id,line:'R10',platform:'1',aimed:1,expected:1,arrival:1,delay:0,duration:10,
  aimedTime:'10:00',expectedTime:'10:00',arrivalTime:'10:10',realtime:true,cancelled:false,notices});
const reply=(changes)=>JSON.stringify({...Model.blank('ok'),updatedAt:100,...changes});
test('reject malformed protocol rather than render misleading defaults',()=>{
 const base=JSON.parse(reply({route:{from:{id:'NSR:StopPlace:1',name:'A'},to:{id:'NSR:StopPlace:2',name:'B'}},
  departures:[departure('a',[notice('n')])],routeNotices:[notice('r')]}));
 assert.deepEqual(Model.parse(JSON.stringify(base)),base,'the valid base report parses');
 // Each row breaks one thing in an otherwise valid report.
 const broken=(change)=>{const r=structuredClone(base);change(r);return JSON.stringify(r)};
 const rows=[['not json','not json'],['empty text',''],['null','null'],['an array','[]'],['an empty object','{}'],
  ['an unknown status',broken(r=>{r.status='loading'})],['departures not a list',broken(r=>{r.departures={}})],
  ['route notices null',broken(r=>{r.routeNotices=null})],['updatedAt a string',broken(r=>{r.updatedAt='100'})],
  ['stale a number',broken(r=>{r.stale=0})],['error null',broken(r=>{r.error=null})],['errorCode a number',broken(r=>{r.errorCode=5})],
  ['an empty route',broken(r=>{r.route={}})],['a station id that is not NSR',broken(r=>{r.route.from.id='bad'})],
  ['a clock time without two digits',broken(r=>{r.departures[0].aimedTime='9:05'})],['expected a string',broken(r=>{r.departures[0].expected='100'})],
  ['realtime a number',broken(r=>{r.departures[0].realtime=1})],['no platform',broken(r=>{delete r.departures[0].platform})],
  ['notices not a list',broken(r=>{r.departures[0].notices={}})],['an unknown notice kind',broken(r=>{r.departures[0].notices[0].kind='error'})],
  ['a notice without detail',broken(r=>{delete r.routeNotices[0].detail})]];
 for(const [name,text] of rows)assert.throws(()=>Model.parse(text),undefined,name);
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
 const widget=require('../manifest.json').barWidget,keys=Schema.fields.map(f=>f.key).sort();
 for(const field of Schema.fields){
  assert.deepEqual(widget.defaults[field.key],field.defaultValue,field.key);
  const declared=widget.schema.find(f=>f.key===field.key);
  assert.ok(declared,field.key);
  assert.deepEqual(declared.defaultValue,field.defaultValue,field.key);
  assert.equal(declared.type,field.type,field.key);
  if(field.min!==undefined)assert.deepEqual([declared.min,declared.max],[field.min,field.max],field.key);
  if(field.step!==undefined)assert.equal(declared.step,field.step,field.key);
  if(field.options!==undefined)assert.deepEqual(declared.options,field.options,field.key);
 }
 // And the other way: the manifest declares nothing the widget does not read.
 assert.deepEqual(widget.schema.map(f=>f.key).sort(),keys);
 assert.deepEqual(Object.keys(widget.defaults).sort(),[...keys,'route'].sort());
 assert.equal(widget.defaults.route,null);
 for(const value of Schema.refreshChoices)assert.equal(Preferences.valid('refreshSeconds',value),true);
 for(const value of Schema.hourChoices)assert.equal(Preferences.valid('lookAheadHours',value),true);
});
test('durations take a number formatter',()=>{
 assert.equal(Model.duration(61,'en',v=>'<'+v+'>'),'<1> h <1> min');
});

const codePoints=s=>[...s].length;
test('clip cuts whole code points and marks the cut',()=>{
 for(const [text,limit,expected] of [['ab',5,'ab'],['abc',3,'abc'],['abcd',3,'ab…'],['øøøø',2,'ø…'],['🚆🚆🚆',2,'🚆…'],['x',1,'x'],['xy',1,'…']])
  assert.equal(Model.clip(text,limit),expected,text);
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
