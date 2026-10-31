const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');

const locationModule = {};
const source = fs.readFileSync(`${__dirname}/location.ts`, 'utf8');
const output = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS },
}).outputText;
vm.runInNewContext(output, { exports: locationModule });

const {
  isInsideActiveServiceArea,
  activeServiceAreaLabels,
  clearManualLocationChoice,
  locationHomeMessageKind,
  restoreManualLocationChoice,
  resolveLocation,
  saveManualLocationChoice,
  shouldAcceptSimulatedPosition,
  shouldRefreshLocationAfterResume,
  shouldRequestForegroundPermission,
} = locationModule;
const frenchLocale = JSON.parse(fs.readFileSync(`${__dirname}/../locales/fr.json`, 'utf8'));
assert.equal(
  frenchLocale['location.outsideOneServiceArea'],
  'Kwitli est actuellement disponible à {area}. Vous pouvez explorer les restaurants de cette zone.',
);
assert.match(frenchLocale['location.simulatedOutsideServiceAreas'], /position simulée/);
assert.equal(shouldAcceptSimulatedPosition(true), true);
assert.equal(shouldAcceptSimulatedPosition(false), false,
  'release builds must not use simulator or mock-provider positions');
assert.equal(locationHomeMessageKind('outside_active_areas'), 'outside_service_area');
assert.equal(locationHomeMessageKind('no_active_service_areas'), null,
  'an empty or unavailable service-area list is not a GPS failure');
assert.equal(locationHomeMessageKind('permission_denied'), 'gps_unavailable');
const now = Date.now();
const dakar = {
  id: 'sn-dakar', code: 'SN-DKR', label: 'Dakar, Sénégal', country_code: 'SN', country: 'Sénégal',
  city: 'Dakar', latitude: 14.7167, longitude: -17.4677, radius_km: 30,
  timezone: 'Africa/Dakar', active: true,
};
const sherbrooke = {
  id: 'ca-sherbrooke-dev', code: 'CA-SHERBROOKE-DEV', label: 'Sherbrooke, Canada (DEV)', country_code: 'CA', country: 'Canada',
  city: 'Sherbrooke', latitude: 45.4042, longitude: -71.8929, radius_km: 30,
  timezone: 'America/Toronto', active: true,
};
const serviceAreas = [dakar, sherbrooke];
assert.equal(JSON.stringify(activeServiceAreaLabels([dakar])), JSON.stringify(['Dakar']));
assert.equal(JSON.stringify(activeServiceAreaLabels([dakar, { ...dakar, id: 'other' }])), JSON.stringify(['Dakar']));
assert.equal(JSON.stringify(activeServiceAreaLabels([{ ...dakar, active: false }])), JSON.stringify([]));
const sherbrookeFix = {
  latitude: 45.405, longitude: -71.893, accuracy: 20, timestamp: now,
};

assert(isInsideActiveServiceArea(sherbrookeFix, serviceAreas));
const validFix = resolveLocation({ gpsFix: sherbrookeFix, serviceAreas, now });
assert.equal(validFix.source, 'gps');
assert.deepEqual(
  { latitude: validFix.choice.latitude, longitude: validFix.choice.longitude },
  { latitude: sherbrookeFix.latitude, longitude: sherbrookeFix.longitude },
);
assert.equal(validFix.accuracyMeters, 20);
assert.deepEqual(
  { latitude: validFix.detectedPosition.latitude, longitude: validFix.detectedPosition.longitude },
  { latitude: sherbrookeFix.latitude, longitude: sherbrookeFix.longitude },
);
assert.equal(validFix.detectedPosition.source, 'gps');
assert.equal(validFix.detectedPosition.accuracyMeters, 20);
assert.equal(validFix.detectedPosition.timestamp, now);

for (const platform of ['ios', 'android']) {
  const resolution = resolveLocation({ gpsFix: sherbrookeFix, serviceAreas, now });
  assert.equal(resolution.source, 'gps', `${platform} uses the same resolver`);
  assert.equal(resolution.choice.latitude, sherbrookeFix.latitude);
  assert.equal(resolution.choice.longitude, sherbrookeFix.longitude);
}
assert.equal(resolveLocation({ gpsFix: sherbrookeFix, serviceAreas, now, isSimulated: true }).source, 'simulated');

assert.equal(shouldRequestForegroundPermission({ granted: true, canAskAgain: true }), false);
assert.equal(shouldRequestForegroundPermission({ granted: false, canAskAgain: true }), true);
assert.equal(shouldRequestForegroundPermission({ granted: false, canAskAgain: false }), false);
assert.equal(shouldRefreshLocationAfterResume(true, 'gps'), true);
assert.equal(shouldRefreshLocationAfterResume(true, 'simulated'), true);
assert.equal(shouldRefreshLocationAfterResume(true, 'manual'), false);
assert.equal(shouldRefreshLocationAfterResume(false, 'gps'), false);

const cupertinoFix = {
  latitude: 37.323, longitude: -122.032, accuracy: 30, timestamp: now,
};
const outsideResolution = resolveLocation({ gpsFix: cupertinoFix, serviceAreas, now });
assert.equal(outsideResolution.choice, null);
assert.equal(outsideResolution.reason, 'outside_active_areas');
assert.equal(outsideResolution.source, null, 'an out-of-area fix cannot become a search zone');
assert.equal(outsideResolution.detectedPosition.latitude, cupertinoFix.latitude);
assert.equal(outsideResolution.detectedPosition.longitude, cupertinoFix.longitude);
assert.equal(outsideResolution.detectedPosition.source, 'gps');
assert.equal(outsideResolution.detectedPosition.accuracyMeters, cupertinoFix.accuracy);
assert.equal(outsideResolution.detectedPosition.timestamp, cupertinoFix.timestamp,
  'a valid real GPS fix is preserved separately from service coverage');
const simulatedOutsideResolution = resolveLocation({
  gpsFix: cupertinoFix, serviceAreas, now, isSimulated: true,
});
assert.equal(simulatedOutsideResolution.detectedPosition.source, 'simulated');
assert.equal(simulatedOutsideResolution.choice, null);
const movedOutsideFix = { ...cupertinoFix, latitude: 37.324, timestamp: now + 1_000 };
const movedOutsideResolution = resolveLocation({ gpsFix: movedOutsideFix, serviceAreas: [dakar], now });
assert.equal(movedOutsideResolution.choice, null, 'moving outside the active market stops nearby discovery');
assert.equal(movedOutsideResolution.detectedPosition.latitude, movedOutsideFix.latitude,
  'a fresh moved-to position replaces the previous GPS position');
const noActiveAreasResolution = resolveLocation({ gpsFix: sherbrookeFix, serviceAreas: [], now });
assert.equal(noActiveAreasResolution.reason, 'no_active_service_areas');
assert.equal(noActiveAreasResolution.choice, null, 'an empty/failed service-area response cannot enable arbitrary discovery');
assert.equal(noActiveAreasResolution.detectedPosition.latitude, sherbrookeFix.latitude,
  'GPS is still detected independently when no market is active');
assert.equal(resolveLocation({ manualChoice: dakar, serviceAreas: [], now }).choice, null,
  'a saved city is ignored until the API confirms it is active');

const deniedPermissionResolution = resolveLocation({ serviceAreas, now });
assert.equal(deniedPermissionResolution.choice, null);
assert.equal(deniedPermissionResolution.reason, 'gps_unavailable');
const refusedPermission = resolveLocation({ unavailableReason: 'permission_denied', serviceAreas, now });
assert.equal(refusedPermission.reason, 'permission_denied');
assert.equal(refusedPermission.detectedPosition, null, 'refused permission never invents a device position');
assert.equal(resolveLocation({ unavailableReason: 'permission_blocked', serviceAreas, now }).reason, 'permission_blocked');
assert.equal(resolveLocation({ unavailableReason: 'services_disabled', serviceAreas, now }).reason, 'services_disabled');
assert.equal(resolveLocation({ unavailableReason: 'gps_timeout', serviceAreas, now }).reason, 'gps_timeout');
assert.equal(resolveLocation({ unavailableReason: 'gps_error', serviceAreas, now }).reason, 'gps_error');

assert.equal(resolveLocation({
  gpsFix: { ...sherbrookeFix, accuracy: 251 }, serviceAreas, now,
}).reason, 'low_accuracy');
assert.equal(resolveLocation({
  gpsFix: { ...sherbrookeFix, accuracy: null }, serviceAreas, now,
}).reason, 'missing_accuracy');
assert.equal(resolveLocation({
  gpsFix: { ...sherbrookeFix, timestamp: now - 10 * 60_000 }, serviceAreas, now,
}).reason, 'stale_fix');
assert.equal(resolveLocation({
  gpsFix: { ...sherbrookeFix, timestamp: now + 31_000 }, serviceAreas, now,
}).reason, 'stale_fix');
assert.equal(resolveLocation({
  gpsFix: { latitude: 999, longitude: -71, accuracy: 20, timestamp: now }, serviceAreas, now,
}).reason, 'invalid_coordinates');

const manualResolution = resolveLocation({
  manualChoice: sherbrooke,
  gpsFix: cupertinoFix,
  serviceAreas,
  now,
});
assert.equal(manualResolution.source, 'manual');
assert.equal(manualResolution.choice.id, sherbrooke.id);
assert.equal(manualResolution.choice.latitude, sherbrooke.latitude);
assert.equal(resolveLocation({
  manualChoice: { ...sherbrooke, id: 'inactive-area' }, serviceAreas, now,
}).choice, null);

const unavailableDev = resolveLocation({ serviceAreas: [], unavailableReason: 'gps_error', now });
assert.equal(unavailableDev.choice, null, 'DEV must not invent a default city when GPS is unavailable');
assert.equal(unavailableDev.source, null);
assert.equal(unavailableDev.reason, 'gps_error');

const productionAreas = [dakar];
assert.equal(resolveLocation({ gpsFix: sherbrookeFix, serviceAreas: productionAreas, now }).choice, null);
const dakarGps = resolveLocation({ gpsFix: {
  latitude: 14.716, longitude: -17.468, accuracy: 25, timestamp: now,
}, serviceAreas: productionAreas, now });
assert.equal(dakarGps.source, 'gps', 'GPS inside the Dakar MVP area remains eligible');
assert.equal(dakarGps.choice.latitude, 14.716, 'in-area discovery uses the actual GPS coordinates');
const manualDakar = resolveLocation({
  manualChoice: dakar,
  gpsFix: cupertinoFix,
  serviceAreas: productionAreas,
  now,
});
assert.equal(manualDakar.source, 'manual');
assert.equal(manualDakar.choice.id, dakar.id);
assert.equal(manualDakar.detectedPosition, null, 'manual Dakar selection is not represented as device GPS');
assert.equal(manualDakar.choice.latitude, dakar.latitude, 'manual browsing uses the service-area center');

// The same resolver is used by pickup synchronization: only an eligible real GPS result
// has source "gps"; manual zones, simulated positions and out-of-area GPS cannot pass its guard.
assert.notEqual(manualDakar.source, 'gps');
assert.notEqual(simulatedOutsideResolution.source, 'gps');
assert.notEqual(outsideResolution.source, 'gps');

async function testManualPreferencePersistence() {
  const values = new Map();
  const storage = {
    async getItem(key) { return values.get(key) ?? null; },
    async setItem(key, value) { await new Promise((resolve) => setTimeout(resolve, 5)); values.set(key, value); },
    async removeItem(key) { values.delete(key); },
  };
  await saveManualLocationChoice(storage, dakar);
  const restored = await restoreManualLocationChoice(storage, productionAreas);
  assert.equal(restored.hasStoredChoice, true);
  assert.equal(restored.choice.id, dakar.id);
  assert.equal(restored.choice.latitude, dakar.latitude,
    'restoration uses canonical coordinates returned by the backend');

  await Promise.all([
    saveManualLocationChoice(storage, dakar),
    clearManualLocationChoice(storage),
  ]);
  assert.equal((await restoreManualLocationChoice(storage, productionAreas)).hasStoredChoice, false,
    'explicit return to GPS queued after manual selection clears it reliably');

  await clearManualLocationChoice(storage);
  await saveManualLocationChoice(storage, dakar);
  assert.equal((await restoreManualLocationChoice(storage, productionAreas)).choice.id, dakar.id,
    'a later manual choice remains selected after a queued GPS reset');

  const inactive = await restoreManualLocationChoice(storage, [
    { ...dakar, active: false },
  ]);
  assert.equal(inactive.hasStoredChoice, true);
  assert.equal(inactive.choice, null, 'inactive backend zones are not restored as selectable');
  await assert.rejects(
    saveManualLocationChoice({ setItem: async () => { throw new Error('storage unavailable'); } }, dakar),
  );
}

testManualPreferencePersistence().then(() => {
  console.log('location tests passed');
}).catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
