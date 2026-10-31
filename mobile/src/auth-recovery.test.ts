import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { passwordResetTokenFromUrl } from "./auth-recovery.ts";

const validToken = "Abcdefghijklmnopqrstuvwxyz0123456789_-ABCDEFG";

assert.equal(passwordResetTokenFromUrl({ path: "reset-password", queryParams: { token: validToken } }), validToken);
assert.equal(passwordResetTokenFromUrl({ path: "/reset-password", queryParams: { token: validToken } }), validToken);
assert.equal(passwordResetTokenFromUrl({ hostname: "reset-password", path: null, queryParams: { token: validToken } }), validToken);
assert.equal(passwordResetTokenFromUrl({ path: "payment-return", queryParams: { token: validToken } }), null);
assert.equal(passwordResetTokenFromUrl({ path: "reset-password", queryParams: {} }), null);
assert.equal(passwordResetTokenFromUrl({ path: "reset-password", queryParams: { token: [validToken] } }), null);
assert.equal(passwordResetTokenFromUrl({ path: "reset-password", queryParams: { token: "short" } }), null);

const appConfig = JSON.parse(readFileSync("app.json", "utf8"));
assert.equal(appConfig.expo.scheme, "kwitli");
const nativeResetUrl = new URL(`${appConfig.expo.scheme}://reset-password?token=${validToken}`);
assert.equal(
  passwordResetTokenFromUrl({
    hostname: nativeResetUrl.hostname,
    path: nativeResetUrl.pathname || null,
    queryParams: Object.fromEntries(nativeResetUrl.searchParams.entries()),
  }),
  validToken,
);
assert.equal(nativeResetUrl.hostname, "reset-password");

console.log("auth-recovery: PASS");
