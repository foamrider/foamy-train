const test=require('node:test');
function loadPrefs(){const fs=require('node:fs'),vm=require('node:vm');const module={exports:{}};vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname,'../kit/FoamyPrefs.js'),'utf8').replace(/^\.pragma library\s*$/m,''),{module,console});return module.exports}const assert=require('node:assert/strict');
const Model=require('../Model.js'),Schedule=require('../Schedule.js'),Schema=require('../Preferences.js'),Prefs=loadPrefs();
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
