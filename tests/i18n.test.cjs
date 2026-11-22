const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const en = require('../i18n/en.json');
const no = require('../i18n/no.json');
const Model = require('../Model.js');
const Schema = require('../Preferences.js');
const kit = require('../kit/node-loader.cjs');
const root = path.join(__dirname, '..');
const read = (...parts) => fs.readFileSync(path.join(root, ...parts), 'utf8');
const tokens = s => [...String(s).matchAll(/%[1-9][0-9]*|\{\w+\}/g)].map(m => m[0]).sort();
const forms = v => (typeof v === 'string' ? [v] : Object.values(v));
// A double-quoted string literal; group 1 is its content.
const STRING = String.raw`"((?:[^"\\]|\\.)*)"`;
const unquote = text => JSON.parse('"' + text + '"');
const literals = (source, before) => [...source.matchAll(new RegExp(before + STRING, 'g'))].map(m => unquote(m[1]));

test('the English and Norwegian catalogs have the same entries, shapes and placeholders', () => {
  // English source keys: plain entries repeat the key, plural entries carry "other".
  for (const [key, value] of Object.entries(en)) {
    if (typeof value === 'string') assert.equal(value, key, `English source key: ${key}`);
    else assert.ok(typeof value.one === 'string' && typeof value.other === 'string', `English plural: ${key}`);
    assert.ok(Object.hasOwn(no, key), `Norwegian entry: ${key}`);
    assert.equal(typeof no[key], typeof value, `same entry shape: ${key}`);
    for (const form of forms(no[key])) assert.deepEqual(tokens(form), tokens(key), `placeholders: ${key}`);
  }
  assert.deepEqual(Object.keys(no).sort(), Object.keys(en).sort());
});

// Each FoamyI18n.t( or FoamyI18n.tn( call in `source` with the double-quoted
// literals inside it: calls span lines, and a ternary passes several keys.
function translationCalls(source) {
  const calls = [];
  for (const match of source.matchAll(/FoamyI18n\.(tn?)\(/g)) {
    const keys = [];
    let depth = 1, quote = null, text = '';
    for (let i = match.index + match[0].length; i < source.length && depth; i++) {
      const ch = source[i];
      if (quote) {
        if (ch === '\\') text += ch + source[++i];
        else if (ch !== quote) text += ch;
        else {
          if (quote === '"') keys.push(unquote(text));
          quote = null;
          text = '';
        }
      } else if (ch === '"' || ch === "'" || ch === '`') quote = ch;
      else if (ch === '(') depth++;
      else if (ch === ')') depth--;
    }
    calls.push({ plural: match[1] === 'tn', keys });
  }
  return calls;
}

test('every text the plugin hands to FoamyI18n has an entry', () => {
  const wanted = []; // [where, key, plural]
  // A call with a variable argument has no literal keys, so only the QML scan as a whole has a minimum.
  for (const file of fs.readdirSync(root).filter(f => f.endsWith('.qml'))) {
    for (const call of translationCalls(read(file))) for (const key of call.keys) wanted.push([file, key, call.plural]);
  }
  assert.ok(wanted.length >= 50, `literal keys found in the QML: ${wanted.length}`);
  // Keys that reach FoamyI18n.t through a variable or a kit component.
  const add = (where, keys, plural = false) => {
    // A source that finds nothing means its scan no longer matches the code (after a kit sync, say).
    assert.ok(keys.length > 0, `no keys found: ${where}`);
    for (const key of keys) wanted.push([where, key, plural]);
  };
  add('Preferences.js dayLabels', Schema.dayLabels);
  add('TrainView.qml detail labels', literals(read('TrainView.qml'), 'label: '));
  add('TrainService.qml fail()', literals(read('TrainService.qml'), String.raw`fail\(`));
  const station = { id: 'NSR:StopPlace:1', name: 'A' };
  for (const route of [{}, { from: station, to: station }]) {
    assert.throws(() => Model.route(route), error => { add('Model.route()', [error.message]); return true; });
  }
  // What Panel.settingsError can hold besides the route errors.
  const Prefs = kit.load('FoamyPrefs');
  add('kit FoamyPrefs', [Prefs.NOT_ALLOWED, Prefs.NO_ENTRY]);
  add('kit FoamyPrefsQueue', literals(read('kit', 'FoamyPrefsQueue.qml'), 'error = ').filter(Boolean));
  add('kit FoamyNative', [kit.load('FoamyNative').UNAVAILABLE_TEXT]);
  // SafeTextField (the station search field) asks the plugin's translator.
  const field = read('kit', 'SafeTextField.qml');
  add('kit SafeTextField menu', literals(field, String.raw`translate\(`));
  add('kit SafeTextField paste', literals(field, '').filter(k => /^(Clipboard|Could not paste)/.test(k)));
  // FoamyI18n.updatedAgo, which TrainView shows.
  const i18n = read('kit', 'FoamyI18n.qml').replace(/^\s*\/\/.*$/gm, '');
  add('kit FoamyI18n.updatedAgo', literals(i18n, String.raw`\bt\(`).filter(k => k.startsWith('Updated ')));
  add('kit FoamyI18n.updatedAgo', literals(i18n, String.raw`\btn\(`).filter(k => k.startsWith('Updated ')), true);
  // The kit components the plugin's QML builds, directly or through another
  // kit component, translate their own default labels and tooltips.
  const kitComponents = new Set(fs.readdirSync(path.join(root, 'kit')).filter(f => f.endsWith('.qml')).map(f => f.slice(0, -4)));
  const kitSource = name => read('kit', name + '.qml').replace(/^\s*\/\/.*$/gm, '');
  const built = source => [...source.matchAll(/\b([A-Z]\w*)\s*\{/g)].map(m => m[1]).filter(name => kitComponents.has(name));
  const pluginQml = fs.readdirSync(root).filter(f => f.endsWith('.qml')).map(f => read(f)).join('\n');
  const used = new Set();
  for (const pending = built(pluginQml); pending.length;) {
    const name = pending.pop();
    if (used.has(name)) continue;
    used.add(name);
    pending.push(...built(kitSource(name)));
  }
  // FoamyInfoNote shows only beside a FoamySettingsSection `info`, which no section sets.
  if (!/\binfo\s*:/.test(pluginQml)) used.delete('FoamyInfoNote');
  const kitKeys = [];
  for (const name of used) for (const call of translationCalls(kitSource(name))) for (const key of call.keys) kitKeys.push([`kit ${name}`, key, call.plural]);
  assert.ok(used.has('FoamyHeader') && kitKeys.length > 0, `kit component texts found: ${kitKeys.length}`);
  wanted.push(...kitKeys);
  const missing = wanted.filter(([, key]) => !Object.hasOwn(en, key)).map(([where, key]) => `${where}: ${key}`);
  assert.deepEqual(missing, [], 'missing catalog keys');
  const notPlural = wanted.filter(([, key, plural]) => plural && typeof en[key] !== 'object').map(([where, key]) => `${where}: ${key}`);
  assert.deepEqual(notPlural, [], 'tn keys need a plural entry');
});

test("the helper's user-facing errors are catalog keys", () => {
  const native = path.join(root, 'native', 'src');
  const helper = fs.readdirSync(native).filter(f => f.endsWith('.rs')).map(f => fs.readFileSync(path.join(native, f), 'utf8')).join('\n');
  const helperKeys = [...helper.matchAll(/TrainError::new\(\s*"[a-z_]+",\s*"([^"]+)",?\s*\)/g)].map(m => m[1]);
  assert.ok(helperKeys.length >= 12, `helper error keys found: ${helperKeys.length}`);
  for (const key of helperKeys) assert.ok(Object.hasOwn(en, key), `helper error key: ${key}`);
});

test("the kit's HTTPS-unsupported text is a catalog key, in its current wording only", () => {
  // tls::UNSUPPORTED (the vendored kit's message) is the error on a CPU without HTTPS support:
  // the catalogs must carry exactly the kit's text, and no other (stale) wording of it.
  const unsupported = read('kit', 'rust', 'foamy-helper', 'src', 'tls.rs').match(/pub const UNSUPPORTED: &str = "((?:[^"\\]|\\.)*)";/);
  assert.ok(unsupported, 'kit tls::UNSUPPORTED');
  assert.ok(Object.hasOwn(en, unsupported[1]), `helper error key (kit tls::UNSUPPORTED): ${unsupported[1]}`);
  for (const key of Object.keys(en).filter(k => k.startsWith("HTTPS isn't supported on this CPU"))) {
    assert.equal(key, unsupported[1], 'HTTPS-unsupported key matches the kit\'s tls::UNSUPPORTED');
  }
});
