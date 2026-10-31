const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const ts = require("typescript");

function loadApi({ development, fetchImpl, messages }) {
  const exports = {};
  const source = fs.readFileSync(`${__dirname}/services/api.ts`, "utf8");
  const output = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const mockedRequire = (path) => {
    if (path === "../config") return { API_URL: "https://api.kwitli.app", isApiConfigured: () => true };
    if (path === "../discovery") return { buildDiscoverPath: () => "/api/v1/discover" };
    throw new Error(`Unexpected import ${path}`);
  };
  vm.runInNewContext(output, {
    exports,
    require: mockedRequire,
    fetch: fetchImpl,
    __DEV__: development,
    console: { info: (message) => messages.push(String(message)), warn: (message) => messages.push(String(message)) },
  });
  return exports;
}

async function main() {
  const messages = [];
  const email = "private@example.invalid";
  const password = "fake-private-password";
  const jwt = "fake-private-jwt";
  const privateResponse = "private-response-detail";
  const api = loadApi({
    development: true,
    messages,
    fetchImpl: async (url) => ({
      ok: true,
      status: url.endsWith("/me") ? 200 : url.endsWith("/register") ? 201 : 200,
      text: async () => JSON.stringify(url.endsWith("/me")
        ? { user: { email }, cook_profile: null }
        : { access_token: jwt, token_type: "bearer" }),
    }),
  });

  await api.login({ email, password });
  assert.equal(messages[0], "[API DEBUG] POST /api/v1/auth/login -> SEND stage=login");
  assert.equal(messages[1], "[API DEBUG] POST /api/v1/auth/login -> HTTP 200 stage=login");
  api.logAuthDiagnostic("TOKEN_SAVE_START", "login");
  api.logAuthDiagnostic("TOKEN_SAVED", "login");
  api.setAccessToken(jwt);
  await api.getMe("hydration_me");
  api.logAuthDiagnostic("PROFILE_LOADED", "login");
  assert.deepEqual(messages.slice(2), [
    "[API DEBUG] AUTH TOKEN_SAVE_START stage=login",
    "[API DEBUG] AUTH TOKEN_SAVED stage=login",
    "[API DEBUG] GET /api/v1/me -> SEND stage=hydration_me",
    "[API DEBUG] GET /api/v1/me -> HTTP 200 stage=hydration_me",
    "[API DEBUG] AUTH PROFILE_LOADED stage=login",
  ]);

  const failedMessages = [];
  const failedApi = loadApi({
    development: true,
    messages: failedMessages,
    fetchImpl: async () => { throw new TypeError(privateResponse); },
  });
  await assert.rejects(failedApi.register({ email, password, first_name: "Test" }), (error) => error.status === 0);
  assert.deepEqual(failedMessages, [
    "[API DEBUG] POST /api/v1/auth/register -> SEND stage=register",
    "[API DEBUG] POST /api/v1/auth/register -> NETWORK_ERROR TypeError stage=register",
  ]);

  const httpMessages = [];
  const httpApi = loadApi({
    development: true,
    messages: httpMessages,
    fetchImpl: async () => ({ ok: false, status: 401, text: async () => JSON.stringify({ detail: privateResponse }) }),
  });
  await assert.rejects(httpApi.login({ email, password }), (error) => error.status === 401);
  assert.deepEqual(httpMessages, [
    "[API DEBUG] POST /api/v1/auth/login -> SEND stage=login",
    "[API DEBUG] POST /api/v1/auth/login -> HTTP 401 stage=login",
  ]);

  const healthMessages = [];
  const healthCalls = [];
  const healthApi = loadApi({
    development: true,
    messages: healthMessages,
    fetchImpl: async (url, options) => {
      healthCalls.push({ url, options });
      return { ok: true, status: 200, text: async () => JSON.stringify({ status: "ok", environment: "staging" }) };
    },
  });
  const statusCallbacks = [];
  await healthApi.getApiHealth((status) => statusCallbacks.push(status));
  assert.equal(healthCalls.length, 1, "health probe must make exactly one request");
  assert.equal(healthCalls[0].url, "https://api.kwitli.app/api/v1/health");
  assert.equal(healthCalls[0].options.method, "GET");
  assert.equal(healthCalls[0].options.body, undefined);
  assert.deepEqual(statusCallbacks, [200]);
  assert.deepEqual(healthMessages, [
    "[API DEBUG] GET https://api.kwitli.app/api/v1/health -> SEND stage=health_probe",
    "[API DEBUG] GET https://api.kwitli.app/api/v1/health -> HTTP 200 stage=health_probe",
  ]);

  const healthFailureMessages = [];
  const healthFailureApi = loadApi({
    development: true,
    messages: healthFailureMessages,
    fetchImpl: async () => { throw new TypeError(privateResponse); },
  });
  await assert.rejects(healthFailureApi.getApiHealth(), (error) => error.status === 0);
  assert.deepEqual(healthFailureMessages, [
    "[API DEBUG] GET https://api.kwitli.app/api/v1/health -> SEND stage=health_probe",
    "[API DEBUG] GET https://api.kwitli.app/api/v1/health -> NETWORK_ERROR TypeError stage=health_probe",
  ]);

  const productionMessages = [];
  const productionApi = loadApi({
    development: false,
    messages: productionMessages,
    fetchImpl: async () => ({ ok: true, status: 200, text: async () => JSON.stringify({ access_token: jwt }) }),
  });
  await productionApi.login({ email, password });
  productionApi.logAuthDiagnostic("TOKEN_SAVED", "login");
  await productionApi.getApiHealth();
  assert.deepEqual(productionMessages, [], "Production mode must never emit API DEBUG diagnostics");

  const allLogs = [...messages, ...failedMessages, ...httpMessages, ...healthMessages, ...healthFailureMessages, ...productionMessages].join("\n");
  for (const forbidden of [email, password, jwt, privateResponse, "Authorization", "Bearer"]) {
    assert.ok(!allLogs.includes(forbidden), `diagnostic must not contain ${forbidden}`);
  }

  const appSource = fs.readFileSync(`${__dirname}/../App.tsx`, "utf8");
  const authStart = appSource.indexOf("async function authenticate() {");
  const authEnd = appSource.indexOf("async function submitPasswordResetRequest()", authStart);
  const authBody = appSource.slice(authStart, authEnd);
  assert.ok(authBody.indexOf('logAuthDiagnostic("TOKEN_SAVE_START"') < authBody.indexOf("saveAccessToken(token.access_token)"));
  assert.ok(authBody.indexOf("saveAccessToken(token.access_token)") < authBody.indexOf('logAuthDiagnostic("TOKEN_SAVED"'));
  assert.ok(authBody.indexOf('logAuthDiagnostic("TOKEN_SAVED"') < authBody.indexOf("hydrate(token.access_token, authStage)"));
  assert.ok(appSource.includes('getMe(authStage ? "hydration_me" : undefined)'));
  assert.ok(appSource.includes('logAuthDiagnostic("PROFILE_LOADED", authStage)'));
  const probeStart = appSource.indexOf("async function probeApiHealth()");
  const probeEnd = appSource.indexOf("async function submitPasswordResetRequest()", probeStart);
  const probeBody = appSource.slice(probeStart, probeEnd);
  assert.ok(probeBody.includes("await getApiHealth("));
  assert.ok(!probeBody.includes("register(") && !probeBody.includes("login("), "health probe must never start auth");
  assert.ok(appSource.includes("{__DEV__ && <>") && appSource.includes("Pressable disabled={apiHealthProbeBusy}"), "probe control must be DEV-only");
  for (const visibleResult of ["debug.apiHealthTarget", "debug.apiHealthInProgress", "debug.apiHealthHttp", "debug.apiHealthHttpError", "debug.apiHealthNetworkError"]) {
    assert.ok(appSource.includes(visibleResult), `DEV UI must expose ${visibleResult}`);
  }
  console.log("API auth/health diagnostics: HTTP/network distinction, exact runtime health URL, GET-only probe, redaction and production guard PASS");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
