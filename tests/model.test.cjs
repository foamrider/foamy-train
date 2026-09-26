const test=require('node:test');const assert=require('node:assert/strict');
const Model=require('../Model.js'),Schedule=require('../Schedule.js'),Preferences=require('../Preferences.js');
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
 assert.equal(Preferences.language('system','nb_NO'),'nb');
});
test('stale snapshots do not imply live predictions',()=>{
 const r={...Model.blank('ok'),updatedAt:100,departures:[{id:'a',expected:120,aimed:120,cancelled:false},{id:'b',expected:500,aimed:500,cancelled:true}]};
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
