const assert = require('node:assert/strict');
const test = require('node:test');
const {
  extractExportOptions,
  mergeSyncedOptions,
  normalizeCardFormats,
  compareCardFormats,
  createSyncHandler,
} = require('../yomitan_sync.js');

const LAPIS_FORMAT = {
  name: 'Expression', icon: 'big-circle', type: 'term', deck: 'General Mining', model: 'Lapis',
  fields: {
    Expression: { value: '{expression}', overwriteMode: 'coalesce' },
    Sentence: { value: '{cloze-prefix}<b>{cloze-body}</b>{cloze-suffix}', overwriteMode: 'coalesce' },
    PitchPosition: { value: '{pitch-accent-positions}', overwriteMode: 'coalesce' },
  },
};

function firefoxOptions() {
  return {
    version: 77, profileCurrent: 0, global: { database: { prefixWildcardsSupported: false } },
    profiles: [{ name: 'Default', conditionGroups: [], options: {
      general: {
        language: 'ja', resultOutputMode: 'group', glossaryLayoutMode: 'default', compactTags: false,
        mainDictionary: 'Jitendex.org [2026-09-01]', sortFrequencyDictionary: 'JPDBv2', sortFrequencyDictionaryOrder: 'ascending',
        averageFrequency: true, popupWidth: 400, popupTheme: 'site', maxResults: 32,
      },
      popupWindow: { width: 400 },
      scanning: { inputs: ['firefox-scan'], delay: 0 },
      inputs: { hotkeys: ['firefox-hotkey'] },
      clipboard: { enableBackgroundMonitor: false },
      accessibility: { forceGoogleDocsHtmlRendering: false },
      dictionaries: [
        { name: 'Jitendex.org [2026-09-01]', enabled: true, styles: '' },
        { name: 'Kanjium Pitch Accents', enabled: true, styles: '' },
        { name: 'JPDBv2', enabled: true, styles: '' },
      ],
      anki: {
        enable: true, server: 'http://127.0.0.1:8765', tags: ['yomitan'], fieldTemplates: null,
        cardFormats: [structuredClone(LAPIS_FORMAT), { name: 'Kanji', icon: 'big-circle', type: 'kanji', deck: '', model: '', fields: {} }],
        duplicateScope: 'collection',
      },
      translation: { searchResolution: 'letter' },
      parsing: { readingMode: 'hiragana' },
      audio: { enabled: true, sources: [] },
      sentenceParsing: { scanExtent: 200 },
    } }],
  };
}

function overlayOptions() {
  return {
    version: 77, profileCurrent: 1, global: { database: { prefixWildcardsSupported: true }, overlayOnly: true },
    profiles: [
      { name: 'Default', conditionGroups: [], options: { general: { popupWidth: 1 }, dictionaries: [], anki: { cardFormats: [] } } },
      { name: 'GSM - Lapis', conditionGroups: [{ conditions: [] }], options: {
        general: {
          language: 'ja', resultOutputMode: 'split', glossaryLayoutMode: 'compact', compactTags: true,
          mainDictionary: 'Old', sortFrequencyDictionary: null, sortFrequencyDictionaryOrder: 'descending',
          averageFrequency: false, popupWidth: 900, popupTheme: 'dark', maxResults: 8,
        },
        popupWindow: { width: 900 },
        scanning: { inputs: ['overlay-scan'], delay: 50 },
        inputs: { hotkeys: ['overlay-hotkey'] },
        clipboard: { enableBackgroundMonitor: true },
        accessibility: { forceGoogleDocsHtmlRendering: true },
        dictionaries: [
          { name: 'GSM Character Dictionary', enabled: true, styles: '' },
          { name: 'Jitendex.org [2025-07-05]', enabled: true, styles: '' },
        ],
        anki: { enable: true, server: 'http://127.0.0.1:8765', tags: ['GSM'], cardFormats: [] },
        translation: { searchResolution: 'word' },
        parsing: { readingMode: 'katakana' },
        audio: { enabled: false },
        sentenceParsing: { scanExtent: 50 },
      } },
    ],
  };
}

const installed = ['Jitendex.org [2026-09-01]', 'JPDBv2', 'GSM Character Dictionary', 'Unlisted Dict'];

test('accepts a full Yomitan export and the bare options object', () => {
  const options = firefoxOptions();
  assert.equal(extractExportOptions({ version: 0, date: 'x', options }), options);
  assert.equal(extractExportOptions(options), options);
  assert.throws(() => extractExportOptions({ version: 0 }), /not a Yomitan settings export/);
  assert.throws(() => extractExportOptions(null), /not a Yomitan settings export/);
});

test('takes card, dictionary and lookup sections from Firefox and keeps overlay window settings', () => {
  const overlay = overlayOptions();
  const before = structuredClone(overlay);
  const ff = firefoxOptions();
  const result = mergeSyncedOptions(overlay, ff, installed);
  assert.deepEqual(overlay, before, 'input must not be mutated');

  const merged = result.options.profiles[1].options;
  const source = ff.profiles[0].options;
  for (const section of ['anki', 'translation', 'parsing', 'audio', 'sentenceParsing']) {
    assert.deepEqual(merged[section], source[section], section);
  }
  for (const section of ['popupWindow', 'scanning', 'inputs', 'clipboard', 'accessibility']) {
    assert.deepEqual(merged[section], before.profiles[1].options[section], section);
  }
  // Card-content general keys follow Firefox; popup/window ones stay.
  assert.equal(merged.general.resultOutputMode, 'group');
  assert.equal(merged.general.glossaryLayoutMode, 'default');
  assert.equal(merged.general.compactTags, false);
  assert.equal(merged.general.mainDictionary, 'Jitendex.org [2026-09-01]');
  assert.equal(merged.general.sortFrequencyDictionary, 'JPDBv2');
  assert.equal(merged.general.sortFrequencyDictionaryOrder, 'ascending');
  assert.equal(merged.general.averageFrequency, true);
  assert.equal(merged.general.popupWidth, 900);
  assert.equal(merged.general.popupTheme, 'dark');
  assert.equal(merged.general.maxResults, 8);

  // Profile identity, other profiles and global settings stay the overlay's.
  assert.equal(result.options.profileCurrent, 1);
  assert.equal(result.options.profiles[1].name, 'GSM - Lapis');
  assert.deepEqual(result.options.profiles[1].conditionGroups, before.profiles[1].conditionGroups);
  assert.deepEqual(result.options.profiles[0], before.profiles[0]);
  assert.deepEqual(result.options.global, before.global);
  assert.equal(result.profileName, 'GSM - Lapis');
  assert.equal(result.sourceProfileName, 'Default');
});

test('dictionary order follows Firefox; missing ones are reported; overlay-only ones are kept', () => {
  const result = mergeSyncedOptions(overlayOptions(), firefoxOptions(), installed);
  const dictionaries = result.options.profiles[1].options.dictionaries;
  assert.deepEqual(dictionaries.map((d) => [d.name, d.enabled]), [
    ['Jitendex.org [2026-09-01]', true],
    ['JPDBv2', true],
    ['GSM Character Dictionary', true],
    ['Unlisted Dict', false],
  ]);
  assert.deepEqual(result.missingDictionaries, ['Kanjium Pitch Accents']);
});

test('without the installed list the Firefox dictionary list is copied as-is', () => {
  const ff = firefoxOptions();
  const result = mergeSyncedOptions(overlayOptions(), ff, null);
  assert.deepEqual(result.options.profiles[1].options.dictionaries, ff.profiles[0].options.dictionaries);
  assert.deepEqual(result.missingDictionaries, []);
});

test('a non-localhost Anki server in the export is not copied', () => {
  const ff = firefoxOptions();
  ff.profiles[0].options.anki.server = 'http://example.com:8765';
  const merged = mergeSyncedOptions(overlayOptions(), ff, installed).options.profiles[1].options;
  assert.equal(merged.anki.server, 'http://127.0.0.1:8765');
  assert.deepEqual(merged.anki.cardFormats, ff.profiles[0].options.anki.cardFormats);
});

test('uses the export\'s current profile and rejects broken input', () => {
  const ff = firefoxOptions();
  ff.profiles.push({ name: 'Second', conditionGroups: [], options: structuredClone(ff.profiles[0].options) });
  ff.profiles[1].options.anki.cardFormats[0].deck = 'Other deck';
  ff.profileCurrent = 1;
  const merged = mergeSyncedOptions(overlayOptions(), ff, installed);
  assert.equal(merged.sourceProfileName, 'Second');
  assert.equal(merged.options.profiles[1].options.anki.cardFormats[0].deck, 'Other deck');
  assert.throws(() => mergeSyncedOptions({ profiles: [] }, firefoxOptions(), installed), /overlay Yomitan settings/);
  assert.throws(() => mergeSyncedOptions(overlayOptions(), { profiles: [] }, installed), /export has no profile/);
});

test('card format comparison is field by field and ignores icons', () => {
  const a = normalizeCardFormats({ cardFormats: [LAPIS_FORMAT] });
  const b = normalizeCardFormats({ cardFormats: [{ ...structuredClone(LAPIS_FORMAT), icon: 'small-circle' }] });
  assert.deepEqual(compareCardFormats(a, b), []);

  const changed = structuredClone(LAPIS_FORMAT);
  changed.deck = 'Other';
  changed.fields.Sentence.value = '{sentence}';
  changed.fields.PitchPosition.overwriteMode = 'overwrite';
  delete changed.fields.Expression;
  changed.fields.Extra = { value: '', overwriteMode: 'coalesce' };
  const diffs = compareCardFormats(a, normalizeCardFormats({ cardFormats: [changed] }));
  assert.ok(diffs.some((d) => d.includes('deck')), diffs.join('\n'));
  assert.ok(diffs.some((d) => d.includes('Sentence') && d.includes('value')), diffs.join('\n'));
  assert.ok(diffs.some((d) => d.includes('PitchPosition') && d.includes('overwriteMode')), diffs.join('\n'));
  assert.ok(diffs.some((d) => d.includes('Expression') && d.includes('missing')), diffs.join('\n'));
  assert.ok(diffs.some((d) => d.includes('Extra') && d.includes('only in the overlay')), diffs.join('\n'));
  assert.ok(compareCardFormats(a, []).some((d) => d.includes('format count')));
});

function memoryState() {
  let value = {};
  return { read: () => structuredClone(value), write: (next) => { value = structuredClone(next); } };
}

test('sync handler applies settings, records the export hash and answers once per request id', async () => {
  const sent = [];
  const state = memoryState();
  let calls = 0;
  const handler = createSyncHandler({
    syncSettings: async (input) => { calls += 1; return { profileName: 'GSM - Lapis', cardFormats: [], missingDictionaries: [], echo: input.settings_hash }; },
    importDictionaries: async () => ({}),
    readStatus: async () => ({ profileName: 'GSM - Lapis' }),
    send: (message) => sent.push(message),
    state,
    now: () => 1000,
  });
  const message = { type: 'yomitan-sync-settings', request_id: 'r1', deadline: Date.now() + 10000,
    data: { settings: firefoxOptions(), settings_hash: 'abc', export_date: '2026-10-03 10:00:00' } };
  assert.equal(handler.handles(message), true);
  await Promise.all([handler(message), handler(message)]);
  assert.equal(calls, 1);
  assert.equal(sent.length, 2);
  assert.equal(sent[0].type, 'yomitan-sync-result');
  assert.equal(sent[0].success, true);
  assert.equal(sent[0].kind, 'settings');
  assert.equal(sent[0].lastSync.settings.hash, 'abc');
  assert.equal(state.read().settings.exportDate, '2026-10-03 10:00:00');
});

test('sync handler reports failures and expired requests without touching state', async () => {
  const sent = [];
  const state = memoryState();
  const handler = createSyncHandler({
    syncSettings: async () => { throw new Error('Yomitan did not keep the card formats'); },
    importDictionaries: async () => ({}),
    readStatus: async () => ({}),
    send: (message) => sent.push(message),
    state,
  });
  await handler({ type: 'yomitan-sync-settings', request_id: 'r2', deadline: Date.now() + 10000, data: { settings: {}, settings_hash: 'x' } });
  await handler({ type: 'yomitan-sync-settings', request_id: 'r3', deadline: Date.now() - 1, data: {} });
  assert.equal(sent[0].success, false);
  assert.match(sent[0].error, /did not keep/);
  assert.equal(sent[1].success, false);
  assert.match(sent[1].error, /expired/);
  assert.deepEqual(state.read(), {});
  assert.equal(handler.handles({ type: 'anki-setup-yomitan' }), false);
});

test('dictionary import streams progress and records the file fingerprint', async () => {
  const sent = [];
  const state = memoryState();
  const handler = createSyncHandler({
    syncSettings: async () => ({}),
    importDictionaries: async (input, onProgress) => {
      onProgress({ completedRows: 5, totalRows: 10 });
      return { installed: ['JPDBv2'] };
    },
    readStatus: async () => ({}),
    send: (message) => sent.push(message),
    state,
  });
  await handler({ type: 'yomitan-sync-dictionaries', request_id: 'd1', deadline: Date.now() + 10000,
    data: { url: 'http://127.0.0.1:7275/api/yomitan-sync/dictionaries-file', fingerprint: 'f1', export_name: 'yomitan-dictionaries-x.json' } });
  assert.equal(sent[0].type, 'yomitan-sync-progress');
  assert.equal(sent[0].completedRows, 5);
  const result = sent.at(-1);
  assert.equal(result.type, 'yomitan-sync-result');
  assert.equal(result.kind, 'dictionaries');
  assert.equal(result.success, true);
  assert.equal(state.read().dictionaries.hash, 'f1');
});

test('status request returns the overlay report with the stored sync marker', async () => {
  const sent = [];
  const state = memoryState();
  state.write({ settings: { hash: 'abc' } });
  const handler = createSyncHandler({
    syncSettings: async () => ({}),
    importDictionaries: async () => ({}),
    readStatus: async () => ({ profileName: 'GSM - Lapis', cardFormats: [] }),
    send: (message) => sent.push(message),
    state,
  });
  await handler({ type: 'yomitan-sync-status-request', request_id: 's1', deadline: Date.now() + 10000 });
  assert.equal(sent[0].kind, 'status');
  assert.equal(sent[0].profileName, 'GSM - Lapis');
  assert.equal(sent[0].lastSync.settings.hash, 'abc');
});

test('page scripts compile and run in a hidden window that is always destroyed', async () => {
  const vm = require('node:vm');
  const { syncSettings, importDictionaries, readStatus } = require('../yomitan_sync.js');
  const windows = [];
  class FakeWindow {
    constructor() { this.destroyed = false; windows.push(this); this.scripts = [];
      this.webContents = { executeJavaScript: async (script) => { this.scripts.push(script); return script.startsWith('window.__gsm') ? null : { ok: true }; } }; }
    async loadURL(url) { this.url = url; }
    isDestroyed() { return this.destroyed; }
    destroy() { this.destroyed = true; }
  }
  const ext = { id: 'abc' };
  await syncSettings(FakeWindow, ext, { settings: firefoxOptions() }, Date.now() + 10000);
  await importDictionaries(FakeWindow, ext, { url: 'http://127.0.0.1:7275/x' }, () => {});
  await readStatus(FakeWindow, ext);
  assert.equal(windows.length, 3);
  for (const window of windows) {
    assert.equal(window.url, 'chrome-extension://abc/legal.html');
    assert.equal(window.destroyed, true);
    // Top-level await is fine inside the async IIFE; a syntax error would throw here.
    assert.doesNotThrow(() => new vm.Script(window.scripts[0]));
  }
  await assert.rejects(readStatus(FakeWindow, null), /Yomitan as its dictionary/);
});
