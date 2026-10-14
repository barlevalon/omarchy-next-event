// Run with: node feed_settings_test.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(`${__dirname}/FeedSettings.qml`, 'utf8');
const secret = 'https://calendar.example/private/secret-token/basic.ics';
const feed = { id: 'work', name: 'Work', url: secret, hideTitles: false };
const rows = [];
let saves = 0;
let savedCalendars;
const context = vm.createContext({
  open: false, revealUrls: true, helpVisible: true, pendingRead: false, feedsLoaded: false, message: '',
  pluginDir: '/test/plugin',
  configProcess: { running: false },
  feeds: {
    get count() { return rows.length; },
    get(index) { return rows[index]; },
    clear() { rows.length = 0; },
    append(row) { rows.push({ ...row }); },
    setProperty(index, name, value) { rows[index][name] = value; },
  },
  feedRows: { itemAt() { return null; } },
  Qt: { callLater(callback) { callback(); } },
  saved(calendars) { saves++; savedCalendars = JSON.parse(JSON.stringify(calendars)); },
});
context.root = context;
Object.defineProperty(context, 'busy', { get() { return context.configProcess.running; } });
for (const name of ['show', 'dismiss', 'urls', 'calendars', 'addFeed', 'updateFeed', 'request', 'applyResult']) {
  const body = source.match(new RegExp(`  function ${name}\\([^]*?\\n  }`));
  assert.ok(body, `Missing ${name}`);
  vm.runInContext(body[0], context);
}
assert.ok(source.includes('maximumLength: 40'), 'Calendar names use Qt TextInput maximumLength');
const mask = source.match(/password: ([^\n]+)/)[1];
const accessibleName = source.match(/id: urlInput[^]*?Accessible.name: ([^\n]+)/)[1];
function result(value, action) {
  context.configProcess.running = false;
  context.applyResult(JSON.stringify(value), action);
}

context.show();
assert.equal(context.open, true);
assert.equal(context.revealUrls, false);
assert.deepEqual(Array.from(context.configProcess.command), ['/test/plugin/next_event.py', '--feeds-read']);
result({ status: 'ok', feeds: [feed] }, 'read');
assert.deepEqual(Array.from(context.urls()), [secret]);
assert.equal(vm.runInContext(mask, context), true);
assert.deepEqual(JSON.parse(JSON.stringify(context.calendars())), [feed]);
context.feedRow = { index: 0 };
assert.equal(vm.runInContext(accessibleName, context), 'Calendar feed 1');
context.revealUrls = true;
assert.equal(vm.runInContext(mask, context), false);
context.revealUrls = false;

context.addFeed();
context.updateFeed(1, 'https://calendar.example/second');
context.request('test');
assert.deepEqual(Array.from(context.configProcess.command), ['/test/plugin/next_event.py', '--feeds-test']);
assert.ok(!context.configProcess.command.join(' ').includes(secret), 'Never pass URLs through argv');
assert.deepEqual(JSON.parse(context.configProcess.payload).urls, [secret, 'https://calendar.example/second']);
context.request('save');
assert.equal(context.configProcess.action, 'test', 'Disable overlapping operations');
result({ status: 'ok', results: [{ ok: true }, { ok: false, error: 'Check sharing link.' }] }, 'test');
assert.equal(rows[0].feedback, 'Connected · valid calendar');
assert.equal(rows[1].feedback, 'Check sharing link.');
assert.ok(context.message.includes('1 of 2'));
assert.equal(saves, 0, 'Testing does not save');
assert.ok(!context.message.includes(secret));
context.updateFeed(1, 'https://calendar.example/fixed');
assert.equal(rows[1].feedback, '');
assert.equal(context.message, '');

rows[0].name = 'Office';
rows[0].hideTitles = true;
context.request('save');
assert.equal(JSON.parse(context.configProcess.payload).feeds[0].name, 'Office');
assert.equal(JSON.parse(context.configProcess.payload).feeds[0].hideTitles, true);
assert.equal(JSON.parse(context.configProcess.payload).feeds[0].id, 'work');
assert.ok(!context.configProcess.command.join(' ').includes(secret));
result({ status: 'error', error: 'Cannot save settings.' }, 'save');
assert.equal(context.open, true, 'Failed saves keep the editor open');
assert.equal(saves, 0);
context.request('save');
result({ status: 'ok', calendars: [{ id: 'work', name: 'Office', hideTitles: true }] }, 'save');
assert.equal(saves, 1);
assert.deepEqual(savedCalendars, [{ id: 'work', name: 'Office', hideTitles: true }]);
assert.equal(context.open, false);
assert.equal(rows.length, 0, 'Discard secret-bearing drafts on close');
assert.equal(context.revealUrls, false);

context.show();
result({ status: 'ok', feeds: [] }, 'read');
assert.equal(rows[0].hideTitles, true, 'New calendars hide titles by default');
assert.ok(rows[0].calendarId);
assert.equal(rows.length, 1, 'New users get an empty URL field');
context.updateFeed(0, secret);
context.dismiss();
assert.equal(rows.length, 0);
assert.equal(saves, 1, 'Cancel never saves');

// Ignore old test results when reopening while a request is still finishing.
context.configProcess.running = true;
context.show();
assert.equal(context.pendingRead, true);
context.applyResult(JSON.stringify({ status: 'ok', results: [{ ok: true }] }), 'test');
assert.equal(rows.length, 0);
context.pendingRead = false;
context.dismiss();
context.applyResult(JSON.stringify({ status: 'ok', feeds: [feed] }), 'read');
assert.equal(rows.length, 0, 'Closed panels must not retain newly loaded secrets');
// A failed read must never silently replace unknown existing feeds with an empty list.
context.configProcess.running = false;
context.show();
result({ status: 'error', error: 'Calendar settings could not be accessed or saved.' }, 'read');
assert.equal(rows.length, 0);
const saveEnabled = source.match(/text: "Save & refresh"[^]*?enabled: ([^\n]+)/)[1];
assert.equal(vm.runInContext(saveEnabled, context), false, 'Save button stays disabled after a failed load');
context.request('save');
assert.equal(context.configProcess.action, 'read', 'Save must be blocked after a failed load');
assert.equal(saves, 1);
assert.equal(context.configProcess.running, false);
// Malformed successful responses also fail closed rather than being treated as an empty config.
context.show();
result({ status: 'ok' }, 'read');
context.request('save');
assert.equal(context.configProcess.action, 'read');
assert.equal(context.configProcess.running, false);
context.request('read');
result({ status: 'ok', feeds: [] }, 'read');
assert.equal(vm.runInContext(saveEnabled, context), true, 'Successful empty read remains savable');
context.request('save');
assert.equal(context.configProcess.action, 'save');
assert.deepEqual(JSON.parse(context.configProcess.payload).feeds.map(value => value.url), ['']); // Empty first-run field must be filled or removed.
// A save completing after Cancel/reopen must use persisted metadata, not cleared drafts.
context.dismiss();
result({ status: 'ok', calendars: [{ id: 'work', name: 'Saved', hideTitles: false }] }, 'save');
assert.deepEqual(savedCalendars, [{ id: 'work', name: 'Saved', hideTitles: false }]);
assert.equal(rows.length, 0);
console.log('ok: masked feed editor, safe request transport, tests, save, cancel, stale responses, failed-load protection');
