const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const en = require('../i18n/en.json');
const no = require('../i18n/no.json');
const manifest = require('../manifest.json');
const root = path.join(__dirname, '..');
const tokens = s => [...String(s).matchAll(/%[1-9][0-9]*|\{\w+\}/g)].map(m => m[0]).sort();
const forms = v => (typeof v === 'string' ? [v] : Object.values(v));

// English source keys: plain entries repeat the key, plural entries carry "other".
for (const [key, value] of Object.entries(en)) {
  if (typeof value === 'string') assert.equal(value, key, `English source key: ${key}`);
  else assert.ok(typeof value.one === 'string' && typeof value.other === 'string', `English plural: ${key}`);
  assert.ok(Object.hasOwn(no, key), `Norwegian entry: ${key}`);
  assert.equal(typeof no[key], typeof value, `same entry shape: ${key}`);
  for (const form of forms(no[key])) assert.deepEqual(tokens(form), tokens(key), `placeholders: ${key}`);
}
assert.deepEqual(Object.keys(no).sort(), Object.keys(en).sort());

// Every literal the plugin passes to FoamyI18n.t/tn has an English entry; tn keys are plural entries.
const sources = fs.readdirSync(root).filter(f => f.endsWith('.qml')).map(f => fs.readFileSync(path.join(root, f), 'utf8'));
for (const source of sources) {
  for (const [, fn, key] of source.matchAll(/FoamyI18n\.(tn?)\("((?:[^"\\]|\\.)*)"/g)) {
    assert.ok(Object.hasOwn(en, key), `missing catalog key: ${key}`);
    if (fn === 'tn') assert.equal(typeof en[key], 'object', `tn key needs a plural entry: ${key}`);
  }
}
// The helper's user-facing errors are catalog keys too.
const native = path.join(root, 'native', 'src');
const helper = fs.readdirSync(native).filter(f => f.endsWith('.rs')).map(f => fs.readFileSync(path.join(native, f), 'utf8')).join('\n');
const helperKeys = [...helper.matchAll(/TrainError::new\(\s*"[a-z_]+",\s*"([^"]+)",?\s*\)/g)].map(m => m[1]);
assert.ok(helperKeys.length >= 12, `helper error keys found: ${helperKeys.length}`);
for (const key of helperKeys) assert.ok(Object.hasOwn(en, key), `helper error key: ${key}`);
// tls::UNSUPPORTED (the vendored kit's message) is the error on a CPU without HTTPS support.
if (/tls::UNSUPPORTED/.test(helper)) {
  const tls = fs.readFileSync(path.join(root, 'kit', 'rust', 'foamy-helper', 'src', 'tls.rs'), 'utf8');
  const unsupported = tls.match(/pub const UNSUPPORTED: &str = "((?:[^"\\]|\\.)*)";/);
  assert.ok(unsupported, 'kit tls::UNSUPPORTED');
  assert.ok(Object.hasOwn(en, unsupported[1]), `helper error key: ${unsupported[1]}`);
}

assert.equal(manifest.barWidget?.defaults?.language, undefined);
assert.equal((manifest.barWidget?.schema || []).some(f => f.key === 'language'), false);
