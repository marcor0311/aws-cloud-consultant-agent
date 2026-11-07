import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {join} from 'node:path';
import vm from 'node:vm';
import {webcrypto} from 'node:crypto';
import {deliver, envelope, install} from './background.mjs';


const config = {url: 'http://127.0.0.1:8000/api/workflow/events/transcript', token: 'offline-only-key-12345678901234567890'};
const capture = () => ({captureId: '41cd930a-a017-4bca-82bc-a9957b3b9344',
  meetingUrl: 'https://meet.google.com/abc-defg-hij', captureClosed: true,
  reporterName: 'Stuart', meetingStartTimestamp: '2026-11-09T16:00:00Z', endedAt: '2026-11-09T16:20:00Z',
  transcript: ['Stuart', 'Ana', 'Luis', 'María'].map((personName, i) => ({personName,
    timestamp: `2026-11-09T16:0${i}:10Z`, transcriptText: `Intervención de ${personName}`}))});

test('wire payload keeps several named speakers and refuses an unclosed capture', () => {
  assert.deepEqual(envelope(capture()).segments.map(s => s.speaker), ['Stuart', 'Ana', 'Luis', 'María']);
  assert.throws(() => envelope({...capture(), captureClosed: false}), /incomplete/);
});

test('delivery is authenticated, fixed to localhost and rejects redirects or bad receipts', async () => {
  let sent;
  await deliver(capture(), config, async (url, options) => {
    sent = {url, ...options};
    return {status: 202, json: async () => ({status: 'accepted'})};
  });
  assert.equal(sent.headers.Authorization, `Bearer ${config.token}`);
  assert.equal(sent.redirect, 'error');
  assert.equal(JSON.parse(sent.body).segments.length, 4);
  await assert.rejects(deliver(capture(), {...config, url: 'https://elsewhere.test'}), /configuration/);
  await assert.rejects(deliver(capture(), config, async () => ({status: 401})), /401/);
});

function fakeChrome() {
  const data = {};
  const listeners = {};
  const event = name => ({addListener: fn => {listeners[name] = fn;}});
  const chromeApi = {
    storage: {local: {
      get: async keys => Object.fromEntries((Array.isArray(keys) ? keys : [keys]).filter(k => k in data).map(k => [k, structuredClone(data[k])])),
      set: async value => Object.assign(data, structuredClone(value)),
    }, sync: {set: async () => {}}},
    runtime: {onMessage: event('message'), onInstalled: event('installed'), onStartup: event('startup'), getURL: path => `chrome-extension://test/${path}`},
    tabs: {onRemoved: event('removed'), get: async () => {throw Error('closed');}},
    alarms: {onAlarm: event('alarm'), create: async () => {}},
  };
  const message = (body, sender = {}) => new Promise(resolve => {
    if (!listeners.message(body, sender, resolve)) resolve(undefined);
  });
  return {chromeApi, data, listeners, message};
}

const sender = {tab: {id: 7}, url: 'https://meet.google.com/abc-defg-hij'};

test('capture is archived before delivery; failure survives until a retry', async () => {
  const fake = fakeChrome();
  let online = false;
  install(fake.chromeApi, async url => {
    if (url.startsWith('chrome-extension:')) return {json: async () => config};
    assert.equal(fake.data.captures.length, 1);
    if (!online) throw Error('offline');
    return {status: 202, json: async () => ({status: 'accepted'})};
  });
  await fake.message({type: 'consulting_preflight'}, sender);
  Object.assign(fake.data, capture());
  await fake.message({type: 'meeting_ended'}, sender);
  assert.equal(fake.data.captures[0].status, 'pending');
  online = true;
  await fake.message({type: 'consulting_retry'});
  assert.equal(fake.data.captures[0].status, 'delivered');
  assert.equal(fake.data.captures.length, 1);
});

test('a second Meet tab is rejected and a tab closed abruptly never publishes', async () => {
  const fake = fakeChrome();
  let backendCalls = 0;
  install(fake.chromeApi, async url => {
    if (!url.startsWith('chrome-extension:')) backendCalls++;
    return {json: async () => config};
  });
  assert.equal((await fake.message({type: 'consulting_preflight'}, sender)).success, true);
  assert.equal((await fake.message({type: 'consulting_preflight'}, {...sender, tab: {id: 8}})).success, false);
  Object.assign(fake.data, capture(), {captureClosed: false});
  fake.listeners.removed(7);
  await fake.message({type: 'consulting_retry'});
  assert.equal(fake.data.captures[0].status, 'incomplete');
  assert.equal(backendCalls, 0);
});

test('preflight accepts the current Meet room URL format', async () => {
  const fake = fakeChrome();
  install(fake.chromeApi, async () => {throw Error('no delivery expected');});
  const response = await fake.message({type: 'consulting_preflight'}, {
    tab: {id: 9}, url: 'https://meet.google.com/meet/fbh-uqjg-eds',
  });
  assert.equal(response.success, true);
});

test('starts capture when Meet navigates from home to a meeting without reloading', {skip: !process.env.CAPTURE_EXTENSION_DIR}, async () => {
  const source = await readFile(join(process.env.CAPTURE_EXTENSION_DIR,
    'content-scripts/google-meet/index.js'), 'utf8');
  const timers = [];
  const messages = [];
  const context = vm.createContext({
    location: {pathname: '/home'},
    chrome: {runtime: {sendMessage: (message, callback) => {
      messages.push(message);
      callback({success: false});
    }}},
    setInterval: callback => {timers.push(callback); return timers.length;},
    clearInterval() {},
    console: {warn() {}, log() {}, error() {}},
  });
  vm.runInContext(source, context);
  assert.equal(messages.length, 0);
  context.location.pathname = '/meet/fbh-uqjg-eds';
  timers[0]();
  assert.deepEqual(messages.map(message => message.type), ['consulting_preflight']);
});

test('pinned observer captures revised captions with four speakers and final flush', {skip: !process.env.CAPTURE_EXTENSION_DIR}, async () => {
  const root = process.env.CAPTURE_EXTENSION_DIR;
  const stored = {};
  const context = vm.createContext({crypto: webcrypto, location: {origin: 'https://meet.google.com', pathname: '/abc-defg-hij'},
    document: {title: 'Inicial', querySelector: () => null},
    chrome: {storage: {local: {set: (value, callback) => {Object.assign(stored, value); callback?.();}}},
      runtime: {sendMessage: (body, callback) => callback?.({success: body.type !== 'consulting_preflight'})}},
    console: {log() {}, warn() {}, error() {}}, setTimeout, clearTimeout,
    setInterval: () => 1, clearInterval() {},
  });
  for (const name of ['common-config.js', 'common-utils.js', 'google-meet/config.js', 'google-meet/utils.js', 'google-meet/index.js']) {
    vm.runInContext(await readFile(join(root, 'content-scripts', name), 'utf8'), context);
  }
  vm.runInContext('var fixtureState = createContentScriptState("Google Meet", "google_meet"); fixtureState.userName = "Stuart";', context);
  function row(speaker, text) {
    const element = {previousSibling: {textContent: speaker}, textContent: text};
    const parent = {parentElement: {children: []}};
    parent.parentElement.children = [parent, {}, {}];
    element.parentElement = parent;
    return {type: 'characterData', target: {parentElement: element}};
  }
  const first = row('Tú', 'Hola');
  context.mutations = [first];
  vm.runInContext('transcriptMutationCallbackGoogleMeet(fixtureState, mutations)', context);
  first.target.parentElement.textContent = 'Hola a todos.';
  vm.runInContext('transcriptMutationCallbackGoogleMeet(fixtureState, mutations)', context);
  for (const name of ['Ana', 'Luis', 'María']) {
    context.mutations = [row(name, `Habla ${name}`)];
    vm.runInContext('transcriptMutationCallbackGoogleMeet(fixtureState, mutations)', context);
  }
  vm.runInContext('pushBufferToTranscript(fixtureState); overWriteChromeStorage(fixtureState, ["transcript"], true);', context);
  assert.deepEqual(Array.from(stored.transcript, s => s.personName), ['Stuart', 'Ana', 'Luis', 'María']);
  assert.equal(stored.transcript[0].transcriptText, 'Hola a todos.');
  assert.equal(stored.captureClosed, true);
});
