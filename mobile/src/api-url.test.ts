import assert from "node:assert/strict";
import { resolveApiUrl, resolveConfiguredApiUrl } from "./api-url.ts";

assert.equal(resolveApiUrl("ios", true), "http://127.0.0.1:8000");
assert.equal(resolveApiUrl("web", true), "http://127.0.0.1:8000");
assert.equal(resolveApiUrl("android", true), "http://10.0.2.2:8000");
assert.equal(resolveApiUrl("android", true, "http://127.0.0.1:8000"), "http://10.0.2.2:8000");
assert.equal(resolveApiUrl("ios", true, "http://10.0.2.2:8000"), "http://127.0.0.1:8000");
assert.equal(resolveApiUrl("android", true, "http://192.168.1.50:8000"), "http://192.168.1.50:8000");
assert.equal(resolveApiUrl("ios", true, "https://api-dev.kwitli.app"), "https://api-dev.kwitli.app");
assert.equal(resolveApiUrl("ios", true, "https://api.kwitli.app"), "https://api.kwitli.app");
assert.equal(resolveApiUrl("android", true, "https://api.kwitli.app"), "https://api.kwitli.app");
assert.equal(resolveConfiguredApiUrl("ios", true, {
  EXPO_PUBLIC_KWITLI_ENV: "staging",
  EXPO_PUBLIC_STAGING_API_URL: "https://api.kwitli.app",
  EXPO_PUBLIC_API_URL: "http://127.0.0.1:8000",
}), "https://api.kwitli.app");
assert.equal(resolveConfiguredApiUrl("ios", true, {
  EXPO_PUBLIC_KWITLI_ENV: "staging",
  EXPO_PUBLIC_API_URL: "http://127.0.0.1:8000",
}), "", "staging must fail closed if its dedicated URL is missing");
assert.equal(resolveConfiguredApiUrl("ios", true, {
  EXPO_PUBLIC_API_URL: "http://127.0.0.1:8000",
}), "http://127.0.0.1:8000", "default DEV configuration remains local");

assert.equal(resolveApiUrl("android", false, "https://api.kwitli.app/"), "https://api.kwitli.app");
assert.equal(resolveApiUrl("ios", false, "https://api.kwitli.app/"), "https://api.kwitli.app");
for (const url of [undefined, "http://127.0.0.1:8000", "https://localhost.:8000", "https://10.0.2.2:8000", "https://192.168.1.50:8000", "https://[::ffff:127.0.0.1]:8000", "http://api.kwitli.app", "not-a-url"]) {
  assert.equal(resolveApiUrl("android", false, url), "", `production rejected ${url}`);
}
