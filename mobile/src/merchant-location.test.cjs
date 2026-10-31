const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');

function loadModule(file, exports, requireModule) {
  const source = fs.readFileSync(`${__dirname}/${file}`, 'utf8');
  const output = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS },
  }).outputText;
  vm.runInNewContext(output, { exports, require: requireModule });
}

const locationModule = {};
loadModule('location.ts', locationModule, (path) => {
  if (path === './location') return locationModule;
  throw new Error(`Unexpected import: ${path}`);
});
const merchantModule = {};
loadModule('merchant-location.ts', merchantModule, (path) => {
  if (path === './location') return locationModule;
  throw new Error(`Unexpected import: ${path}`);
});

const { assessMerchantServiceArea, validateMerchantGpsFix } = merchantModule;
const dakar = {
  id: 'sn-dakar', code: 'SN-DKR', label: 'Dakar, Sénégal', country_code: 'SN', country: 'Sénégal',
  city: 'Dakar', latitude: 14.7167, longitude: -17.4677, radius_km: 30,
  timezone: 'Africa/Dakar', active: true,
};
const now = Date.now();
const dakarFix = { latitude: 14.716, longitude: -17.468, accuracy: 20, timestamp: now };
const valid = validateMerchantGpsFix(dakarFix, { now });
assert.equal(valid.error, undefined);
assert.equal(valid.coordinates.latitude, dakarFix.latitude);

const phoneInCanada = { latitude: 45.4042, longitude: -71.8929, accuracy: 20, timestamp: now };
assert.equal(validateMerchantGpsFix(phoneInCanada, { now }).coordinates.latitude, phoneInCanada.latitude,
  'valid phone GPS is captured even when outside the restaurant market; the merchant may replace it manually');
assert.equal(assessMerchantServiceArea(dakarFix, [dakar]).status, 'inside');
assert.equal(assessMerchantServiceArea(dakarFix, [dakar]).areaLabel, dakar.label);
assert.equal(assessMerchantServiceArea(phoneInCanada, [dakar]).status, 'outside');
assert.equal(assessMerchantServiceArea(dakarFix, [{ ...dakar, active: false }]).status, 'unknown');
assert.equal(assessMerchantServiceArea(dakarFix, []).status, 'unknown');

assert.equal(validateMerchantGpsFix({ ...dakarFix, mocked: true }, { now }).error, 'simulated');
assert.equal(validateMerchantGpsFix(dakarFix, { now, simulated: true }).error, 'simulated');
assert.equal(validateMerchantGpsFix({ ...dakarFix, timestamp: now - 3 * 60_000 }, { now }).error, 'stale');
assert.equal(validateMerchantGpsFix({ ...dakarFix, accuracy: null }, { now }).error, 'missing_accuracy');
assert.equal(validateMerchantGpsFix({ ...dakarFix, accuracy: 251 }, { now }).error, 'low_accuracy');
assert.equal(validateMerchantGpsFix({ ...dakarFix, latitude: 91 }, { now }).error, 'invalid_coordinates');

console.log('merchant location tests passed');
