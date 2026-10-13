// Run with: node coordination_test.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(`${__dirname}/BarWidget.qml`, 'utf8');
const { id } = JSON.parse(fs.readFileSync(`${__dirname}/manifest.json`, 'utf8'));
let members = [];
let clock = Date.parse('2026-10-13T09:45:00Z');
const commands = [];
const deferred = [];
function flushDeferred() { while (deferred.length) deferred.shift()(); }
const ownerChange = source.match(/  onUpdateOwnerChanged: ({[^]*?\n  })/)[1];
const timerTrigger = source.match(/id: notificationTimer[^]*?onTriggered: ([^\n]+)/)[1];
const Clock = class extends Date { static now() { return clock; } };
function widget() {
  const process = { running: false };
  const state = {
    Date: Clock, JSON, Math, String,
    moduleName: id, mounted: true,
    pluginDir: '/synthetic/plugin',
    status: 'loading', errorText: '', eventData: null, eventsData: [],
    notified: {}, refreshPending: false,
    fetchProcess: process,
    notificationTimer: {
      running: false, deadline: Infinity,
      stop() { this.running = false; },
      start() { this.running = true; this.deadline = clock + this.interval; },
    },
    notificationCommand: 'synthetic-notify',
    privacyMode: true,
    eventTitle() { return 'Private event'; },
    Qt: {
      formatTime(date) { return date.toISOString().slice(11, 16); },
      callLater(callback) { deferred.push(callback); },
    },
    Quickshell: { execDetached(command) { commands.push(Array.from(command)); } },
    bar: { moduleWidgets(requestedId) { assert.equal(requestedId, id); return members; } },
  };
  const context = vm.createContext({ root: state });
  for (const key of Object.keys(state)) Object.defineProperty(context, key, {
    get() { return state[key]; }, set(value) { state[key] = value; },
  });
  for (const name of ['peerWidgets', 'syncFromOwner', 'distributeResult', 'refresh',
    'applyResult', 'eventKey', 'sendNotification', 'checkNotifications']) {
    const method = source.match(new RegExp(`  function ${name}\\([^]*?\\n  }`));
    assert.ok(method, 'Missing ' + name);
    vm.runInContext(method[0], context);
    state[name] = context[name];
  }
  Object.defineProperty(state, 'updateOwner', {
    get() { return state.mounted && state.peerWidgets()[0] === state; },
  });
  Object.defineProperty(context, 'updateOwner', { get() { return state.updateOwner; } });
  state.ownerChanged = () => vm.runInContext(ownerChange, context);
  state.fireReminderTimer = () => {
    if (state.notificationTimer.running && clock >= state.notificationTimer.deadline) {
      state.notificationTimer.running = false;
      vm.runInContext(timerTrigger, context);
    }
  };
  return state;
}
const first = widget();
const second = widget();
members = [first, second];
assert.equal(first.updateOwner, true);
assert.equal(second.updateOwner, false);
second.refresh();
assert.equal(first.fetchProcess.running, true, 'Refresh from any monitor reaches one owner');
assert.equal(second.fetchProcess.running, false);
const events = ['Demo stand-up', 'Demo customer call'].map((title, index) => ({
  title, start: '2026-10-13T10:00:00Z', end: '2026-10-13T10:30:00Z',
  ongoing: false, meetingUrl: 'https://meet.google.com/demo-' + index,
}));
first.distributeResult(JSON.stringify({ status: 'ok', event: events[0], events }));
assert.equal(first.status, 'ok');
assert.equal(second.status, 'ok');
assert.equal(second.eventsData.length, 2);
assert.equal(second.notified, first.notified, 'Reminder history shared across the widget group');
assert.equal(commands.length, 2, 'One soon-reminder per event, not per monitor');
second.checkNotifications();
first.checkNotifications();
assert.equal(commands.length, 2);
assert.ok(commands.every(command => !command.join(' ').includes('Demo')));

// A late monitor joins the current cache/history without scheduling duplicates.
const third = widget();
members = [first, second, third];
third.syncFromOwner();
assert.equal(third.status, 'ok');
assert.equal(third.eventsData.length, 2);
assert.equal(third.notified, first.notified);
third.checkNotifications();
assert.equal(commands.length, 2);

// Remove the owner immediately before start; leave replacement fetching pending.
clock = Date.parse('2026-10-13T09:59:59Z');
first.mounted = false;
members = [first, second, third];
assert.equal(first.updateOwner, false);
assert.equal(second.updateOwner, true);
first.distributeResult(JSON.stringify({ status: 'error' }));
assert.equal(second.status, 'ok', 'Retired-owner output must not overwrite current state');
first.ownerChanged();
second.ownerChanged();
flushDeferred();
assert.equal(second.fetchProcess.running, true);
assert.equal(third.fetchProcess.running, false);
assert.equal(second.notificationTimer.running, true,
  'Promotion must resume cached reminder scheduling before replacement fetching finishes');
assert.equal(second.notificationTimer.deadline, Date.parse('2026-10-13T10:00:00Z'));
clock = Date.parse('2026-10-13T10:00:00Z');
for (const item of [first, second, third]) item.fireReminderTimer();
assert.equal(commands.length, 4, 'Cached start-reminders arrive while replacement fetch remains pending');
assert.equal(second.fetchProcess.running, true);
for (const item of [first, second, third]) item.fireReminderTimer();
assert.equal(commands.length, 4);
second.distributeResult(JSON.stringify({ status: 'error', error: 'Synthetic unavailable' }));
assert.equal(third.status, 'error');
assert.equal(third.eventsData.length, 0);

// Native bindings must gate timer ownership and discard stale process output.
assert.ok(source.includes('running: root.updateOwner'));
assert.ok(source.includes('onStreamFinished: root.distributeResult(text)'));
assert.ok(source.includes('Component.onDestruction: mounted = false'));
// Deferred startup must discard ownership lost before its callback runs.
second.fetchProcess.running = false;
second.ownerChanged();
second.mounted = false;
flushDeferred();
assert.equal(second.fetchProcess.running, false);
assert.equal(third.fetchProcess.running, false);
console.log('ok: shared fetching, per-event reminders, late monitor, owner removal, stale-output rejection');
