const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const React = require('react');
function compile(source, extras = {}) {
  const exports = {};
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS } }).outputText, { exports, ...extras });
  return exports;
}
const order = compile(fs.readFileSync(`${__dirname}/order-actions.ts`, 'utf8'));
const paymentFlow = compile(fs.readFileSync(`${__dirname}/payment-flow.ts`, 'utf8'));
const paymentReturn = compile(fs.readFileSync(`${__dirname}/payment-return.ts`, 'utf8'));
const paymentUi = compile(fs.readFileSync(`${__dirname}/payment-ui-state.ts`, 'utf8'));
const sessions = compile(fs.readFileSync(`${__dirname}/payment-session.ts`, 'utf8'), {
  require: () => ({ default: { getItem: async () => null, setItem: async () => {}, removeItem: async () => {} } }),
});
assert.equal(paymentUi.resolvePaymentUiState({ status: 'approved' }, true, true), 'approved');
assert.equal(paymentUi.resolvePaymentUiState({ id: 'pending', status: 'pending' }, false, true), 'verifying');
assert.equal(paymentUi.resolvePaymentUiState({ status: 'pending' }, false, true), 'idle');
assert.equal(paymentUi.resolvePaymentUiState(null, false, true), 'idle');
assert.equal(paymentUi.resolvePaymentUiState({ status: 'declined' }, false, false), 'failed');
assert.equal(paymentUi.resolvePaymentUiState(null, true, false), 'redirecting');
assert.equal(paymentUi.resolvePaymentUiState(null, false, false), 'idle');
assert.equal(paymentReturn.paymentIdFromReturn({ path: 'payment-return', queryParams: { payment_id: 'payment-a' } }), 'payment-a');
assert.equal(paymentReturn.paymentIdFromReturn({ path: 'other', queryParams: { payment_id: 'payment-a' } }), null);
assert.equal(paymentReturn.paymentIdFromReturn({ path: 'payment-return', queryParams: { payment_id: ['payment-a'] } }), null);
const t = (key, params = {}) => key + (params.total ?? params.count ?? '');
function component(name) {
  return compile(fs.readFileSync(`${__dirname}/components/${name}.tsx`, 'utf8'), { require: (path) => {
    if (path === 'react') return { useEffect() {} };
    if (path === 'react/jsx-runtime') return require(path);
    if (path === 'react-native') return { View: 'View', Text: 'Text', TextInput: 'TextInput', Pressable: 'Pressable', Image: 'Image', StyleSheet: { create: (s) => s } };
    if (path.includes('Ionicons')) return 'Icon';
    if (path === '../i18n') return { t };
    if (path === '../format') return { formatMoney: String };
    if (path === '../config') return { mediaUrl: String };
    if (path === '../client-content') return compile(fs.readFileSync(`${__dirname}/client-content.ts`, 'utf8'));
    if (path === '../order-actions') return order;
    if (path === '../payment-flow') return paymentFlow;
    if (path === '../payment-ui-state') return paymentUi;
    if (path === './PrimaryButton') return { PrimaryButton: 'PrimaryButton' };
    if (path === './PaymentActions') return component('PaymentActions');
    if (path.startsWith('../theme/')) return { colors: {}, fonts: {}, radius: {}, spacing: {} };
    throw new Error(path);
  } });
}
function nodes(e) {
  if (!React.isValidElement(e)) return [];
  if (typeof e.type === 'function') return nodes(e.type(e.props));
  return [e, ...React.Children.toArray(e.props.children).flatMap(nodes)];
}
const item = { dish_id: 'dish-a', availability_id: 'a', cook_id: 'seller', dish_name: 'Poulet', cook_display_name: 'Cuisine', price: '19000.00', currency: 'COP', photo_url: '/image.jpg', remaining_portions: null, is_open: true };
const line = { item, quantity: 2 };
const { CartBar } = component('CartBar');
assert.equal(CartBar({ cart: [], onPress() {} }), null);
let opened = false;
const bar = nodes(CartBar({ cart: [line], onPress() { opened = true; } }));
bar.find((n) => n.type === 'Pressable').props.onPress();
assert.ok(opened);
assert.ok(bar.some((n) => n.props.children === 'cart.itemsCountPlural2'));
assert.ok(bar.some((n) => n.props.children === '38000.00'));
const singularBar = nodes(CartBar({ cart: [{ ...line, quantity: 1 }], onPress() {} }));
assert.ok(singularBar.some((n) => n.props.children === 'cart.itemsCountSingular1'));
const { CartScreen } = component('CartScreen');
let continued = false;
nodes(CartScreen({ cart: [line], onContinue() { continued = true; } })).find((n) => n.props.label === 'cart.continue').props.onPress();
assert.ok(continued);
const { CartSummary } = component('CartSummary');
let requested = false;
const secondLine = { item: { ...item, dish_id: "dish-b", availability_id: "b", dish_name: "Riz", price: "24000.00" }, quantity: 1 };
const summary = nodes(CartSummary({ lines: [line, secondLine], payment: null, error: null, busy: false, onPay() { requested = true; } }));
summary.find((n) => n.props.label === 'checkout.pay62000.00').props.onPress();
assert.ok(requested);
assert.ok(summary.some((n) => n.props.children === "Riz"));
assert.equal(summary.filter((n) => n.props.label?.startsWith("checkout.pay")).length, 1);
let chosenNetwork;
let enteredPhone = '';
const xofSummary = nodes(CartSummary({ lines: [{ ...line, item: { ...item, currency: 'XOF' } }], payment: null,
  busy: false, network: 'WAVE', phone: enteredPhone, onPhone(value) { enteredPhone = value; },
  onNetwork(value) { chosenNetwork = value; } }));
const phoneInput = xofSummary.find((n) => n.type === 'TextInput');
assert.equal(phoneInput.props.editable, true);
assert.equal(phoneInput.props.keyboardType, 'phone-pad');
assert.equal(phoneInput.props.style.borderWidth, 1);
assert.ok(phoneInput.props.style.minHeight >= 44);
assert.ok(phoneInput.props.placeholder);
phoneInput.props.onChangeText('221770000000');
assert.equal(enteredPhone, '221770000000');
const updatedPhone = nodes(CartSummary({ lines: [{ ...line, item: { ...item, currency: 'XOF' } }],
  payment: null, busy: false, phone: enteredPhone })).find((n) => n.type === 'TextInput');
assert.equal(updatedPhone.props.value, enteredPhone);
const methods = xofSummary.filter((n) => n.props.accessibilityRole === 'radio');
assert.equal(methods.length, 2);
assert.equal(methods[0].props.accessibilityState.checked, true);
methods[1].props.onPress();
assert.equal(chosenNetwork, 'ORANGEMONEY');
methods[0].props.onPress();
assert.equal(chosenNetwork, 'WAVE');
let checked = false;
const pendingOutsideCart = nodes(CartSummary({
  lines: [line], payment: { id: 'pending', availability_id: 'removed', status: 'pending' },
  error: null, busy: false, paidIds: [], onCheck() { checked = true; },
}));
pendingOutsideCart.find((n) => n.props.label === 'checkout.checkPayment').props.onPress();
assert.ok(checked);
assert.equal(pendingOutsideCart.find((n) => n.props.label === 'checkout.pay38000.00'), undefined);
const staleFailure = nodes(CartSummary({ lines: [line], payment: null, error: 'stale', busy: false }));
assert.equal(staleFailure.some((n) => n.props.label?.startsWith('checkout.retryPayment')), false);
assert.ok(staleFailure.some((n) => n.props.label?.startsWith('checkout.pay')));
const verifiedFailure = nodes(CartSummary({ lines: [line], payment: { id: 'failed', status: 'declined' }, error: 'failed', busy: false }));
assert.ok(verifiedFailure.some((n) => n.props.label?.startsWith('checkout.retryPayment')));
const approvedWithStaleError = nodes(CartSummary({
  lines: [line], merchantName: 'Restaurant Sénégal',
  payment: { id: 'approved', order_id: 'order-1', status: 'approved', amount_in_cents: 1800000, currency: 'XOF', items: [{ availability_id: 'a', quantity: 2 }] },
  error: 'stale', busy: false,
}));
assert.ok(approvedWithStaleError.some((n) => n.props.children === 'clientExperience.confirmed'));
assert.ok(approvedWithStaleError.some((n) => n.props.children === 'Restaurant Sénégal'));
assert.equal(approvedWithStaleError.some((n) => n.props.label?.startsWith('checkout.pay')), false);
assert.equal(approvedWithStaleError.some((n) => n.props.label?.startsWith('checkout.retryPayment')), false);

const source = ts.createSourceFile('App.tsx', fs.readFileSync(`${__dirname}/../App.tsx`, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const appText = source.getFullText();
assert.ok(appText.includes('screen !== "cart" && screen !== "cartSummary"'));
assert.ok(appText.includes('{showBottomNavigation && <View style={styles.bottomNavigationSlot}>'));
assert.ok(appText.includes('Linking.addEventListener("url"'));
assert.ok(appText.includes('paymentIdentityFromReturn(parsed)'));
assert.ok(appText.includes('void checkPayment()'));
assert.ok(appText.includes('sessionExpired && !authError && <Text style={styles.error}>{t("error.auth")}</Text>'));
assert.ok(appText.includes('sessionExpired ? t("auth.reconnect")'));
assert.ok(appText.includes('{!registering && <Pressable onPress={() => { setPasswordResetEmail(email);'));
const functions = {};
function visit(node) {
  if (ts.isFunctionDeclaration(node)) functions[node.name.text] = node.getText(source);
  ts.forEachChild(node, visit);
}
visit(source);
async function testPayTechWarning() {
  let buttons;
  const context = {
    t,
    Alert: { alert(_title, message, actions) {
      assert.equal(message, 'checkout.paytechWarning'); buttons = actions;
    } },
  };
  vm.createContext(context);
  vm.runInContext(ts.transpileModule(functions.confirmPayTechTest, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText, context);
  assert.equal(await context.confirmPayTechTest('payu'), true);
  const decision = context.confirmPayTechTest('paytech');
  buttons[0].onPress();
  assert.equal(await decision, false);
  const accepted = context.confirmPayTechTest('paytech');
  buttons[1].onPress();
  assert.equal(await accepted, true);
}
testPayTechWarning().catch((error) => { console.error(error); process.exitCode = 1; });
let currencyWarning = null;
const mixedCartContext = {
  selectedDish: { ...item, currency: 'XOF', availability_id: 'xof' }, cart: [line],
  cartActionLock: { current: false }, requestAnimationFrame(fn) { fn(); },
  canOrderQuantity: order.canOrderQuantity, hasMixedCartCurrency: order.hasMixedCartCurrency,
  Alert: { alert(_title, message) { currencyWarning = message; } }, t,
  setCart() { throw new Error('Mixed cart must not be modified'); },
  setPendingCartReplacement() { throw new Error('No silent currency replacement'); },
};
vm.createContext(mixedCartContext);
vm.runInContext(ts.transpileModule(functions.addSelectedDishToCart, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText, mixedCartContext);
mixedCartContext.addSelectedDishToCart(1);
assert.equal(currencyWarning, 'cart.mixedCurrency');
let guardedCart = [], releaseCartAction;
const guardedCartContext = {
  selectedDish: item, cart: guardedCart, cartActionLock: { current: false },
  canOrderQuantity: order.canOrderQuantity, hasMixedCartCurrency: order.hasMixedCartCurrency,
  requiresCartReplacement: order.requiresCartReplacement, addCartItem: order.addCartItem,
  Alert: { alert() {} }, t, setPendingCartReplacement() {},
  requestAnimationFrame(fn) { releaseCartAction = fn; },
  setCart(update) { guardedCart = update(guardedCart); guardedCartContext.cart = guardedCart; },
  currentCart: { current: guardedCart },
  updateClientCart(next) { guardedCart = next; guardedCartContext.currentCart.current = next; guardedCartContext.cart = next; },
};
vm.createContext(guardedCartContext);
vm.runInContext(ts.transpileModule(functions.addSelectedDishToCart, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText, guardedCartContext);
guardedCartContext.addSelectedDishToCart(1);
guardedCartContext.addSelectedDishToCart(1);
assert.equal(guardedCart[0].quantity, 1);
releaseCartAction();
guardedCartContext.addSelectedDishToCart(1);
assert.equal(guardedCart[0].quantity, 2);
let returnedScreen = null, returnedProfile = null, clearedDish = false;
const detailReturnContext = {
  detailProfileReturn: { current: { cook_id: 'seller' } },
  setSelectedDish(value) { clearedDish = value === null; },
  setProfile(value) { returnedProfile = value; },
  setScreen(value) { returnedScreen = value; },
};
vm.createContext(detailReturnContext);
vm.runInContext(ts.transpileModule(functions.continueShopping, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText, detailReturnContext);
detailReturnContext.continueShopping();
assert.ok(clearedDish);
assert.equal(returnedProfile.cook_id, 'seller');
assert.equal(returnedScreen, 'cookProfile');
detailReturnContext.detailProfileReturn.current = null;
detailReturnContext.continueShopping();
assert.equal(returnedScreen, 'discover');
const { formatMoney } = compile(fs.readFileSync(`${__dirname}/format.ts`, 'utf8'), {
  require(path) {
    if (path === './language') return { ACTIVE_LOCALE: 'fr' };
    if (path === './market') return { ACTIVE_MARKET: { currency: 'COP' } };
    throw new Error(path);
  },
});
assert.match(formatMoney('4500', 'XOF'), /4\s*500/);
assert.match(formatMoney('4500', 'XOF'), /F\s*CFA|XOF/);
assert.match(formatMoney('24000', 'COP'), /24\s*000/);
assert.notEqual(formatMoney('4500', 'XOF'), formatMoney('4500', 'COP'));
let cartBarExpression;
function findCartBar(node) {
  if (ts.isJsxExpression(node) && node.expression?.getText(source).includes('<CartBar')) cartBarExpression = node.expression.getText(source);
  ts.forEachChild(node, findCartBar);
}
findCartBar(source);
assert.ok(cartBarExpression);
for (const screen of ['discover', 'cart', 'cartSummary', 'orders', 'account']) {
  const { visible } = compile(`export const visible = ${cartBarExpression};`, {
    require, mode: 'client', screen, selectedDish: null, CartBar: 'CartBar', cart: [line], openCart() {},
  });
  assert.equal(!!visible, screen === 'discover');
}
async function testFlow() {
  let cart = [line], calls = 0, links = 0, mode = 'approved', error = null;
  let provider = 'payu', sandboxCalls = 0, paymentReads = [], getPaymentCalls = 0;
  const context = {
    __DEV__: true,
    ExpoLinking: { createURL: (path) => `kwitli://${path}` },
    ...sessions,
    clearCheckoutPayment: async () => {},
    loadCheckoutPayment: async () => context.payment ? context.activeCheckout.current : null,
    loadLastCheckoutPayment: async () => null,
    saveCheckoutPayment: async () => {},
    saveReturnedPayment: async () => {},
    me: { user: { id: 'customer' } }, checkoutMerchantName: 'Chez Awa', reservationError: null,
    returnedPayment: { current: null }, recoveryTask: { current: null },
    activeCheckout: { current: sessions.newCheckoutSession('customer', [line, secondLine]) },
    cartChanged: { current: true }, currentCart: { current: cart },
    setCheckoutMerchantName() {}, setScreen() {}, setSelectedDish() {},
    getPaymentByReference: async () => { throw new Error('Unexpected reference lookup'); },
    paymentNetwork: 'WAVE', paymentPhone: '221770000000',
    confirmPayTechTest: async () => true,
    checkoutLines: [line, secondLine], payment: null,
    paymentLaunchLock: { current: false }, paymentVerificationLock: { current: false },
    paymentVerificationRequested: { current: false }, paymentSession: { current: 0 }, unopenedCheckout: { current: null },
    appliedPayments: { current: new Set() }, t, canOrderQuantity: order.canOrderQuantity,
    detailProfileReturn: { current: null }, setProfile() {},
    ApiError: class extends Error {},
    setOpeningPayment() {}, setPaidIds() {},
    setReservationError(value) { error = value; },
    setCart(update) { cart = update(cart); },
    setPayment(value) { context.payment = typeof value === 'function' ? value(context.payment) : value; },
    refreshDiscover: async () => {},
    setTimeout(fn) { fn(); },
    createPayment: async (body) => {
      calls++;
      if (provider === 'flutterwave') {
        assert.equal(body.network, context.paymentNetwork);
        assert.equal(body.phone_number, '221770000000');
        assert.equal(body.return_url, 'kwitli://payment-return');
      }
      assert.equal(body.items.length, 2); assert.equal(body.items[0].dish_id, 'dish-a'); assert.equal(body.items[0].availability_id, undefined); assert.equal(body.items[0].quantity, 2); assert.equal(body.items[1].dish_id, 'dish-b');
      if (mode === 'network') throw new Error('network');
      return paymentFixture(provider === 'paydunya' ? 'xof' : 'p', 'pending');
    },
    paySandboxInvoice: async () => {
      sandboxCalls++;
      return paymentFixture('xof', 'approved');
    },
    getPayment: async (id) => {
      getPaymentCalls++;
      const queued = paymentReads.shift();
      if (queued instanceof Error) throw queued;
      return { ...paymentFixture(id, queued?.status ?? mode), ...queued, items: paymentFixture(id, mode).items };
    },
    paymentCheckoutUrl: () => 'https://example.invalid/checkout',
    Linking: { openURL: async () => { links++; } },
  };
  function paymentFixture(id, status) {
    return { id, status, provider, provider_reference: `ref-${id}`,
      currency: context.checkoutLines[0].item.currency,
      amount_in_cents: context.checkoutLines.reduce((sum, entry) => sum + Number(entry.item.price) * 100 * entry.quantity, 0),
      items: context.checkoutLines.map(entry => ({ dish_id: entry.item.dish_id, availability_id: entry.item.availability_id, quantity: entry.quantity })) };
  }
  // Chaque remise a null dans ces scenarios demarre explicitement un nouveau checkout.
  let currentPayment = null, preserveCheckoutOnNull = false;
  Object.defineProperty(context, 'payment', {
    get: () => currentPayment,
    set(value) {
      currentPayment = value;
      if ((!value && !preserveCheckoutOnNull) || context.activeCheckout.current?.state !== 'active') {
        context.activeCheckout.current = sessions.newCheckoutSession('customer', context.checkoutLines);
      }
      if (value) Object.assign(context.activeCheckout.current, { paymentId: value.id, txRef: `ref-${value.id}` });
    },
  });
  vm.createContext(context);
  for (const name of ['applyPaymentStatus', 'verifyExistingPayment', 'recoverCheckoutPayment', 'checkPayment', 'startPayment']) {
    vm.runInContext(ts.transpileModule(functions[name], { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText, context);
  }
  mode = 'declined';
  await context.startPayment(line);
  assert.equal(calls, 1); assert.equal(links, 1); assert.equal(cart.length, 1); assert.ok(error);
  mode = 'approved';
  await context.startPayment(line);
  assert.equal(calls, 1, 'A stale failure must be rechecked before creating another Payment');
  assert.equal(cart.length, 0);
  context.applyPaymentStatus(context.payment);
  assert.equal(cart.length, 0);
  cart = [line]; context.payment = null; mode = 'network';
  await context.startPayment(line);
  assert.equal(cart.length, 1);
  assert.equal(error, 'checkout.paymentFailed', 'Non-401 payment errors keep payment feedback');
  context.payment = { id: 'pending', status: 'pending' }; mode = 'pending';
  const before = calls;
  await context.startPayment(line);
  assert.equal(calls, before, 'Pending payment must not create duplicate payments');
  assert.equal(cart.length, 1);
  let screen;
  context.setScreen = (value) => { screen = value; };
  context.setSelectedDish = () => {};
  context.cartReturn = { current: { screen: 'discover', dish: item } };
  vm.runInContext(functions.closeCart, context);
  context.closeCart();
  assert.equal(screen, 'discover'); assert.equal(cart.length, 1);
  vm.runInContext(functions.continueShopping, context);
  context.continueShopping();
  assert.equal(screen, 'discover'); assert.equal(cart.length, 1);
  provider = 'paydunya'; mode = 'approved'; context.payment = null;
  const previousLinks = links;
  await context.startPayment();
  assert.equal(sandboxCalls, 1);
  assert.equal(links, previousLinks, 'PayDunya never opens an external checkout');
  assert.equal(cart.length, 0);
  provider = 'paytech'; context.payment = null; cart = [line];
  const paytechLinks = links;
  await context.startPayment();
  assert.equal(links, paytechLinks + 1, 'PayTech test uses existing external checkout path');
  assert.equal(sandboxCalls, 1, 'PayTech must never invoke PayDunya SoftPay');
  context.payment = null; context.confirmPayTechTest = async () => false;
  const beforeCancel = links;
  await context.startPayment();
  assert.equal(links, beforeCancel, 'Declining test charge must not open checkout');
  assert.ok(context.unopenedCheckout.current, 'Pending checkout remains available after canceling warning');
  provider = 'flutterwave'; mode = 'approved'; context.payment = null; cart = [line];
  context.appliedPayments.current.clear();
  context.checkoutLines = [line, secondLine].map(entry => ({ ...entry, item: { ...entry.item, currency: 'XOF' } }));
  context.payment = null;
  const beforeFlutterwave = links;
  await context.startPayment();
  assert.equal(links, beforeFlutterwave, 'Flutterwave callback mode must not open a URL');
  assert.equal(cart.length, 0, 'Server approval applies existing cart cleanup');
  context.payment = null; context.paymentNetwork = 'ORANGEMONEY';
  await context.startPayment();
  context.payment = null; context.paymentPhone = '';
  const beforeInvalidPhone = calls;
  await context.startPayment();
  assert.equal(calls, beforeInvalidPhone, 'Empty phone must not start a payment');
  assert.equal(error, 'checkout.mobileMoneyRequired');
  context.paymentPhone = '221770000000';
  context.payment = null; context.paymentNetwork = null; cart = [line];
  const beforeMissingMethod = calls;
  await context.startPayment();
  assert.equal(calls, beforeMissingMethod);
  assert.equal(error, 'checkout.mobileMoneyRequired');
  assert.equal(cart.length, 1);

  context.paymentNetwork = 'WAVE'; context.payment = { id: 'p', status: 'pending' };
  context.paymentLaunchLock.current = true; mode = 'approved'; error = 'stale-error'; cart = [line];
  const creationsBeforeReturn = calls;
  const readsBeforeReturn = getPaymentCalls;
  await context.checkPayment();
  assert.equal(calls, creationsBeforeReturn, 'Return verification must not create a Payment');
  assert.equal(getPaymentCalls, readsBeforeReturn + 1, 'Return verification must run while launch lock is active');
  assert.equal(context.payment.status, 'approved');
  assert.equal(error, null);
  context.paymentLaunchLock.current = false;

  context.payment = null; error = 'stale-error'; cart = [line]; mode = 'approved';
  context.loadCheckoutPayment = async () => ({ ...context.activeCheckout.current, paymentId: 'p-stored', txRef: 'ref-p-stored' });
  paymentReads = [{ id: 'p-stored', status: 'approved', items: [{ availability_id: 'a', quantity: 2 }] }];
  const creationsBeforeStoredRecovery = calls;
  await context.recoverCheckoutPayment('a:2');
  assert.equal(calls, creationsBeforeStoredRecovery, 'Stored checkout recovery must not create a Payment');
  assert.equal(context.payment.status, 'approved');
  assert.equal(error, null);
  assert.equal(cart.length, 0);
  context.loadCheckoutPayment = async () => context.payment ? context.activeCheckout.current : null;

  context.appliedPayments.current.clear(); cart = [line]; context.payment = null; error = null;
  paymentReads = [new Error('503'), { id: 'p', status: 'approved', items: [{ availability_id: 'a', quantity: 2 }] }];
  await context.startPayment();
  assert.equal(context.payment.status, 'approved');
  assert.equal(error, null);
  assert.equal(cart.length, 0, 'Approved status alone clears the paid cart lines');

  context.appliedPayments.current.clear(); cart = [line]; context.payment = { id: 'p-timeout', status: 'pending' }; error = null;
  paymentReads = [new Error('timeout')];
  await context.checkPayment();
  assert.equal(context.payment.status, 'pending');
  assert.equal(paymentUi.resolvePaymentUiState(context.payment, false, !!error), 'verifying');
  assert.equal(cart.length, 1);

  paymentReads = [
    { id: 'p-later', status: 'pending' },
    { id: 'p-later', status: 'approved', items: [{ availability_id: 'a', quantity: 2 }] },
  ];
  context.payment = { id: 'p-later', status: 'pending' };
  await context.checkPayment();
  assert.equal(context.payment.status, 'pending'); assert.equal(cart.length, 1);
  await context.checkPayment();
  assert.equal(context.payment.status, 'approved'); assert.equal(cart.length, 0);
  await context.checkPayment();
  assert.equal(cart.length, 0, 'Duplicate verification must not reapply cart effects');

  cart = [line]; context.payment = { id: 'p-failed', status: 'pending' }; error = null;
  paymentReads = [{ id: 'p-failed', status: 'declined' }];
  await context.checkPayment();
  assert.equal(context.payment.status, 'declined');
  assert.equal(error, 'checkout.paymentFailed');
  assert.equal(cart.length, 1);
  console.log('Cart bar, cart screen, summary, PayU wiring, failures, pending payment and back navigation: PASS');

  // Une sauvegarde lente bloque la redirection et un second tap.
  context.payment = null; context.reservationError = null; context.checkoutMerchantName = 'Chez Awa';
  context.loadCheckoutPayment = async () => null;
  context.returnedPayment.current = null;
  context.confirmPayTechTest = async () => true;
  provider = 'paytech'; mode = 'pending';
  let finishSave;
  context.saveCheckoutPayment = () => new Promise(resolve => { finishSave = resolve; });
  const beforeCreate = calls, beforeOpen = links;
  const launch = context.startPayment();
  for (let i = 0; i < 20 && !finishSave; i++) await Promise.resolve();
  assert.ok(finishSave);
  assert.equal(links, beforeOpen);
  await context.startPayment();
  assert.equal(calls, beforeCreate + 1);
  finishSave();
  await launch;
  assert.equal(links, beforeOpen + 1);

  context.payment = null;
  context.saveCheckoutPayment = async () => { throw new Error('Storage unavailable'); };
  const beforeStorageFailure = links;
  await context.startPayment();
  assert.equal(links, beforeStorageFailure, 'No external redirect before durable identity');
  assert.equal(context.payment.status, 'pending');

  context.saveCheckoutPayment = async () => {};
  context.loadCheckoutPayment = async () => ({ ...context.activeCheckout.current, paymentId: 'existing', txRef: 'ref-existing' });
  context.payment = null; paymentReads = [new Error('timeout')];
  const beforeRecoveryFailure = calls;
  await context.startPayment();
  assert.equal(calls, beforeRecoveryFailure, 'Failed recovery must never create another Payment');

  // Un 401 avant creation du Payment renvoie a la connexion sans effacer le panier.
  context.payment = null;
  context.loadCheckoutPayment = async () => null;
  context.saveCheckoutPayment = async () => {};
  context.paymentNetwork = 'WAVE'; context.paymentPhone = '221770000000';
  context.checkoutLines = [line, secondLine].map(entry => ({ ...entry, item: { ...entry.item, currency: 'XOF' } }));
  context.payment = null;
  preserveCheckoutOnNull = true;
  let tokenCleared = false, storedTokenDeleted = false, authExpired = false, loginShown = false;
  context.setAccessToken = value => { tokenCleared = value === null; };
  context.deleteAccessToken = async () => { storedTokenDeleted = true; };
  context.setMe = value => { context.me = value; };
  context.setWelcomeDismissed = value => { loginShown = value; };
  context.setRegistering = () => {};
  context.setAuthError = () => {};
  context.setSessionExpired = value => { authExpired = value; };
  context.createPayment = async () => {
    calls++;
    const rejected = new context.ApiError('Unauthorized');
    rejected.status = 401;
    throw rejected;
  };
  vm.runInContext(ts.transpileModule(functions.expireSession, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText, context);
  const beforeUnauthorized = calls;
  const checkoutBeforeUnauthorized = context.activeCheckout.current;
  await context.startPayment();
  assert.equal(calls, beforeUnauthorized + 1);
  assert.equal(context.payment, null, 'No phantom Payment after 401');
  assert.equal(cart.length, 1); assert.equal(cart[0].quantity, 2);
  assert.deepEqual(context.checkoutLines.map(entry => entry.quantity), [2, 1]);
  assert.equal(context.activeCheckout.current, checkoutBeforeUnauthorized, 'Checkout identity is preserved');
  assert.equal(tokenCleared, true); assert.equal(storedTokenDeleted, true);
  assert.equal(authExpired, true); assert.equal(loginShown, true);
  assert.equal(context.me, null);
  assert.equal(error, null, '401 is not displayed as payment failure');
  assert.equal(calls, beforeUnauthorized + 1, 'No automatic Payment retry after 401');

  context.email = 'client@example.test'; context.password = 'password'; context.registering = false;
  context.login = async () => ({ access_token: 'new-token' });
  context.saveAccessToken = async () => {};
  context.hydrate = async () => { context.me = { user: { id: 'customer' } }; };
  context.logAuthDiagnostic = () => {};
  vm.runInContext(ts.transpileModule(functions.authenticate, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText, context);
  await context.authenticate();
  assert.equal(authExpired, false);
  assert.equal(calls, beforeUnauthorized + 1, 'Login alone never creates a Payment');
  assert.equal(cart.length, 1); assert.equal(cart[0].quantity, 2);
  assert.equal(context.activeCheckout.current, checkoutBeforeUnauthorized);
  context.createPayment = async () => { calls++; return paymentFixture('after-login', 'pending'); };
  provider = 'flutterwave'; mode = 'pending';
  await context.startPayment();
  assert.equal(calls, beforeUnauthorized + 2, 'One manual retry creates one Payment');
  assert.equal(context.payment.id, 'after-login');
  assert.equal(cart.length, 1, 'Pending Payment preserves the cart');
  preserveCheckoutOnNull = false;
}
testFlow().catch((error) => { console.error(error); process.exitCode = 1; });
