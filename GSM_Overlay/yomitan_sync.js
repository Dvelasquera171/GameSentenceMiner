// GSM integration only: keep the overlay's Yomitan in step with the user's Firefox Yomitan export.
// Firefox is the source of truth for cards, dictionaries and lookup behaviour; the overlay keeps its
// own window, scanning and input settings. Uses Yomitan's API from a hidden extension page.

// Functions passed to the page with toString() must stay self-contained.
function extractExportOptions(data) {
  const options = data && typeof data === 'object' && !Array.isArray(data)
    ? (data.options && typeof data.options === 'object' ? data.options : data)
    : null;
  if (!options || !Array.isArray(options.profiles) || options.profiles.length === 0) {
    throw new Error('This file is not a Yomitan settings export (Settings → Backup → Export Settings).');
  }
  return options;
}

function mergeSyncedOptions(overlayOptions, firefoxOptions, installedTitles) {
  // Sections that decide what a card contains and what a lookup finds.
  const SYNCED_SECTIONS = ['dictionaries', 'anki', 'translation', 'parsing', 'audio', 'sentenceParsing'];
  // general.* keys that change card content; the rest of general is popup/window behaviour.
  const CARD_GENERAL_KEYS = [
    'language', 'resultOutputMode', 'glossaryLayoutMode', 'compactTags', 'mainDictionary',
    'sortFrequencyDictionary', 'sortFrequencyDictionaryOrder', 'averageFrequency',
  ];
  const isLocalhostUrl = (value) => {
    try {
      const { hostname } = new URL(value);
      return ['localhost', '127.0.0.1', '[::1]', '::1'].includes(hostname);
    } catch (_) {
      return false;
    }
  };
  const pick = (options) => {
    const index = Number.isInteger(options?.profileCurrent) ? options.profileCurrent : 0;
    return options?.profiles?.[Math.min(Math.max(index, 0), options.profiles.length - 1)];
  };

  const next = structuredClone(overlayOptions);
  const target = pick(next);
  if (!target?.options || typeof target.options !== 'object') {
    throw new Error('The overlay Yomitan settings are not ready. Open its settings once and retry.');
  }
  const source = pick(firefoxOptions);
  if (!source?.options || typeof source.options !== 'object') {
    throw new Error('The Firefox export has no profile to sync from.');
  }

  const into = target.options;
  const from = structuredClone(source.options);
  const keptServer = into.anki?.server;
  for (const section of SYNCED_SECTIONS) {
    if (section in from) into[section] = from[section];
  }
  if (from.general && typeof from.general === 'object') {
    into.general = into.general && typeof into.general === 'object' ? into.general : {};
    for (const key of CARD_GENERAL_KEYS) {
      if (key in from.general) into.general[key] = from.general[key];
    }
  }
  // Same guard as Yomitan's own settings import.
  if (into.anki && typeof into.anki.server === 'string' && into.anki.server && !isLocalhostUrl(into.anki.server)) {
    into.anki.server = typeof keptServer === 'string' && keptServer ? keptServer : 'http://127.0.0.1:8765';
  }

  let missingDictionaries = [];
  if (Array.isArray(installedTitles) && Array.isArray(into.dictionaries)) {
    const installed = new Set(installedTitles);
    const ordered = into.dictionaries.filter((entry) => installed.has(entry?.name));
    missingDictionaries = into.dictionaries.filter((entry) => !installed.has(entry?.name)).map((entry) => entry?.name);
    const listed = new Set(ordered.map((entry) => entry.name));
    // Dictionaries only the overlay has (GSM's character dictionary) keep their overlay entry.
    const previousProfile = pick(overlayOptions);
    const previous = Array.isArray(previousProfile?.options?.dictionaries) ? previousProfile.options.dictionaries : [];
    for (const entry of previous) {
      if (entry && installed.has(entry.name) && !listed.has(entry.name)) {
        ordered.push(structuredClone(entry));
        listed.add(entry.name);
      }
    }
    for (const title of installedTitles) {
      if (!listed.has(title)) {
        ordered.push({
          name: title, enabled: false, allowSecondarySearches: false, definitionsCollapsible: 'not-collapsible',
          partsOfSpeechFilter: true, useDeinflections: true, styles: '',
        });
        listed.add(title);
      }
    }
    into.dictionaries = ordered;
  }

  return {
    options: next,
    profileName: target.name,
    sourceProfileName: source.name,
    missingDictionaries,
  };
}

function normalizeCardFormats(anki) {
  const formats = Array.isArray(anki?.cardFormats) ? anki.cardFormats : [];
  return formats.map((format) => ({
    name: String(format?.name ?? ''),
    type: String(format?.type ?? ''),
    deck: String(format?.deck ?? ''),
    model: String(format?.model ?? ''),
    fields: Object.fromEntries(Object.entries(format?.fields && typeof format.fields === 'object' ? format.fields : {})
      .map(([name, field]) => [name, {
        value: String(field?.value ?? ''),
        overwriteMode: String(field?.overwriteMode ?? ''),
      }])),
  }));
}

function compareCardFormats(expected, actual) {
  const diffs = [];
  if (expected.length !== actual.length) {
    diffs.push(`card format count: Firefox ${expected.length}, overlay ${actual.length}`);
  }
  for (let i = 0; i < Math.min(expected.length, actual.length); i++) {
    const a = expected[i];
    const b = actual[i];
    const label = `card format ${i + 1} (${a.name || a.type})`;
    for (const key of ['name', 'type', 'deck', 'model']) {
      if (a[key] !== b[key]) diffs.push(`${label} ${key}: Firefox "${a[key]}", overlay "${b[key]}"`);
    }
    for (const [field, value] of Object.entries(a.fields)) {
      const other = b.fields[field];
      if (!other) {
        diffs.push(`${label} field ${field}: missing in the overlay`);
        continue;
      }
      for (const key of ['value', 'overwriteMode']) {
        if (value[key] !== other[key]) {
          diffs.push(`${label} field ${field} ${key}: Firefox "${value[key]}", overlay "${other[key]}"`);
        }
      }
    }
    for (const field of Object.keys(b.fields)) {
      if (!(field in a.fields)) diffs.push(`${label} field ${field}: only in the overlay`);
    }
  }
  return diffs;
}

async function runInYomitanPage(BrowserWindow, extension, script, { timeoutMs, timeoutMessage, onPoll, pollMs = 2000 }) {
  if (!extension?.id) {
    throw new Error('Start the GSM overlay with Yomitan as its dictionary, then retry.');
  }
  // legal.html is an extension page without settings controllers, so nothing else edits options meanwhile.
  const window = new BrowserWindow({
    show: false,
    webPreferences: { nodeIntegration: false, contextIsolation: true },
  });
  let timer;
  let poller;
  try {
    return await Promise.race([
      (async () => {
        await window.loadURL(`chrome-extension://${extension.id}/legal.html`);
        if (onPoll) {
          poller = setInterval(() => {
            window.webContents.executeJavaScript('window.__gsmYomitanSyncProgress || null')
              .then((value) => { if (value) onPoll(value); })
              .catch(() => {});
          }, pollMs);
        }
        return await window.webContents.executeJavaScript(script);
      })(),
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error(timeoutMessage)), timeoutMs);
      }),
    ]);
  } finally {
    clearTimeout(timer);
    clearInterval(poller);
    if (!window.isDestroyed()) window.destroy();
  }
}

const PAGE_PRELUDE = `
  const {API} = await import('./js/comm/api.js');
  const {WebExtension} = await import('./js/extension/web-extension.js');
  const api = new API(new WebExtension());
  const extractExportOptions = (${extractExportOptions.toString()});
  const mergeSyncedOptions = (${mergeSyncedOptions.toString()});
  const normalizeCardFormats = (${normalizeCardFormats.toString()});
  const compareCardFormats = (${compareCardFormats.toString()});
  const currentProfile = (options) => options.profiles[Math.min(Math.max(options.profileCurrent | 0, 0), options.profiles.length - 1)];
  const report = async () => {
    const saved = await api.optionsGetFull();
    const profile = currentProfile(saved);
    const installed = (await api.getDictionaryInfo()).map((d) => d.title);
    return {
      profileName: profile.name,
      ankiEnabled: Boolean(profile.options.anki?.enable),
      cardFormats: normalizeCardFormats(profile.options.anki),
      dictionaries: (profile.options.dictionaries || []).map((d) => ({name: d.name, enabled: Boolean(d.enabled)})),
      installed,
    };
  };
`;

async function syncSettings(BrowserWindow, extension, input, deadline) {
  const remaining = Math.min(60000, deadline - Date.now());
  if (remaining <= 0) throw new Error('Sync request expired. Retry from GSM.');
  return await runInYomitanPage(BrowserWindow, extension, `(async () => {
    ${PAGE_PRELUDE}
    const {OptionsUtil} = await import('./js/data/options-util.js');
    const input = ${JSON.stringify(input)};
    const optionsUtil = new OptionsUtil();
    await optionsUtil.prepare();
    // Same upgrade step as Yomitan's own settings import.
    const source = await optionsUtil.update(structuredClone(extractExportOptions(input.settings)));
    const current = await api.optionsGetFull();
    const installed = (await api.getDictionaryInfo()).map((d) => d.title);
    const result = mergeSyncedOptions(current, source, installed);
    if (Date.now() >= ${Number(deadline)}) throw new Error('Sync request expired. Retry from GSM.');
    await api.setAllSettings(result.options, 'gsm-yomitan-sync');
    const after = await report();
    const diffs = compareCardFormats(normalizeCardFormats(currentProfile(source).options.anki), after.cardFormats);
    if (diffs.length > 0) {
      throw new Error('Yomitan did not keep the Firefox card formats: ' + diffs.slice(0, 5).join('; '));
    }
    return {...after, sourceProfileName: result.sourceProfileName, missingDictionaries: result.missingDictionaries};
  })()`, { timeoutMs: remaining, timeoutMessage: 'Yomitan settings sync timed out. Retry from GSM.' });
}

async function importDictionaries(BrowserWindow, extension, input, onProgress) {
  return await runInYomitanPage(BrowserWindow, extension, `(async () => {
    ${PAGE_PRELUDE}
    const {Dexie} = await import('./lib/dexie.js');
    const input = ${JSON.stringify(input)};
    window.__gsmYomitanSyncProgress = {stage: 'download', completedRows: 0, totalRows: 0};
    const response = await fetch(input.url, {cache: 'no-store'});
    if (!response.ok) throw new Error('GSM could not serve the dictionary export (HTTP ' + response.status + ').');
    const blob = await response.blob();
    if (input.size && blob.size !== input.size) throw new Error('The dictionary export download was incomplete. Retry.');
    const head = await blob.slice(0, 512).text();
    if (!head.includes('"formatName"') || !head.toLowerCase().includes('dexie')) {
      throw new Error('This file is not a Yomitan dictionary collection export (Settings → Backup → Export Dictionary Collection).');
    }
    window.__gsmYomitanSyncProgress = {stage: 'import', completedRows: 0, totalRows: 0};
    // Same steps as Yomitan's "Import Dictionary Collection": replace the whole dictionary database.
    await api.purgeDatabase();
    await Dexie.import(blob, {progressCallback: ({totalRows, completedRows}) => {
      window.__gsmYomitanSyncProgress = {stage: 'import', totalRows, completedRows};
      return true;
    }});
    await api.triggerDatabaseUpdated('dictionary', 'import');
    return await report();
  })()`, {
    timeoutMs: 2 * 60 * 60 * 1000,
    timeoutMessage: 'Dictionary import took longer than two hours. Restart the overlay and retry.',
    onPoll: onProgress,
  });
}

async function readStatus(BrowserWindow, extension) {
  return await runInYomitanPage(BrowserWindow, extension, `(async () => {
    ${PAGE_PRELUDE}
    return await report();
  })()`, { timeoutMs: 20000, timeoutMessage: 'Reading the overlay Yomitan settings timed out.' });
}

function createFileState(fs, filePath) {
  return {
    read: () => {
      try {
        const value = JSON.parse(fs.readFileSync(filePath, 'utf-8'));
        return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
      } catch (_) {
        return {};
      }
    },
    write: (value) => fs.writeFileSync(filePath, JSON.stringify(value, null, 2)),
  };
}

const MESSAGE_KINDS = {
  'yomitan-sync-settings': 'settings',
  'yomitan-sync-dictionaries': 'dictionaries',
  'yomitan-sync-status-request': 'status',
};

function createSyncHandler({ syncSettings: applySettings, importDictionaries: importAll, readStatus: status, send, state, now = Date.now }) {
  // The overlay has two connections to the same backend; share duplicate requests and run one job at a time.
  const requests = new Map();
  let queue = Promise.resolve();
  const readState = () => {
    try { return state.read() || {}; } catch (_) { return {}; }
  };
  const handler = async (message) => {
    const kind = MESSAGE_KINDS[message?.type];
    if (!kind || typeof message.request_id !== 'string') return;
    const id = message.request_id;
    if (!requests.has(id)) {
      const operation = queue.then(async () => {
        try {
          if (!Number.isFinite(message.deadline) || message.deadline <= Date.now()) {
            throw new Error('Sync request expired. Retry from GSM.');
          }
          const input = message.data && typeof message.data === 'object' ? message.data : {};
          let result;
          if (kind === 'settings') {
            result = await applySettings(input, message.deadline);
            const next = readState();
            next.settings = {
              hash: String(input.settings_hash || ''),
              exportDate: String(input.export_date || ''),
              exportName: String(input.export_name || ''),
              appliedAt: now(),
            };
            state.write(next);
          } else if (kind === 'dictionaries') {
            result = await importAll(input, (progress) => send({ type: 'yomitan-sync-progress', request_id: id, kind, ...progress }));
            const next = readState();
            next.dictionaries = {
              hash: String(input.fingerprint || ''),
              exportName: String(input.export_name || ''),
              importedAt: now(),
            };
            state.write(next);
          } else {
            result = await status();
          }
          return { ...result, type: 'yomitan-sync-result', request_id: id, kind, success: true, lastSync: readState() };
        } catch (error) {
          return {
            type: 'yomitan-sync-result', request_id: id, kind, success: false,
            error: error?.message || String(error), lastSync: readState(),
          };
        }
      });
      queue = operation.catch(() => {});
      requests.set(id, operation);
      if (requests.size > 32) requests.delete(requests.keys().next().value);
    }
    send(await requests.get(id));
  };
  handler.handles = (message) => Boolean(MESSAGE_KINDS[message?.type]);
  return handler;
}

module.exports = {
  extractExportOptions,
  mergeSyncedOptions,
  normalizeCardFormats,
  compareCardFormats,
  syncSettings,
  importDictionaries,
  readStatus,
  createFileState,
  createSyncHandler,
};
