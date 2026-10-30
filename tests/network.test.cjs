const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");

// Exercise TrainService's production functions with observable process,
// timer and lock-registry boundaries.
const qml = fs.readFileSync(path.join(__dirname, "../TrainService.qml"), "utf8");
function controller(values, functions) {
  const context = vm.createContext(values);
  context.root = context;
  for (const name of functions) {
    const start = qml.indexOf("function " + name + "(");
    assert.ok(start >= 0, "Missing service function: " + name);
    let end = qml.indexOf("{", start) + 1;
    let depth = 1;
    while (depth && end < qml.length) {
      if (qml[end] === "{") depth++;
      if (qml[end] === "}") depth--;
      end++;
    }
    vm.runInContext(qml.slice(start, end), context);
  }
  return context;
}
function timer() {
  return { running: false, interval: 0, starts: 0,
    restart() { this.running = true; this.starts++; },
    stop() { this.running = false; } };
}
function fixture(lock) {
  const c = controller({ active: true, configured: true, sessionLocked: false, withinSchedule: true, demanded: false,
    networkReady: false, networkRetries: 0, networkRetry: timer(), pollTimer: timer(), canPoll: false, pollInterval: 60,
    statusProcess: { running: false }, lockProcess: { running: false }, generation: 7,
    route: { from: { id: "NSR:StopPlace:1", name: "One" }, to: { id: "NSR:StopPlace:2", name: "Two" } },
    helperPath: "/fixture/train.py", language: "en", lookAheadHours: 24, lastAttempt: 0,
    lockProbeAvailable: true, lockInProcess: false, lockProbeFailures: 0, lockForce: false,
    pendingRefresh: false, pendingForce: false, lockGeneration: 0, Math, JSON, String, Date,
    Qt: { callLater() {} }, drainRefresh() {},
    IpcResolver: { registry: () => lock === undefined ? null : { call: (t, m, a) => {
      assert.equal(JSON.stringify([t, m, a]), JSON.stringify(["lock", "isLocked", []]));
      return lock === null ? { ran: false } : { ran: true, output: String(lock) };
    } } },
  }, ["canFetch", "refresh", "fetch", "lockProbeDone", "schedule", "retryNetworkRequest", "resetNetworkRetry", "lockedInProcess", "lockAnswered", "lockProbeFailed"]);
  return c;
}
test("offline startup loads cache only; the route goes to stdin, never argv", () => {
  const c = fixture(false);
  c.refresh(true, false);
  assert.ok(c.statusProcess.command.includes("--offline"));
  assert.ok(c.statusProcess.command.includes("--route-stdin"));
  assert.equal(c.statusProcess.command.join(" ").includes("NSR:"), false);
  assert.deepEqual(JSON.parse(c.statusProcess.requestInput), c.route);
  c.statusProcess.running = false; c.networkReady = true;
  c.refresh(true, false);
  assert.equal(c.statusProcess.command.includes("--offline"), false);
  assert.equal(c.requestedGeneration, 7);
});
test("a reconnect during an active worker queues one forced refresh", () => {
  const c = fixture(false); c.statusProcess.running = true; c.networkReady = true;
  c.refresh(true, false); c.refresh(false, false);
  assert.equal(c.pendingRefresh, true); assert.equal(c.pendingForce, true);
  assert.equal(c.statusProcess.command, undefined);
});
test("a locked session (4.5 in-process probe) skips Entur and keeps probing", () => {
  const c = fixture(true); c.networkReady = true;
  c.refresh(false, false);
  assert.equal(c.sessionLocked, true);
  assert.equal(c.lockInProcess, true);
  assert.equal(c.statusProcess.running, false);
  assert.ok(c.lastAttempt > 0);
});
test("a popup open or explicit refresh skips the probe and clears the lock", () => {
  const c = fixture(true); c.networkReady = true; c.sessionLocked = true;
  c.refresh(true, true);
  assert.equal(c.sessionLocked, false);
  assert.equal(c.statusProcess.running, true);
});
test("without an in-process answer the omarchy-shell probe runs first", () => {
  for (const lock of [undefined, null]) {
    const c = fixture(lock); c.networkReady = true;
    c.refresh(true, false);
    assert.equal(c.lockProcess.running, true);
    assert.equal(c.lockForce, true);
    assert.equal(c.statusProcess.running, false);
  }
});
test("a lock service that never answers stops being probed", () => {
  const c = fixture(null);
  for (let i = 0; i < 3; i++) c.lockProbeFailed();
  assert.equal(c.lockProbeAvailable, false);
  c.networkReady = true; c.refresh(false, false);
  assert.equal(c.statusProcess.running, true);
});
test("retries back off, stop after three, and reset after recovery", () => {
  const c = fixture(false); c.networkReady = true;
  for (const interval of [2500, 5000, 10000]) {
    c.retryNetworkRequest(); assert.equal(c.networkRetry.interval, interval);
  }
  c.retryNetworkRequest(); assert.equal(c.networkRetry.starts, 3);
  c.resetNetworkRetry(); assert.equal(c.networkRetries, 0); assert.equal(c.networkRetry.running, false);
});
test("offline, locked, and out-of-schedule states suppress retries", () => {
  for (const state of [{networkReady:false}, {networkReady:true,sessionLocked:true}, {networkReady:true,withinSchedule:false}]) {
    const c = fixture(false); Object.assign(c, state); c.retryNetworkRequest();
    assert.equal(c.networkRetry.starts, 0);
  }
});
test("the poll timer waits for the rest of the current interval", () => {
  const c = fixture(false); c.canPoll = true; c.pollInterval = 900;
  c.lastAttempt = Date.now() / 1000 - 300;
  c.schedule();
  assert.ok(Math.abs(c.pollTimer.interval - 600000) < 2000, String(c.pollTimer.interval));
  c.pollInterval = 60; c.schedule();
  assert.equal(c.pollTimer.interval, 1000, "an overdue poll runs at once");
  c.canPoll = false; c.schedule();
  assert.equal(c.pollTimer.running, false);
});
test("an omarchy-shell probe that finishes after polling stopped does not fetch", () => {
  for (const change of [c => { c.withinSchedule = false; c.generation++; }, c => { c.active = false; c.generation++; },
                         c => { c.route = null; }, c => { c.generation++; }]) {
    const c = fixture(null); c.networkReady = true;
    c.refresh(false, false);
    assert.equal(c.lockProcess.running, true);
    c.lockProcess.running = false;
    change(c);
    c.lockProbeDone(0, "false\n");
    assert.equal(c.statusProcess.running, false, change.toString());
  }
  const c = fixture(null); c.networkReady = true;
  c.refresh(false, false); c.lockProcess.running = false;
  c.lockProbeDone(0, "false\n");
  assert.equal(c.statusProcess.running, true, "unchanged state still fetches");
  const locked = fixture(null); locked.networkReady = true;
  locked.refresh(false, false); locked.lockProcess.running = false;
  locked.lockProbeDone(0, "true");
  assert.equal(locked.sessionLocked, true);
  assert.equal(locked.statusProcess.running, false);
});
test("fetch itself refuses when polling is off", () => {
  const c = fixture(false); c.withinSchedule = false;
  c.fetch(true);
  assert.equal(c.statusProcess.running, false);
});
test("every reconnection waits out the network settle delay", () => {
  // Handlers are not functions; check the declaration the singleton relies on.
  assert.match(qml, /onNetworkConnectedChanged:\s*networkSettled = false/);
  assert.match(qml, /running: root\.networkConnected && !root\.networkSettled/);
});
