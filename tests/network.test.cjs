const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");
const FoamyNative = require("../kit/node-loader.cjs").load("FoamyNative");
const Model = require("../Model.js");

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
  let c = null;
  c = controller({ active: true, configured: true, sessionLocked: false, withinSchedule: true, demanded: false,
    networkReady: false, networkRetries: 0, networkRetry: timer(), pollTimer: timer(), canPoll: false, pollInterval: 60,
    statusProcess: { running: false }, statusOutput: { text: "" }, generation: 7, requestedGeneration: 0,
    inFlight: false, deadline: ["timeout", "--kill-after=2s", "18s"], Model,
    route: { from: { id: "NSR:StopPlace:1", name: "One" }, to: { id: "NSR:StopPlace:2", name: "Two" } },
    pluginDir: "/fixture", helperUnavailable: false, FoamyNative, report: { status: "ready", updatedAt: 0 },
    language: "en", lookAheadHours: 24, lastAttempt: 0,
    lockInProcess: false, pendingRefresh: false, pendingForce: false, Math, JSON, String, Date,
    Qt: { callLater(fn) { c.callLater.push(fn); } }, callLater: [],
    IpcResolver: { call: (context, t, m, a) => {
      assert.equal(JSON.stringify([t, m, a]), JSON.stringify(["lock", "isLocked", []]));
      return lock === undefined || lock === null ? { ran: false } : { ran: true, output: String(lock) };
    } },
  }, ["canFetch", "refresh", "fetch", "schedule", "retryNetworkRequest", "resetNetworkRetry", "lockedInProcess", "lockAnswered", "helperFailed", "fail", "finishFetch", "drainRefresh"]);
  // The service's `live` binding: the schedule is in force or a popup is open.
  Object.defineProperty(c, "live", { get() { return c.withinSchedule || c.demanded; } });
  return c;
}
test("the native helper runs under the same timeout with the route on stdin", () => {
  const c = fixture(false); c.networkReady = true;
  c.refresh(true, true);
  assert.deepEqual(JSON.parse(c.statusProcess.requestInput), c.route);
  assert.deepEqual(Array.from(c.statusProcess.command), ["timeout", "--kill-after=2s", "18s",
    ...FoamyNative.command("/fixture", "foamy-train-helper", ["--language", "en", "--hours", "24", "--route-stdin", "--force"])]);
  c.language = "no"; c.lookAheadHours = 3; c.networkReady = false; c.statusProcess.running = false;
  c.refresh(false, true);
  assert.deepEqual(Array.from(c.statusProcess.command).slice(9), ["--language", "nb", "--hours", "3", "--route-stdin", "--offline"]);
});
test("an unavailable helper (exit 126/127) is reported once and never retried", () => {
  const c = fixture(false); c.networkReady = true;
  c.refresh(true, true); c.pendingRefresh = true;
  c.statusProcess.running = false; c.finishFetch(127, true);
  assert.equal(c.helperUnavailable, true);
  assert.equal(c.report.error, FoamyNative.UNAVAILABLE_TEXT);
  assert.equal(c.pendingRefresh, false);
  assert.equal(c.pollTimer.running, false);
  c.refresh(true, true); c.retryNetworkRequest();
  assert.equal(c.statusProcess.running, false);
  assert.equal(c.networkRetry.starts, 0);
});
// Ends one fetch the way Quickshell does: exited(code), then running -> false
// (for a start that failed only the second). Returns and clears the callbacks
// the service queued with Qt.callLater.
function finish(c, code, stdout) {
  c.statusOutput.text = stdout;
  c.statusProcess.running = false;
  if (code !== null) c.finishFetch(code, true);
  c.finishFetch(-1, false);
  return c.callLater.splice(0);
}
test("how a fetch ends: the report, the retry and the queue", () => {
  const ok = JSON.stringify({ ...Model.blank("ok"), updatedAt: 1 });
  const reply = code => JSON.stringify({ ...Model.blank("error"), error: "x", errorCode: code });
  const failed = "Train request failed. Try Refresh.";
  // [outcome, exit code (null: the start failed), stdout, report.error, retry armed]
  const rows = [
    ["an ok reply", 0, ok, "", false],
    ["a network error", 0, reply("network_error"), "x", true],
    ["an HTTP error", 0, reply("http_error"), "x", true],
    ["offline", 0, reply("offline"), "x", false],
    ["an invalid Entur answer", 0, reply("invalid_response"), "x", false],
    ["a reply that is not a report", 0, "not json", "Invalid train response.", false],
    ["the deadline killed it", 124, "", failed, true],
    ["the start failed", null, "", failed, true],
  ];
  for (const [name, code, stdout, error, armed] of rows) {
    const c = fixture(false); c.networkReady = true;
    c.refresh(true, true);
    assert.equal(c.statusProcess.running, true, name);
    // A refresh queued behind the fetch runs once it ends, however it ends.
    c.refresh(true, true);
    const queued = finish(c, code, stdout);
    assert.equal(c.report.error, error, name);
    assert.equal(c.networkRetry.running, armed, name + ": retry armed");
    assert.equal(queued.length, 1, name + ": the end runs once");
    queued.forEach(fn => fn());
    assert.equal(c.statusProcess.running, true, name + ": the queued refresh starts");
  }
  // Earlier departures stay, marked stale, when a reply is not a report.
  const c = fixture(false); c.networkReady = true;
  c.report = { ...Model.blank("ok"), updatedAt: 5, departures: [{ id: "a" }] };
  c.refresh(true, true);
  finish(c, 0, "{}");
  assert.deepEqual([c.report.status, c.report.stale, c.report.departures.length, c.report.error],
    ["stale", true, 1, "Invalid train response."]);
});
test("a fetch for a replaced route or setting is dropped", () => {
  const c = fixture(false); c.networkReady = true;
  c.refresh(true, true); c.generation++;
  c.statusOutput.text = "not json"; c.statusProcess.running = false;
  c.finishFetch(0, true);
  assert.equal(c.report.status, "ready");
  assert.equal(c.callLater.length, 1);
});
test("a reconnect during an active worker queues one forced refresh", () => {
  const ok = JSON.stringify({ ...Model.blank("ok"), updatedAt: 1 });
  const c = fixture(false); c.networkReady = true;
  c.refresh(false, true);
  const first = c.statusProcess.command;
  assert.equal(first.includes("--force"), false);
  // A forced reconnect refresh and a poll arrive while the helper runs.
  c.refresh(true, false); c.refresh(false, false);
  assert.equal(c.statusProcess.command, first, "no second helper while one runs");
  finish(c, 0, ok).forEach(fn => fn());
  assert.equal(c.statusProcess.running, true, "the queued refresh starts");
  assert.ok(c.statusProcess.command.includes("--force"), "and it is forced");
  finish(c, 0, ok).forEach(fn => fn());
  assert.equal(c.statusProcess.running, false, "it ran once");
});
test("a locked session (in-process probe) skips Entur and keeps probing", () => {
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
test("without a lock target the session counts as unlocked and the fetch starts at once", () => {
  const c = fixture(null); c.networkReady = true; c.sessionLocked = true;
  c.refresh(true, false);
  assert.equal(c.sessionLocked, false);
  assert.equal(c.lockInProcess, false);
  assert.equal(c.statusProcess.running, true);
  assert.ok(c.statusProcess.command.includes("--force"));
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
test("only a shown, configured widget in force or with an open popup fetches", () => {
  // [state, fetches]
  const rows = [
    [{}, true],
    [{ withinSchedule: false }, false],
    [{ withinSchedule: false, demanded: true }, true],
    [{ active: false }, false],
    [{ route: null }, false],
    [{ configured: false }, false],
    [{ helperUnavailable: true }, false],
  ];
  for (const [state, fetches] of rows) {
    const c = fixture(false); c.networkReady = true;
    Object.assign(c, state);
    c.refresh(true, false);
    assert.equal(c.statusProcess.running, fetches, JSON.stringify(state));
  }
});
test("every reconnection waits out the network settle delay", () => {
  // Handlers are not functions; check the declaration the singleton relies on.
  assert.match(qml, /onNetworkConnectedChanged:\s*networkSettled = false/);
  assert.match(qml, /running: root\.networkConnected && !root\.networkSettled/);
});
