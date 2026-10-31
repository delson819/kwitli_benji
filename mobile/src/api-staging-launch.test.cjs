const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const { loadProjectEnv, getEnvFiles } = require("@expo/env");
const path = require("node:path");
const {
  METRO_PORT,
  STAGING_API_URL,
  STAGING_ENV_MARKER,
  STAGING_URL_VARIABLE,
  assertStagingVariablesAreNotInDotenv,
  createStagingEnvironment,
} = require("../scripts/start-staging.cjs");

const mobileRoot = path.resolve(__dirname, "..");
const stagingEnvironment = createStagingEnvironment({ EXPO_PUBLIC_API_URL: "http://127.0.0.1:8000" });
assert.equal(stagingEnvironment.EXPO_PUBLIC_API_URL, "http://127.0.0.1:8000", "the local dotenv key must remain untouched");
assert.equal(stagingEnvironment[STAGING_ENV_MARKER], "staging");
assert.equal(stagingEnvironment[STAGING_URL_VARIABLE], STAGING_API_URL);
assert.equal(METRO_PORT, 8090);
assert.doesNotThrow(assertStagingVariablesAreNotInDotenv);

const expoEnvironment = { NODE_ENV: "development", ...stagingEnvironment };
loadProjectEnv(mobileRoot, { mode: "development", force: true, systemEnv: expoEnvironment });
assert.equal(expoEnvironment.EXPO_PUBLIC_STAGING_API_URL, STAGING_API_URL, "the staging-specific key must survive Expo dotenv loading");
const expoVirtualEnv = {
  ...expoEnvironment,
  EXPO_PUBLIC_API_URL: "http://127.0.0.1:8000", // Expo virtual env overlays dotenv values after process.env
};
const devEnvironment = { NODE_ENV: "development" };
loadProjectEnv(mobileRoot, { mode: "development", force: true, systemEnv: devEnvironment });
assert.equal(devEnvironment.EXPO_PUBLIC_API_URL, "http://127.0.0.1:8000", "plain Expo start must retain the local DEV dotenv URL");

const expoDotenvFiles = getEnvFiles({ mode: "development" });
assert.ok(expoDotenvFiles.includes(".env"));
assert.ok(!expoDotenvFiles.includes(".env.save"), "Expo must ignore .env.save");

(async () => {
  const { resolveConfiguredApiUrl } = await import("./api-url.ts");
  assert.equal(resolveConfiguredApiUrl("ios", true, expoVirtualEnv), STAGING_API_URL);
  assert.equal(resolveConfiguredApiUrl("ios", true, expoEnvironment), STAGING_API_URL);
  assert.equal(resolveConfiguredApiUrl("ios", true, devEnvironment), "http://127.0.0.1:8000");

  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "kwitli-env-guard-"));
  try {
    fs.writeFileSync(path.join(tempRoot, ".env"), "EXPO_PUBLIC_STAGING_API_URL=https://wrong.invalid\n");
    assert.throws(() => assertStagingVariablesAreNotInDotenv(tempRoot), /must not be defined in \.env/);
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }

  console.log("Staging launch: dedicated URL survives Expo virtual dotenv overlay, local DEV URL preserved, conflicts fail closed, .env.save excluded PASS");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
