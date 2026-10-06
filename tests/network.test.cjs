const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");

const qml = fs.readFileSync(path.join(__dirname, "../Panel.qml"), "utf8");
function controller(values, functions) {
  const context = vm.createContext(values);
  context.root = context;
  // Exercise the controller's production functions with observable process/timer boundaries.
  for (const name of functions) {
    const start = qml.indexOf("function " + name + "(");
    assert.ok(start >= 0, "Missing controller function: " + name);
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

function fixture() {
  return controller({ initialized: true, sessionLocked: false, withinSchedule: true,
    networkReady: false, networkRetries: 0, networkRetry: timer(),
    statusProcess: { running: false }, routeSaving: false, generation: 7,
    report: { route: { from: { id: "one" }, to: { id: "two" } } },
    helperPath: "/fixture/train.py", language: "en", lookAheadHours: 24,
    pendingRefresh: false, pendingForce: false,
  }, ["refresh", "retryNetworkRequest", "resetNetworkRetry"]);
}
test("offline startup loads cache only; online requests use the current route", () => {
  const c = fixture();
  c.refresh(true);
  assert.ok(c.statusProcess.command.includes("--offline"));
  c.statusProcess.running = false; c.networkReady = true;
  c.refresh(true);
  assert.equal(c.statusProcess.command.includes("--offline"), false);
  assert.equal(c.requestedGeneration, 7);
});
test("a reconnect during an active worker queues one forced refresh", () => {
  const c = fixture(); c.statusProcess.running = true; c.networkReady = true;
  c.refresh(true); c.refresh(false);
  assert.equal(c.pendingRefresh, true); assert.equal(c.pendingForce, true);
  assert.equal(c.statusProcess.command, undefined);
});
test("retries back off, stop after three, and reset after recovery", () => {
  const c = fixture(); c.networkReady = true;
  for (const interval of [2500, 5000, 10000]) {
    c.retryNetworkRequest(); assert.equal(c.networkRetry.interval, interval);
  }
  c.retryNetworkRequest(); assert.equal(c.networkRetry.starts, 3);
  c.resetNetworkRetry(); assert.equal(c.networkRetries, 0); assert.equal(c.networkRetry.running, false);
});
test("offline, locked, and out-of-schedule states suppress retries", () => {
  for (const state of [{networkReady:false}, {networkReady:true,sessionLocked:true}, {networkReady:true,withinSchedule:false}]) {
    const c = fixture(); Object.assign(c, state); c.retryNetworkRequest();
    assert.equal(c.networkRetry.starts, 0);
  }
});
