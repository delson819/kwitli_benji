const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');

function compile(source, context) {
  vm.runInContext(ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText, context);
}

async function test() {
  let returnUrl = 'kwitli://payment-return';
  let result = { type: 'success', url: `${returnUrl}?payment_id=current` };
  let authCalls = 0, browserCalls = 0, externalCalls = 0;
  const platform = { OS: 'android' };
  const context = vm.createContext({ exports: {}, require(name) {
    if (name === 'expo-linking') return { createURL: path => {
      assert.equal(path, 'payment-return'); return returnUrl;
    } };
    if (name === 'expo-web-browser') return { openBrowserAsync: async (url) => {
      browserCalls++;
      assert.equal(url, 'https://checkout.flutterwave.com/test');
      return { type: 'opened' };
    }, openAuthSessionAsync: async (url, redirect) => {
      authCalls++;
      assert.equal(url, 'https://checkout.flutterwave.com/test');
      assert.equal(redirect, returnUrl);
      if (result instanceof Error) throw result;
      return result;
    } };
    if (name === 'react-native') return { Platform: platform, Linking: { openURL: async () => { externalCalls++; } } };
    throw Error(name);
  } });
  compile(fs.readFileSync(`${__dirname}/payment-browser.ts`, 'utf8'), context);
  const open = context.exports.openFlutterwaveBrowser;
  assert.equal(await open('https://checkout.flutterwave.com/test'), result.url);
  for (const type of ['cancel', 'dismiss']) {
    result = { type };
    assert.equal(await open('https://checkout.flutterwave.com/test'), null);
  }
  result = Error('Browser unavailable');
  await assert.rejects(open('https://checkout.flutterwave.com/test'), /Browser unavailable/);
  const beforeGo = authCalls;
  returnUrl = 'exp://127.0.0.1:8081/--/payment-return';
  assert.equal(await open('https://checkout.flutterwave.com/test'), null);
  assert.equal(authCalls, beforeGo, 'Do not claim a custom Kwitli auth session in Expo Go');
  assert.equal(browserCalls, 1, 'Android Expo Go uses a closable system browser tab');
  assert.equal(externalCalls, 0);
  platform.OS = 'ios';
  assert.equal(await open('https://checkout.flutterwave.com/test'), null);
  assert.equal(externalCalls, 1);

  const source = ts.createSourceFile('App.tsx', fs.readFileSync(`${__dirname}/../App.tsx`, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const functions = {};
  function visit(node) {
    if (ts.isFunctionDeclaration(node) && node.name) functions[node.name.text] = node.getText(source);
    ts.forEachChild(node, visit);
  }
  visit(source);
  const parsed = vm.createContext({ exports: {} });
  compile(fs.readFileSync(`${__dirname}/payment-return.ts`, 'utf8'), parsed);
  let resolveBrowser, rejectBrowser, checks = 0;
  const app = vm.createContext({
    paymentSession: { current: 1 }, returnedPayment: { current: null }, me: { user: { id: 'client' } },
    paymentIdentityFromReturn: parsed.exports.paymentIdentityFromReturn,
    // handleAppUrl traite aussi les liens de reinitialisation : aucun ici.
    passwordResetTokenFromUrl: () => null,
    ExpoLinking: { parse(url) {
      const u = new URL(url);
      return { hostname: u.hostname, path: u.pathname.replace(/^\//, ''), queryParams: Object.fromEntries(u.searchParams) };
    } },
    openFlutterwaveBrowser: () => new Promise((resolve, reject) => { resolveBrowser = resolve; rejectBrowser = reject; }),
    checkPayment: async () => { checks++; },
    createPayment: () => { throw Error('No new Payment allowed on return'); },
  });
  // Le gestionnaire de retour s'appelle desormais handleAppUrl dans App.tsx.
  compile(functions.handleAppUrl, app);
  compile(functions.openFlutterwavePage, app);
  assert.equal(app.openFlutterwavePage('https://checkout.flutterwave.com/test'), undefined,
    'Browser lifetime must not hold the payment creation lock');
  assert.equal(checks, 0);
  resolveBrowser('kwitli://payment-return?payment_id=current&status=successful');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(app.returnedPayment.current.paymentId, 'current');
  assert.equal(checks, 1, 'Return must request existing server verification, never approval');
  app.openFlutterwavePage('https://checkout.flutterwave.com/test');
  app.paymentSession.current++;
  resolveBrowser('kwitli://payment-return?payment_id=old');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(checks, 1, 'A browser result from a previous checkout must be ignored');
  assert.equal(app.returnedPayment.current.paymentId, 'current');
  for (const cancel of [true, false]) {
    app.openFlutterwavePage('https://checkout.flutterwave.com/test');
    if (cancel) resolveBrowser(null);
    else rejectBrowser(Error('Browser unavailable'));
    await new Promise(resolve => setImmediate(resolve));
  }
  assert.equal(checks, 3, 'Cancel/error only rechecks the same payment');
  console.log('Native browser return, Expo Go limitation, cancellation, checkout isolation and verification delegation: PASS');
}
test().catch(error => { console.error(error); process.exitCode = 1; });
