// Run with: node privacy_test.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(`${__dirname}/BarWidget.qml`, 'utf8');
const manifest = JSON.parse(fs.readFileSync(`${__dirname}/manifest.json`, 'utf8'));
assert.equal(manifest.id, 'io.github.barlevalon.next-event');
const readme = fs.readFileSync(`${__dirname}/README.md`, 'utf8');
assert.ok(readme.includes(`omarchy plugin update ${manifest.id}`));
assert.ok(readme.includes(`omarchy plugin remove ${manifest.id}`));
assert.equal(source.match(/  moduleName: "([^"]+)"/)[1], manifest.id);
const pluginDir = source.match(/readonly property string pluginDir: ([^\n]+)/)[1];
const helperContext = vm.createContext({
  String, decodeURIComponent,
  Qt: { resolvedUrl: () => 'file:///home/test%20user/.config/omarchy/plugins/' + manifest.id + '/' },
});
assert.equal(vm.runInContext(pluginDir, helperContext),
  '/home/test user/.config/omarchy/plugins/' + manifest.id);
assert.ok(!pluginDir.includes('XDG_CONFIG_HOME'), 'Code location must follow QML source, not feed-data storage');
for (const file of ['BarWidget.qml', 'FeedSettings.qml']) {
  const qml = fs.readFileSync(`${__dirname}/${file}`, 'utf8');
  assert.ok(qml.includes('import qs.Commons as Commons'));
  assert.ok(!/(?<!Commons\.)\bColor\./.test(qml), 'Palette must not collide with QtQuick.Color');
}
const event = {
  title: 'Confidential review',
  calendarId: 'work',
  start: '2026-08-29T15:00:00Z',
  end: '2026-08-29T15:30:00Z',
  ongoing: false,
  meetingUrl: 'https://meet.google.com/secret-room',
};
const commands = [];
let hidden = 0;
let refreshed = 0;
const context = vm.createContext({
  Date, Object,
  calendarsData: [], configGeneration: 0, privacyError: '', privacySaving: false,
  privacyProcess: { running: false }, fetchProcess: { running: false },
  peerWidgets() { return [context]; },
  moduleName: manifest.id,
  status: 'ok', errorText: '', eventData: event, eventsData: [],
  mounted: true, updateOwner: true,
  popupOpen: false, selectedKey: '', notified: {},
  notificationTimer: { stop() {}, start() {} },
  notificationCommand: 'omarchy-notification-send',
  button: {},
  openProcess: { running: false },
  feedSettings: { open: false, shown: 0, show() { this.shown++; this.open = true; }, dismiss() { this.open = false; } },
  broadcast(method) { assert.equal(method, 'refresh'); refreshed++; },
  bar: {
    hideTooltip() { hidden++; },

  },

  refresh() { refreshed++; },
  Qt: { LeftButton: 1, RightButton: 2, MiddleButton: 4,
    formatTime(date) { return date.toISOString().slice(11, 16); } },
  Quickshell: { execDetached(command) { commands.push(command); } },
});
context.root = context;
for (const name of ['calendarFor', 'titlesHidden', 'eventTitle', 'eventChoiceTitle', 'eventTiming', 'togglePrivacy',
  'savePrivacy', 'applyPrivacyResult', 'updateCalendars', 'feedsSaved',
  'closePicker', 'close', 'openFeedSettings', 'joinEvent', 'eventKey', 'sendNotification', 'checkNotifications', 'applyResult']) {
  const body = source.match(new RegExp(`  function ${name}\\([^]*?\\n  }`));
  assert.ok(body, `Missing ${name}`);
  vm.runInContext(body[0], context);
}
const privacy = source.match(/readonly property bool privacyMode: ([^\n]+)/)[1];
const hint = source.match(/readonly property string privacyHint: ([^]*?)\n\n/)[1];
const label = source.match(/readonly property string label: \{([^]*?)\n  }/)[1];
const details = source.match(/readonly property string details: \{([^]*?)\n  }/)[1];
const press = source.match(/onPressed: function\(button\) \{([^]*?)\n    }/)[1];
const hideTooltip = source.match(/onCalendarsDataChanged: ([^\n]+)/)[1];
const overlaps = source.match(/readonly property var overlapEvents: \{([^]*?)\n  }/)[1];
const selection = source.match(/readonly property var selectedEvent: ([^\n]+)/)[1];
function render() {
  context.privacyMode = vm.runInContext(privacy, context);
  context.privacyHint = vm.runInContext(hint, context);
  context.overlapEvents = vm.runInContext(`(function() {${overlaps}})()`, context);
  context.selectedEvent = vm.runInContext(selection, context);
  return ['label', 'details'].map((name, i) =>
    vm.runInContext(`(function() {${[label, details][i]} })()`, context));
}
function click(button) {
  context.clickedButton = button;
  vm.runInContext(`(function(button) {${press}})(clickedButton)`, context);
}

// Missing or malformed calendar preferences must never reveal details.
for (const calendars of [[], [{ id: 'work', name: 'Work' }],
  [{ id: 'work', name: 'Work', hideTitles: true }], [{ id: 'work', name: 'Work', hideTitles: 'false' }]]) {
  context.calendarsData = calendars;
  const output = render().join('\n');
  assert.equal(context.privacyMode, true);
  assert.ok(output.includes('Private event'));
  assert.ok(output.includes('15:00'));
  assert.ok(!output.includes(event.title));
  assert.ok(!output.includes(event.meetingUrl));
}
context.sendNotification(event, false);
assert.ok(commands.at(-1).some(text => text.startsWith('Event in ')));
assert.ok(commands.at(-1).some(text => text.includes('Private event')));
assert.ok(!commands.at(-1).includes('--exec'));
assert.ok(!commands.at(-1).join(' ').includes(event.title));
assert.ok(!commands.at(-1).join(' ').includes(event.meetingUrl));
context.sendNotification(event, true);
assert.ok(commands.at(-1).includes('Event starting now'));

context.calendarsData = [{ id: 'work', name: 'Work', hideTitles: true },
  { id: 'personal', name: 'Personal', hideTitles: true }];
render();
assert.ok(context.privacyHint.includes('reveal titles for Work'));
click(2);
assert.deepEqual(JSON.parse(context.privacyProcess.payload), { calendarId: 'work', hideTitles: false });
assert.ok(!context.privacyProcess.payload.includes(event.meetingUrl));
assert.ok(!render().join('\n').includes(event.title), 'Do not reveal until persistence succeeds');
click(2);
assert.equal(JSON.parse(context.privacyProcess.payload).hideTitles, false, 'Ignore repeat clicks during a save');
function finishPrivacy(hidden) {
  context.applyPrivacyResult(JSON.stringify({ status: 'ok', calendars: [
    { id: 'work', name: 'Work', hideTitles: hidden },
    { id: 'personal', name: 'Personal', hideTitles: true },
  ] }));
  context.privacyProcess.running = false;
}
finishPrivacy(false);
assert.ok(render().every(text => text.includes(event.title)));
assert.ok(render()[0].includes('Work · '));
assert.equal(context.calendarsData[1].hideTitles, true);
assert.ok(context.privacyHint.includes('hide titles for Work'));
vm.runInContext(hideTooltip, context);
assert.equal(hidden, 1);
context.sendNotification(event, true);
assert.ok(commands.at(-1).join(' ').includes(event.title));
assert.ok(commands.at(-1).includes(event.meetingUrl));

click(2);
assert.equal(JSON.parse(context.privacyProcess.payload).hideTitles, true);
finishPrivacy(true);
render();
click(1);
assert.deepEqual(Array.from(context.openProcess.command), ['xdg-open', event.meetingUrl]);
click(4);
assert.equal(context.feedSettings.shown, 1);
assert.equal(refreshed, 0);
context.eventData = { ...event, ongoing: true };
assert.ok(render()[0].startsWith('now'));
context.eventData = null;
for (const hideTitles of [true, false]) {
  context.calendarsData = [{ id: 'work', name: 'Work', hideTitles }];
  assert.equal(render()[0], '\uf133', 'Keep feed settings reachable when no events remain');
}
context.calendarsData = [{ id: 'work', name: 'Work', hideTitles: true }];
context.errorText = `Failed to fetch ${event.meetingUrl}`;
assert.ok(!render()[1].includes(event.meetingUrl));
context.status = 'setup';
assert.ok(!render()[1].includes('Right-click'), 'No calendar toggle when no event is displayed');
// Same-schedule entries must both be visible, with explicit selection before joining.
const second = { ...event, title: 'Team sync', meetingUrl: 'https://meet.google.com/second-room' };
function setEvents(events) {
  context.status = 'ok';
  context.errorText = '';
  context.eventsData = events;
  context.eventData = events[0] ? { ...events[0] } : null; // Backend emits separate objects.
  return render();
}
context.calendarsData = [{ id: 'work', name: 'Work', hideTitles: false }];
let output = setEvents([event, second]);
assert.ok(output[0].endsWith('+1 overlap'));
assert.ok(output[1].includes(event.title) && output[1].includes(second.title));
assert.ok(output[1].includes('15:00–15:30 · upcoming'));
assert.ok(output[1].includes('Left-click: choose event'));
context.openProcess = { running: false };
click(4);
assert.equal(context.feedSettings.open, true);
click(1);
assert.equal(context.popupOpen, true);
assert.equal(context.feedSettings.open, false, 'Opening the picker must dismiss settings');
assert.equal(context.selectedEvent, null);
assert.equal(context.openProcess.command, undefined, 'Opening the picker must not join the first event');
context.selectedKey = context.eventKey(second);
render();
context.joinEvent(context.selectedEvent);
assert.deepEqual(Array.from(context.openProcess.command), ['xdg-open', second.meetingUrl]);
assert.equal(context.popupOpen, false);
assert.equal(context.selectedKey, '');

// Privacy applies to every conflict title, including numbered picker/accessibility labels.
context.calendarsData = [{ id: 'work', name: 'Work', hideTitles: true }];
output = render();
assert.ok(output[1].includes('Private event 1') && output[1].includes('Private event 2'));
for (const item of [event, second]) {
  assert.ok(!output.join('\n').includes(item.title));
  assert.ok(!output.join('\n').includes(item.meetingUrl));
  assert.ok(!context.eventChoiceTitle(item, 0).includes(item.title));
}
const pickerTitle = source.match(/text: (root\.eventChoiceTitle\(eventRow[^\n]+)/)[1];
const accessibleName = source.match(/Accessible.name: ([^\n]+)/)[1];
context.eventRow = { modelData: second, index: 1 };
context.modelData = second;
context.index = 1;
assert.equal(vm.runInContext(pickerTitle, context), 'Work · Private event 2');
assert.ok(!vm.runInContext(accessibleName, context).includes(second.title));
context.calendarsData = [{ id: 'work', name: 'Work', hideTitles: false }];
render();
assert.equal(vm.runInContext(pickerTitle, context), 'Work · ' + second.title);

// Calendar privacy is independent in mixed-calendar overlaps and reminders.
const personal = { ...second, calendarId: 'personal' };
context.calendarsData.push({ id: 'personal', name: 'Personal', hideTitles: true });
output = setEvents([event, personal]);
assert.ok(output[1].includes(event.title));
assert.ok(output[1].includes('Personal · Private event 2'));
assert.ok(!output[1].includes(personal.title));
context.sendNotification(personal, true);
assert.ok(!commands.at(-1).join(' ').includes(personal.title));
assert.ok(!commands.at(-1).includes('--exec'));
context.sendNotification(event, true);
assert.ok(commands.at(-1).includes('--exec'));
assert.notEqual(context.eventKey(event), context.eventKey({ ...event, calendarId: 'personal' }));

// Do not overwrite editor drafts; no-op without a displayed calendar.
context.editingFeeds = true;
const beforeDraftClick = context.privacyProcess.payload;
click(2);
assert.equal(context.privacyProcess.payload, beforeDraftClick);
assert.ok(context.privacyError.includes('Close calendar settings'));
context.editingFeeds = false;
context.status = 'error';
click(2);
assert.equal(context.privacyProcess.payload, beforeDraftClick);
context.status = 'ok';

// Failed saves leave privacy unchanged; in-flight fetches are invalidated on success.
context.applyPrivacyResult(JSON.stringify({ status: 'error' }));
assert.equal(context.calendarsData[0].hideTitles, false);
assert.ok(context.privacyError.includes('could not be saved'));
context.fetchProcess.running = true;
context.refreshPending = false;
const generation = context.configGeneration;
finishPrivacy(true);
assert.equal(context.configGeneration, generation + 1);
assert.equal(context.refreshPending, true);
context.fetchProcess.running = false;
finishPrivacy(false);
setEvents([event, second]);

// Partial, contained and spanning conflicts count; adjacent and zero-duration entries don't.
function at(title, start, end) {
  return { ...second, title, start: `2026-08-29T${start}:00Z`, end: `2026-08-29T${end}:00Z` };
}
for (const other of [at('Partial', '15:10', '15:40'), at('Contained', '15:10', '15:20'),
  at('Spanning', '14:50', '15:40')]) {
  setEvents([event, other]);
  assert.equal(context.overlapEvents.length, 2);
}
for (const other of [at('Adjacent after', '15:30', '16:00'), at('Adjacent before', '14:30', '15:00'),
  at('Instant', '15:10', '15:10')]) {
  output = setEvents([event, other]);
  assert.equal(context.overlapEvents.length, 1);
  assert.ok(!output[0].includes('overlap'));
}
setEvents([at('Instant primary', '15:00', '15:00'), event]);
assert.equal(context.overlapEvents.length, 1);
const instant = at('Same instantaneous event', '15:00', '15:00');
output = setEvents([instant, { ...instant }]);
assert.equal(context.overlapEvents.length, 1, 'Identical zero-duration events must not create overlaps');
assert.ok(!output[0].includes('overlap'));
setEvents([event, at('Partial', '15:10', '15:40'), at('Not a direct conflict', '15:35', '16:00')]);
assert.equal(context.overlapEvents.length, 2);
output = setEvents([event, second, { ...second, title: 'Third' }]);
assert.ok(output[0].endsWith('+2 overlaps'));
setEvents([{ ...event, ongoing: true }, second]);
assert.ok(render()[1].includes('15:00–15:30 · now'));

// Entries without meeting links stay inspectable but cannot be joined.
const noLink = { ...second, meetingUrl: '' };
setEvents([event, noLink]);
context.openProcess = { running: false };
context.selectedKey = context.eventKey(noLink);
render();
context.joinEvent(context.selectedEvent);
assert.equal(context.openProcess.command, undefined);
context.selectedKey = context.eventKey(second);
setEvents([event]);
assert.equal(context.selectedEvent, null, 'Removed entries must not remain joinable');
setEvents([]);
assert.equal(context.overlapEvents.length, 0);

// Reminder scheduling still covers both simultaneous entries and deduplicates each phase.
const now = Date.parse('2026-08-29T14:45:00Z');
context.Date = class extends Date { static now() { return now; } };
setEvents([event, second]);
context.notified = {};
commands.length = 0;
context.checkNotifications();
assert.equal(commands.length, 2);
context.checkNotifications();
assert.equal(commands.length, 2);
context.Date = class extends Date { static now() { return Date.parse(event.start); } };
context.checkNotifications();
assert.equal(commands.length, 4);
assert.ok(commands.slice(2).every(command => command.includes('Event starting now')));
context.checkNotifications();
assert.equal(commands.length, 4);
context.Date = Date;

// Failed refreshes must not open a stale picker or join an old event.
context.status = 'error';
render();
assert.equal(context.overlapEvents.length, 0);
context.openProcess = { running: false };
click(1);
assert.equal(context.openProcess.command, undefined);
context.status = 'setup';
render();
const shownBeforeSetup = context.feedSettings.shown;
click(1);
assert.equal(context.feedSettings.shown, shownBeforeSetup + 1, 'Setup opens the feed editor');
const savedRefresh = source.match(/onSaved: function\(calendars\) \{ ([^]*?) }/)[1];
context.calendars = context.calendarsData;
const refreshBeforeSave = refreshed;
vm.runInContext(savedRefresh, context);
assert.equal(refreshed, refreshBeforeSave + 1, 'Save must request one shared refresh for every monitor');
assert.ok(!source.includes('updateEntryInline'), 'Calendar config is the only privacy persistence');
console.log('ok: privacy, overlap detection, picker selection, join, reminders, setup access, exclusive panels, shared refresh');
