const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');

function loadMarket(env) {
  const exports = {};
  const source = fs.readFileSync(`${__dirname}/market.ts`, 'utf8');
  const output = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS },
  }).outputText;
  vm.runInNewContext(output, { exports, process: { env } });
  return exports;
}

let market = loadMarket({});
assert.equal(market.ACTIVE_MARKET_CODE, 'SN');
assert.equal(market.ACTIVE_MARKET_TIMEZONE, 'Africa/Dakar');
assert.equal(market.resolveTimezone('America/Toronto', 'Africa/Dakar', 'UTC'), 'America/Toronto');
assert.equal(market.resolveTimezone(undefined, 'Africa/Dakar', 'America/Bogota'), 'Africa/Dakar');
assert.equal(market.resolveTimezone(undefined, 'invalid/zone', 'America/Bogota'), 'America/Bogota');
assert.equal(market.resolveTimezone(undefined, 'invalid/zone', 'also/invalid'), 'UTC');

market = loadMarket({ EXPO_PUBLIC_TIMEZONE_MARKET_CODE: 'CI', EXPO_PUBLIC_MARKET_TIMEZONE: 'UTC' });
assert.equal(market.ACTIVE_MARKET_TIMEZONE, 'Africa/Abidjan');
market = loadMarket({ EXPO_PUBLIC_MARKET_CODE: 'CO', EXPO_PUBLIC_MARKET_TIMEZONE: 'UTC' });
assert.equal(market.ACTIVE_MARKET_TIMEZONE, 'America/Bogota');

console.log('market timezone tests passed');
