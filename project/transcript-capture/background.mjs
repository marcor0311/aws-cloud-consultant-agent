// Integration for the pinned TranscripTonic caption observer (MIT).
const fields = ['captureId', 'meetingUrl', 'captureClosed', 'reporterName',
  'meetingStartTimestamp', 'transcript'];

export function envelope(capture) {
  if (!capture.captureClosed) throw new Error('incomplete_capture');
  const segments = (capture.transcript || []).filter(s => s.transcriptText?.trim()).map(s => ({
    speaker: s.personName, at: s.timestamp, text: s.transcriptText,
  }));
  if (!segments.length) throw new Error('empty_capture');
  return {
    capture_id: capture.captureId, meeting_url: capture.meetingUrl,
    started_at: capture.meetingStartTimestamp, ended_at: capture.endedAt,
    reporter_name: capture.reporterName || '', segments,
  };
}

export async function deliver(capture, config, request = fetch) {
  if (config.url !== 'http://127.0.0.1:8000/api/workflow/events/transcript' || config.token.length < 32) {
    throw new Error('invalid_local_configuration');
  }
  const response = await request(config.url, {
    method: 'POST', redirect: 'error', signal: AbortSignal.timeout(8000),
    headers: {'Content-Type': 'application/json', Authorization: `Bearer ${config.token}`},
    body: JSON.stringify(envelope(capture)),
  });
  if (response.status !== 202) throw new Error(`backend_http_${response.status}`);
  const result = await response.json();
  if (!['accepted', 'duplicate'].includes(result.status)) throw new Error('invalid_backend_receipt');
  return result;
}

export function install(chromeApi = chrome, request = fetch) {
  let serial = Promise.resolve();
  let sending;
  const local = chromeApi.storage.local;
  const config = () => request(chromeApi.runtime.getURL('backend-config.json')).then(r => r.json());

  async function retry() {
    if (sending) return sending;
    sending = (async () => {
      const {captures = []} = await local.get('captures');
      const credentials = await config();
      for (const saved of captures.filter(c => c.status === 'pending')) {
        try {
          await deliver(saved, credentials, request);
          saved.status = 'delivered';
          saved.error = '';
        } catch (error) {
          saved.error = error.message;
        }
      }
      await local.set({captures});
    })();
    try { await sending; } finally { sending = undefined; }
  }

  async function archive(normalClose) {
    const current = await local.get([...fields, 'captures']);
    const captures = current.captures || [];
    if (current.captureId && !captures.some(c => c.captureId === current.captureId)) {
      const saved = Object.fromEntries(fields.map(k => [k, current[k]]));
      saved.endedAt = new Date().toISOString();
      saved.captureClosed = normalClose && current.captureClosed === true;
      saved.status = saved.captureClosed && saved.transcript?.length ? 'pending' : 'incomplete';
      captures.push(saved);
    }
    await local.set({captures, activeTab: null});
    await retry();
  }

  chromeApi.runtime.onMessage.addListener((message, sender, respond) => {
    if (message.type === 'consulting_retry' && !sender.tab) {
      serial = serial.then(retry).then(() => respond({success: true})).catch(() => respond({success: false}));
      return true;
    }
    if (!sender.tab || !/^https:\/\/meet\.google\.com\/(?:meet\/)?[a-z]{3}-[a-z]{4}-[a-z]{3}(?:[?#]|$)/.test(sender.url || '')) return false;
    serial = serial.then(async () => {
      if (message.type === 'consulting_preflight') {
        const {activeTab} = await local.get('activeTab');
        if (activeTab != null) {
          respond({success: false});
          return;
        }
        await local.set({activeTab: sender.tab.id});
      } else if (message.type === 'meeting_ended') {
        const {activeTab} = await local.get('activeTab');
        if (activeTab !== sender.tab.id) throw new Error('inactive_tab');
        await archive(true);
      }
      // Upstream's recovery request never publishes an unclosed capture.
      respond({success: true});
    }).catch(() => respond({success: false}));
    return true;
  });
  chromeApi.tabs.onRemoved.addListener(tabId => {
    serial = serial.then(async () => {
      const {activeTab} = await local.get('activeTab');
      if (activeTab === tabId) await archive(false);
    }).catch(() => {});
  });
  chromeApi.alarms.onAlarm.addListener(alarm => {
    if (alarm.name === 'retry-transcripts') serial = serial.then(retry).catch(() => {});
  });
  chromeApi.runtime.onInstalled.addListener(async () => {
    await chromeApi.storage.sync.set({operationMode: 'auto', hideCaptions: false});
    await chromeApi.alarms.create('retry-transcripts', {periodInMinutes: 1});
  });
  chromeApi.runtime.onStartup.addListener(() => {
    serial = serial.then(async () => {
      const {activeTab} = await local.get('activeTab');
      if (activeTab != null) {
        try { await chromeApi.tabs.get(activeTab); }
        catch { await archive(false); }
      }
      await retry();
    }).catch(() => {});
  });
}

if (globalThis.chrome?.runtime?.onMessage) install();
