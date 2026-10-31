const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const app = JSON.parse(fs.readFileSync("app.json", "utf8")).expo;
const eas = JSON.parse(fs.readFileSync("eas.json", "utf8"));
const profile = eas.build?.["preview-android"];

const { getResolvedLocalesAsync } = require("@expo/config-plugins/build/utils/locales");
const { setLocalesAsync } = require("@expo/config-plugins/build/android/Locales");
const androidXml = require("@expo/config-plugins/build/utils/XML");

assert.ok(profile, "the private Android preview profile must exist");
assert.equal(profile.distribution, "internal");
assert.equal(profile.developmentClient, false, "the installed APK must not depend on Metro");
assert.equal(profile.android?.buildType, "apk");
assert.equal(app.android.package, "app.kwitli.mobile", "the Android application ID must stay stable");
assert.equal(app.android.package, app.ios.bundleIdentifier, "iOS and Android retain the same Kwitli identity");
assert.equal(profile.env.EXPO_PUBLIC_KWITLI_ENV, "staging");
assert.equal(profile.env.EXPO_PUBLIC_STAGING_API_URL, "https://api.kwitli.app");
assert.equal(profile.env.EXPO_PUBLIC_API_URL, "https://api.kwitli.app");
assert.ok(app.android.permissions.includes("android.permission.MODIFY_AUDIO_SETTINGS"),
  "order alert playback may change the audio mode");
assert.ok(!app.android.permissions.includes("android.permission.RECORD_AUDIO"),
  "the MVP plays order alerts but does not record audio");
assert.ok(app.android.blockedPermissions.includes("android.permission.RECORD_AUDIO"),
  "the microphone permission remains blocked from transitive native manifests");
const audioPlugin = app.plugins.find((plugin) => Array.isArray(plugin) && plugin[0] === "expo-audio");
assert.equal(audioPlugin?.[1]?.recordAudioAndroid, false,
  "expo-audio must not inject the microphone permission");

for (const value of Object.values(profile.env)) {
  assert.doesNotMatch(value, /127\.0\.0\.1|localhost|10\.0\.2\.2/);
}
assert.ok(!("production" in eas.build), "this change must not define a store/release profile");

(async () => {
  const androidLocales = await getResolvedLocalesAsync(process.cwd(), app.locales, "android");
  const iosLocales = await getResolvedLocalesAsync(process.cwd(), app.locales, "ios");

  for (const [locale, strings] of Object.entries(androidLocales)) {
    assert.deepEqual(Object.keys(strings).sort(), ["app_name"]);
    assert.equal(strings.app_name, "Kwitli");
    assert.ok(!("CFBundleDisplayName" in strings), `${locale} iOS display name must not leak into Android resources`);
  }
  assert.equal(iosLocales.fr.CFBundleDisplayName, "Kwitli");
  assert.equal(iosLocales["es-CO"].CFBundleDisplayName, "Kwitli");
  assert.ok(iosLocales.fr.NSCameraUsageDescription);
  assert.ok(iosLocales["es-CO"].NSLocationWhenInUseUsageDescription);

  const generatedProject = fs.mkdtempSync(path.join(os.tmpdir(), "kwitli-locales-"));
  try {
    fs.mkdirSync(path.join(generatedProject, "android/app/src/main/res"), { recursive: true });
    const fixtureLocales = {};
    for (const locale of ["fr", "es-CO"]) {
      const fixturePath = `./${locale}.json`;
      fs.writeFileSync(
        path.join(generatedProject, fixturePath),
        fs.readFileSync(app.locales[locale], "utf8"),
      );
      fixtureLocales[locale] = fixturePath;
    }
    const originalWriteXml = androidXml.writeXMLAsync;
    const pendingWrites = [];
    androidXml.writeXMLAsync = (options) => {
      const write = originalWriteXml(options);
      pendingWrites.push(write);
      return write;
    };
    try {
      await setLocalesAsync({ locales: fixtureLocales }, { projectRoot: generatedProject });
      await Promise.all(pendingWrites);
    } finally {
      androidXml.writeXMLAsync = originalWriteXml;
    }
    for (const locale of ["fr", "es-CO"]) {
      const languageTag = locale.replaceAll("-", "+");
      const stringsXml = fs.readFileSync(
        path.join(generatedProject, `android/app/src/main/res/values-b+${languageTag}/strings.xml`),
        "utf8",
      );
      assert.match(stringsXml, /name="app_name"/);
      assert.doesNotMatch(stringsXml, /CFBundleDisplayName|NSCameraUsageDescription|NSLocationWhenInUseUsageDescription|NSPhotoLibraryUsageDescription/);
    }
  } finally {
    fs.rmSync(generatedProject, { recursive: true, force: true });
  }

  const { resolveConfiguredApiUrl } = await import("./api-url.ts");
  const resolvedUrl = resolveConfiguredApiUrl("android", false, {
    ...profile.env,
    EXPO_PUBLIC_API_URL: "http://127.0.0.1:8000",
  });
  assert.equal(resolvedUrl, "https://api.kwitli.app", "staging marker must win over a local dotenv URL");
  console.log("EAS preview profile and generated platform-scoped locale resources: internal APK, stable app ID, staging URL, Android app_name only, iOS metadata retained PASS");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
