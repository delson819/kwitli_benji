const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
let stored = null;
const storage = {
  getItem: async () => stored,
  setItem: async (_key, value) => { stored = value; },
  removeItem: async () => { stored = null; },
};
function load(file) {
  const exports = {};
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(`${__dirname}/${file}`, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText, { exports, require: () => ({ default: storage }) });
  return exports;
}
async function test() {
  const first = load('payment-session.ts');
  const line = { item: { availability_id: 'yassa', cook_id: 'senegal', cook_display_name: 'Restaurant Senegal',
    price: '4500', currency: 'XOF', remaining_portions: 10 }, quantity: 1 };
  const oldLines = [{ ...line, quantity: 4 }];
  const identity = { ...first.newCheckoutSession('client', oldLines), paymentId: 'payment-18000', txRef: 'reference-18000' };
  const idempotencyKey = first.paymentIdempotencyKey(identity);
  assert.equal(idempotencyKey, first.paymentIdempotencyKey(identity), 'Network retries retain the same attempt key');
  assert.notEqual(first.paymentIdempotencyKey({ ...identity, paymentAttempt: 1 }), idempotencyKey,
    'A new key is created only for a new attempt');
  const approved = { id: identity.paymentId, provider_reference: identity.txRef, status: 'approved', order_id: 'existing-order',
    amount_in_cents: 1800000, currency: 'XOF', items: [{ availability_id: 'yassa', quantity: 4 }] };
  await first.saveCheckoutPayment(identity);
  const reloaded = load('payment-session.ts');
  assert.deepEqual(JSON.parse(JSON.stringify(await reloaded.loadCheckoutPayment('client'))), JSON.parse(JSON.stringify(identity)));
  assert.equal(await reloaded.loadCheckoutPayment('other-client'), null);
  const newCart = reloaded.newCheckoutSession('client', [line]);
  assert.equal(reloaded.sameCheckout(identity, newCart), false);
  assert.equal(reloaded.sameCheckout(identity, reloaded.newCheckoutSession('client', oldLines)), false,
    'Even an identical cart must have a distinct session when created again');
  assert.equal(reloaded.paymentMatchesCheckout(newCart, approved), false, '4500 XOF must reject 18000 XOF');
  assert.equal(reloaded.paymentMatchesCheckout(identity, approved), true);
  for (const patch of [{ amount_in_cents: 450000 }, { currency: 'COP' }, { id: 'another' }, { provider_reference: 'another' }]) {
    assert.equal(reloaded.paymentMatchesCheckout(identity, { ...approved, ...patch }), false);
  }
  const calls = [];
  const byId = async id => { calls.push(['id', id]); return { id, status: 'approved' }; };
  const byRef = async ref => { calls.push(['ref', ref]); return approved; };
  assert.equal(await reloaded.readExistingPayment(identity, { txRef: 'old-return' }, byId, byRef), null);
  assert.equal(await reloaded.readExistingPayment(null, { txRef: identity.txRef }, byId, byRef), null);
  await reloaded.readExistingPayment(identity, { txRef: identity.txRef }, byId, byRef);
  await reloaded.readExistingPayment({ txRef: 'stored-ref' }, null, byId, byRef);
  assert.deepEqual(calls, [['id', identity.paymentId], ['ref', 'stored-ref']]);
  assert.equal(await reloaded.readExistingPayment(null, null, byId, byRef), null);
  await assert.rejects(reloaded.readExistingPayment(identity, null, async () => { throw Error('503'); }, byRef), /503/);
  assert.equal(calls.length, 2, 'Network failure cannot fall back to a guessed Payment');
  await reloaded.completeCheckoutPayment(identity.sessionId);
  assert.equal(await reloaded.loadCheckoutPayment('client'), null);
  assert.equal(JSON.parse(stored).paymentId, undefined);
  assert.equal(JSON.parse(stored).txRef, undefined);
  await reloaded.saveCheckoutPayment(newCart);
  await reloaded.completeCheckoutPayment(identity.sessionId);
  assert.equal((await reloaded.loadCheckoutPayment('client')).sessionId, newCart.sessionId,
    'Late completion cannot erase a newer checkout');
  stored = JSON.stringify({ userId: 'client', paymentId: approved.id, txRef: identity.txRef, checkoutKey: 'yassa:4' });
  assert.equal(await reloaded.loadCheckoutPayment('client'), null, 'Unbound legacy records must never be adopted');

  // Executer les vrais handlers App, avec stockage reel en memoire et API de lecture seulement.
  const source = ts.createSourceFile('App.tsx', fs.readFileSync(`${__dirname}/../App.tsx`, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const functions = {};
  function visit(node) {
    if (ts.isFunctionDeclaration(node) && node.name) functions[node.name.text] = node.getText(source);
    ts.forEachChild(node, visit);
  }
  visit(source);
  function harness(session, cart, response = approved) {
    let reads = 0, refreshes = 0;
    const c = {
      ...reloaded, me: { user: { id: 'client' } }, screen: 'cartSummary', cart,
      checkoutLines: session?.lines ?? [], checkoutMerchantName: null, payment: null, error: null,
      currentCart: { current: cart }, cartChanged: { current: !!cart.length }, activeCheckout: { current: session },
      paymentSession: { current: 0 }, recoveryTask: { current: null }, returnedPayment: { current: null },
      paymentRecoveryKey: { current: null }, unopenedCheckout: { current: null },
      appliedPayments: { current: new Set() }, paymentLaunchLock: { current: false },
      setPayment: value => { c.payment = typeof value === 'function' ? value(c.payment) : value; },
      setCart: value => { c.cart = typeof value === 'function' ? value(c.cart) : value; c.currentCart.current = c.cart; },
      setCheckoutLines: value => { c.checkoutLines = value; },
      setCheckoutMerchantName: value => { c.checkoutMerchantName = value; },
      setReservationError: value => { c.error = value; },
      setScreen: value => { c.screen = value; }, setSelectedDish() {}, setOpeningPayment() {},
      t: key => key,
      getPayment: async id => { reads++; assert.equal(id, response.id); return response; },
      getPaymentByReference: async ref => { reads++; assert.equal(ref, response.provider_reference); return response; },
      getOrder: async () => ({ cook_display_name: 'Restaurant Senegal' }),
      refreshDiscover: async () => { refreshes++; },
      createPayment: () => { throw Error('Recovery must never create a Payment'); },
    };
    vm.createContext(c);
    for (const name of ['applyPaymentStatus', 'recoverCheckoutPayment', 'checkPayment', 'continueCart', 'updateClientCart']) {
      vm.runInContext(ts.transpileModule(functions[name], { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText, c);
    }
    return { c, reads: () => reads, refreshes: () => refreshes };
  }
  await reloaded.saveCheckoutPayment(identity);
  let h = harness(newCart, [line]);
  await h.c.recoverCheckoutPayment();
  assert.equal(h.reads(), 0, 'Old session must be rejected BEFORE fetching its Payment');
  assert.equal(h.c.payment, null);
  assert.equal(h.c.cart[0].quantity, 1);
  assert.equal(h.refreshes(), 0);

  // Memes commerce, utilisateur, articles et montant ne suffisent pas sans identite commune.
  h = harness(reloaded.newCheckoutSession('client', oldLines), oldLines);
  await h.c.recoverCheckoutPayment();
  assert.equal(h.reads(), 0);

  // Reprise du meme checkout apres redemarrage, puis retour du meme deep link.
  h = harness(null, []);
  h.c.returnedPayment.current = { txRef: identity.txRef };
  await h.c.recoverCheckoutPayment();
  assert.equal(h.c.payment.status, 'approved');
  assert.equal(h.c.payment.order_id, 'existing-order');
  assert.equal(h.c.checkoutLines[0].quantity, 4);
  assert.equal(h.c.checkoutMerchantName, 'Restaurant Senegal');
  await h.c.recoverCheckoutPayment();
  assert.equal(h.refreshes(), 1, 'Duplicate return must not repeat approval effects');
  assert.equal(h.reads(), 1);
  assert.equal(await reloaded.loadCheckoutPayment('client'), null);
  h.c.updateClientCart([line]);
  h.c.continueCart();
  await h.c.recoverCheckoutPayment();
  assert.equal(h.c.payment, null);
  assert.equal(h.c.checkoutLines[0].quantity, 1);
  assert.notEqual(h.c.activeCheckout.current.sessionId, identity.sessionId);

  await reloaded.saveCheckoutPayment(identity);
  h = harness(identity, oldLines, { ...approved, status: 'pending', order_id: null });
  await h.c.recoverCheckoutPayment();
  assert.equal(h.c.payment.status, 'pending');
  assert.equal(h.c.cart[0].quantity, 4);
  assert.equal(h.refreshes(), 0);

  h = harness(identity, oldLines);
  h.c.returnedPayment.current = { paymentId: approved.id, txRef: identity.txRef };
  await Promise.all([h.c.checkPayment(), h.c.checkPayment()]);
  assert.equal(h.c.payment.status, 'approved');
  assert.equal(h.c.cart.length, 0, 'Only approval of this checkout clears its cart');
  assert.equal(h.reads(), 1, 'Concurrent return checks share the same read');
  assert.equal(h.refreshes(), 1);
  await h.c.checkPayment();
  assert.equal(h.refreshes(), 1);

  // Une reponse en vol ne peut pas recuperer le checkout apres modification du panier.
  await reloaded.saveCheckoutPayment(identity);
  h = harness(identity, oldLines);
  let resolveRead;
  h.c.getPayment = () => new Promise(resolve => { resolveRead = resolve; });
  const recovery = h.c.recoverCheckoutPayment();
  for (let i = 0; i < 30 && !resolveRead; i++) await Promise.resolve();
  assert.ok(resolveRead);
  h.c.updateClientCart([line]);
  resolveRead(approved);
  await recovery;
  assert.equal(h.c.payment, null);
  assert.equal(h.c.cart[0].quantity, 1);
  assert.equal(await reloaded.loadCheckoutPayment('client'), null);

  // Fast Refresh conserve parfois l'ancien etat React, mais pas sa preuve de correlation.
  h = harness(null, [line]);
  h.c.payment = approved;
  h.c.checkoutLines = oldLines;
  h.c.error = 'stale-error';
  await h.c.checkPayment();
  assert.equal(h.c.payment, null);
  assert.equal(h.c.error, null);
  assert.equal(h.c.checkoutLines[0].quantity, 1);
  assert.equal(h.reads(), 0);

  const parser = load('payment-return.ts');
  for (const parsed of [
    { path: 'payment-return', queryParams: { tx_ref: 'reference-1' } },
    { hostname: 'payment-return', path: '', queryParams: { tx_ref: 'reference-1' } },
  ]) assert.equal(parser.paymentIdentityFromReturn(parsed).txRef, 'reference-1');
  assert.equal(parser.paymentIdentityFromReturn({ path: 'other', queryParams: { tx_ref: 'reference-1' } }), null);
  assert.equal(parser.paymentIdentityFromReturn({ path: 'payment-return', queryParams: { tx_ref: ['a', 'b'] } }), null);
  console.log('Checkout identity, 4500/18000 rejection, completion, reload/deep link, race and Fast Refresh safety: PASS');
}
test().catch(error => { console.error(error); process.exitCode = 1; });
