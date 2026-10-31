const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const React = require('react');

function compile(file, requireModule = require, extras = {}) {
  const exports = {};
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(`${__dirname}/${file}`, 'utf8'), {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS },
  }).outputText, { exports, require: requireModule, ...extras });
  return exports;
}
const workflow = compile('orders-workflow.ts');
const fr = require('../locales/fr.json');
const es = require('../locales/es-CO.json');
const t = (key, params = {}) => {
  assert.equal(typeof fr[key], 'string', key);
  assert.equal(typeof es[key], 'string', key);
  return fr[key].replace(/\{(\w+)\}/g, (_, name) => params[name]);
};
assert.equal(t('orders.arrivalOne'), 'Nouvelle commande reçue');
assert.equal(t('orders.arrivalMany', { count: 2 }), '2 nouvelles commandes reçues');
const base = { id: 'order-a', status: 'ordered', created_at: '2026-09-25T12:00:00', cook_display_name: 'Commerce DEV',
  total_price: '10000', currency: 'XOF', review_id: null, availability_id: null, quantity: null, unit_price: null,
  items: [
    { id: 'line-a', dish_name: 'Poulet yassa', quantity: 2, unit_price: '4500', line_total: '9000' },
    { id: 'line-b', dish_name: 'Jus bissap', quantity: 1, unit_price: '1000', line_total: '1000' },
  ] };
function nodes(element) {
  if (!React.isValidElement(element)) return [];
  if (typeof element.type === 'function') return nodes(element.type(element.props));
  return [element, ...React.Children.toArray(element.props.children).flatMap(nodes)];
}
function moduleFor(api, hooks = React, runtime = {}) {
  function load(path) {
    if (path === 'react') return hooks;
    if (path === 'react/jsx-runtime') return require(path);
    if (path.includes('Ionicons')) return { default: 'Icon' };
    if (path === 'react-native') return { View: 'View', Text: 'Text', TextInput: 'TextInput', Pressable: 'Pressable', Modal: 'Modal', ScrollView: 'ScrollView', ActivityIndicator: 'ActivityIndicator', Vibration: { vibrate() { runtime.vibrations = (runtime.vibrations ?? 0) + 1; } },
      AppState: runtime.appState ?? { currentState: 'active', addEventListener: () => ({ remove() {} }) }, StyleSheet: { create: (s) => s } };
    if (path === 'expo-audio') return { createAudioPlayer() { runtime.audioPlays = (runtime.audioPlays ?? 0) + 1; return { seekTo: async () => {}, play() { runtime.audioPlays += 1; }, release() {} }; }, setAudioModeAsync: async () => {} };
    if (path === '../services/api') return api;
    if (path === '../orders-workflow') return workflow;
    if (path === '../client-content') return compile('client-content.ts');
    if (path === '../i18n') return { t };
    if (path === '../language') return { ACTIVE_LOCALE: 'fr' };
    if (path === '../market') return { ACTIVE_MARKET: { timezone: 'Africa/Dakar' }, ACTIVE_MARKET_TIMEZONE: 'Africa/Dakar', resolveTimezone: (business, market) => business || market || 'UTC' };
    if (path === '../format') return { formatMoney: (amount, currency) => `${amount} ${currency}` };
    if (path === './PrimaryButton') return { PrimaryButton: 'PrimaryButton' };
    if (path === './OrderResolutionRequestCard') return { OrderResolutionRequestCard: 'OrderResolutionRequestCard' };
    if (path === './ClientOrderViews') return compile('components/ClientOrderViews.tsx', load);
    if (path.startsWith('../theme/')) return { colors: {}, fonts: {}, radius: {}, spacing: {} };
    throw new Error(path);
  }
  return { ...compile('components/OrdersScreen.tsx', load, { setInterval: runtime.setInterval ?? (() => 0), clearInterval: runtime.clearInterval ?? (() => {}) }),
    ...compile('components/ClientOrderViews.tsx', load), ...compile('components/ClientReviewForm.tsx', load) };
}
class ApiError extends Error { constructor(status, message = 'API') { super(message); this.status = status; } }
const ui = moduleFor({ ApiError });
const originalTimezone = process.env.TZ;
process.env.TZ = 'America/Toronto';
const startedAt = '2026-10-03T12:00:00';
const startedOrder = { ...base, status: 'in_progress', in_progress_at: startedAt };
assert.equal(ui.elapsedLabel(startedOrder, Date.parse(`${startedAt}Z`)), t('orders.preparingSinceSeconds', { count: 0 }));
assert.equal(ui.elapsedLabel(startedOrder, Date.parse(`${startedAt}Z`) + 5 * 60000), t('orders.preparingSince', { count: 5 }));
assert.equal(ui.elapsedLabel(startedOrder, Date.parse(`${startedAt}Z`) + 65 * 60000), t('orders.preparingSinceHours', { hours: 1, minutes: 5 }));
assert.equal(ui.elapsedLabel({ ...startedOrder, in_progress_at: '2026-10-03T12:03:00' }, Date.parse(`${startedAt}Z`) + 5 * 60000),
  t('orders.preparingSince', { count: 2 }));
assert.ok(!ui.elapsedLabel({ ...startedOrder, status: 'ready' }, Date.parse(`${startedAt}Z`) + 5 * 60000).includes('préparation'));
const placedAt = Date.parse(`${startedAt}Z`);
const recentOrder = { ...base, created_at: startedAt };
assert.equal(ui.elapsedLabel(recentOrder, placedAt + 30_000), 'il y a 30 s');
assert.equal(ui.elapsedLabel(recentOrder, placedAt + 5 * 60_000), 'il y a 5 min');
assert.equal(ui.elapsedLabel(recentOrder, placedAt + (3 * 60 + 20) * 60_000), 'il y a 3 h 20 min');
assert.equal(ui.elapsedLabel(recentOrder, placedAt + (23 * 60 + 59) * 60_000), 'il y a 23 h 59 min');
assert.equal(ui.elapsedLabel(recentOrder, placedAt + 24 * 60 * 60_000), 'samedi 3 octobre 2026 à 12:00');
assert.equal(ui.elapsedLabel(recentOrder, placedAt + 60_000, true), 'samedi 3 octobre 2026 à 12:00');
const localDate = 'samedi 3 octobre 2026 à 17:36';
const localOrder = { ...base, status: 'picked_up', created_at: '2026-10-03T17:36:00' };
assert.equal(ui.elapsedLabel(localOrder, Date.parse('2026-10-05T17:36:00Z'), true), localDate);
assert.equal(ui.elapsedLabel({ ...localOrder, created_at: '2026-10-03T17:36:00+00:00' }, Date.parse('2026-10-05T17:36:00Z'), true), localDate);
assert.ok(nodes(ui.OrderList({ orders: [localOrder], history: true, onOpen() {} })).some((n) => n.props.children === localDate));
assert.ok(nodes(ui.OrderDetail({ order: localOrder, scope: 'cook', busy: false, onTransition() {}, onReview() {} }))
  .some((n) => n.props.children === localDate));
let readyOrderOpened;
const readyOrderCard = nodes(ui.OrderList({ orders: [{ ...base, status: 'ready' }], onOpen: (order) => { readyOrderOpened = order.id; } }));
const pickupValidationLink = readyOrderCard.find((n) => n.type === 'Pressable'
  && n.props.accessibilityLabel === t('orders.openPickupValidation'));
assert.ok(pickupValidationLink, 'ready merchant order exposes an explicit pickup validation action');
pickupValidationLink.props.onPress();
assert.equal(readyOrderOpened, base.id, 'pickup validation action opens the existing code entry detail');
let submittedPickupCode;
const readyMerchantDetail = nodes(ui.OrderDetail({ order: { ...base, status: 'ready' }, scope: 'cook', busy: false,
  onTransition() {}, onReview() {}, pickupCodeInput: '789795', onConfirmPickup: (code) => { submittedPickupCode = code; } }));
const pickupInput = readyMerchantDetail.find((n) => n.type === 'TextInput' && n.props.accessibilityLabel === t('orders.pickupCodeInput'));
assert.equal(pickupInput.props.value, '789795');
const validatePickupButton = readyMerchantDetail.find((n) => n.type === 'Pressable'
  && nodes(n).some((child) => child.props.children === t('orders.validatePickup')));
assert.ok(validatePickupButton, 'merchant ready detail exposes code validation');
validatePickupButton.props.onPress();
assert.equal(submittedPickupCode, '789795', 'merchant validation submits the entered code');
if (originalTimezone === undefined) delete process.env.TZ;
else process.env.TZ = originalTimezone;
for (const scope of ['customer', 'cook']) {
  let opened;
  let actionOrder;
  const list = nodes(ui.OrderList({ orders: [{ ...base, status: 'ordered' }], onOpen: (order) => { opened = order.id; }, onAction: (order) => { actionOrder = order.id; } }));
  assert.equal(list.filter((n) => n.type === 'Pressable').length, 1);
  list.find((n) => n.type === 'Pressable').props.onPress();
  assert.equal(opened, base.id);
  assert.ok(list.some((n) => n.props.children === '#KORDE'));
  assert.ok(list.some((n) => n.props.children === '2 articles · 3 unités'));
  list.find((n) => n.type === 'PrimaryButton').props.onPress();
  assert.equal(actionOrder, base.id);
  const detail = nodes(ui.OrderDetail({ order: base, scope, busy: false, onTransition() {}, onReview() {} }));
  for (const text of ['Poulet yassa', 'Jus bissap', '2 × 4500 XOF', '1 × 1000 XOF', '10000 XOF']) {
    assert.ok(detail.some((n) => n.props.children === text), text);
  }
  assert.equal(detail.filter((n) => n.type === 'PrimaryButton').length, scope === 'cook' ? 1 : 0);
}
for (const status of ['ordered', 'in_progress', 'ready', 'picked_up', 'completed', 'confirmed', 'cancelled']) {
  const detail = nodes(ui.OrderDetail({ order: { ...base, status }, scope: 'cook', busy: true, pickupCodeInput: '', onTransition() {}, onReview() {} }));
  assert.ok(detail.some((n) => n.props.children === t(workflow.orderStatusKeys[status])));
  const buttons = detail.filter((n) => n.type === 'PrimaryButton');
  assert.equal(buttons.length, ['ordered', 'in_progress'].includes(status) ? 1 : 0);
  assert.ok(buttons.every((n) => n.props.disabled && n.props.loading));
}
assert.equal(workflow.orderLines({ ...base, items: [], availability_id: 'legacy', quantity: 1, unit_price: '10000', dish_name: 'Legacy' }).length, 1);
assert.equal(workflow.isActiveOrder('completed'), false);
assert.equal(workflow.isActiveOrder('ready'), true);

// Presentation client dediee : une carte par commande, jamais une carte par ligne.
const clientList = nodes(ui.ClientOrderList({ orders: [base], history: false, onOpen() {} }));
assert.equal(clientList.filter((n) => n.type === 'Pressable').length, 1);
assert.ok(clientList.some((n) => n.props.children === t('clientOrders.viewDetails')));
assert.ok(!clientList.some((n) => ['Poulet yassa', 'Jus bissap'].includes(n.props.children)));
for (const status of ['ordered', 'in_progress', 'ready', 'picked_up', 'completed', 'cancelled', 'confirmed']) {
  const order = { ...base, status };
  let selectedRating = 0;
  let pickupCodeRequested = false;
  const detail = nodes(ui.ClientOrderDetail({ order, onReview(_order, rating) { selectedRating = rating ?? 0; },
    onRequestPickupCode() { pickupCodeRequested = true; } }));
  for (const text of ['Poulet yassa', 'Jus bissap', '2 × 4500 XOF', '1 × 1000 XOF', '9000 XOF', '1000 XOF', '10000 XOF']) {
    assert.ok(detail.some((n) => n.props.children === text), `${status}: ${text}`);
  }
  assert.ok(!detail.some((n) => n.props.children === base.id || n.props.children === status));
  assert.ok(detail.some((n) => n.props.children === t('clientOrders.contactMerchant')));
  assert.ok(detail.some((n) => n.props.children === t('clientOrderMessages.contactHint')));
  const helpToggle = detail.find((n) => n.type === 'Pressable' && n.props.accessibilityState?.expanded === false);
  assert.ok(helpToggle, `${status}: help accordion closed by default`);
  assert.equal(detail.filter((n) => n.props.children === t('clientOrders.helpTitle')).length, 1, `${status}: one help section`);
  assert.equal(detail.some((n) => n.props.children === t('clientExperience.helpIntro')), false, `${status}: help body is not mounted while closed`);
  const expandedDetail = nodes(ui.ClientOrderDetail({ order, helpExpanded: true, onToggleHelp() {}, onReview() {} }));
  assert.ok(expandedDetail.find((n) => n.type === 'Pressable' && n.props.accessibilityState?.expanded === true));
  const progress = nodes(ui.ClientOrderProgress({ order })).filter((n) => n.props.accessible);
  assert.equal(progress.length, status === 'cancelled' ? 0 : 3);
  assert.equal(progress.filter((n) => n.props.accessibilityLabel.includes(t('clientOrders.stepCurrent'))).length,
    ['ordered', 'in_progress', 'ready', 'confirmed'].includes(status) ? 1 : 0);
  assert.ok(progress.every((n) => !n.props.accessibilityLabel.includes(t('orders.status.picked_up'))));
  const buttons = detail.filter((n) => n.type === 'Pressable');
  const reviewButtons = buttons.filter((n) => nodes(n).some((child) => child.props.children === t('reviews.leaveReview')));
  assert.equal(reviewButtons.length, ['picked_up', 'completed'].includes(status) ? 1 : 0);
  const pickupButtons = buttons.filter((n) => nodes(n).some((child) => child.props.children === t('clientExperience.pickupFuture')));
  assert.equal(pickupButtons.length, 0);
  if (status === 'ready') {
    assert.ok(detail.some((n) => n.props.children === t('clientOrders.readyStatusTitle')));
    assert.equal(detail.filter((n) => n.props.children === 'À récupérer chez Commerce.').length, 1);
    assert.ok(detail.some((n) => n.props.children === t('clientOrders.readyTitle')));
    const pickupAction = detail.find((n) => n.type === 'Pressable' && nodes(n).some((child) => child.props.children === t('clientOrders.showPickupCode')));
    assert.ok(pickupAction, 'ready client sees pickup-code action');
    assert.equal(pickupAction.props.accessibilityLabel, t('clientOrders.showPickupCode'));
    assert.ok(detail.indexOf(pickupAction) < detail.findIndex((n) => n.props.children === t('clientOrders.summary')),
      'ready pickup action appears before order details');
    pickupAction.props.onPress();
    assert.equal(pickupCodeRequested, true);
    assert.equal(detail.filter((n) => n.props.children === t('clientOrders.readyStatusTitle')).length, 1);
    assert.equal(detail.filter((n) => n.props.children === t('clientOrders.pickupOnSite')).length, 0);
    const codeDetail = nodes(ui.ClientOrderDetail({ order: { ...order, pickup_code: '083104' }, pickupCodeVisible: true,
      onRequestPickupCode() {}, onReview() {} }));
    assert.ok(codeDetail.some((n) => n.props.children === '083104'), 'requested pickup code is visible');
    const noHandlerDetail = nodes(ui.ClientOrderDetail({ order, onReview() {} }));
    const disabledPickupAction = noHandlerDetail.find((n) => n.type === 'Pressable' && nodes(n).some((child) => child.props.children === t('clientOrders.showPickupCode')));
    assert.ok(disabledPickupAction, 'ready CTA remains visibly labeled without a handler');
    assert.equal(disabledPickupAction.props.accessibilityState.disabled, true);
  }
  if (status === 'picked_up' || status === 'completed') {
    assert.ok(detail.some((n) => n.props.children === t('clientOrders.pickedUpTitle')));
    assert.ok(detail.some((n) => n.props.children === t('clientOrders.pickedUpBody')));
    assert.ok(detail.some((n) => n.props.children === t('reviews.title') || n.props.children === t('reviews.thanks')));
    if (!order.review_id) assert.ok(detail.some((n) => n.props.children === t('reviews.invitationBody')));
    const reviewStars = detail.filter((n) => n.type === 'Pressable' && n.props.accessibilityRole === 'radio');
    assert.equal(reviewStars.length, order.review_id ? 0 : 5);
    if (reviewStars.length) {
      reviewStars[4].props.onPress();
      assert.equal(selectedRating, 5);
    }
    const progressIndex = detail.findIndex((n) => n.props.children === t('clientOrders.progress'));
    const reviewIndex = detail.findIndex((n) => n.props.children === t('reviews.title') || n.props.children === t('reviews.thanks'));
    const contactIndex = detail.findIndex((n) => n.props.children === t('clientOrders.contactMerchant'));
    const helpIndex = detail.findIndex((n) => n.props.children === t('clientOrders.helpTitle'));
    assert.ok(progressIndex > -1 && contactIndex > progressIndex && reviewIndex > contactIndex && helpIndex > reviewIndex);
  }
}
let openedMessagesFor;
const messageOrder = { ...base, status: 'picked_up' };
const contactDetail = nodes(ui.ClientOrderDetail({ order: messageOrder, onReview() {},
  onContactMerchant(order) { openedMessagesFor = order.id; } }));
contactDetail.find((node) => node.type === 'Pressable' && nodes(node).some((child) => child.props.children === t('clientOrders.contactMerchant'))).props.onPress();
assert.equal(openedMessagesFor, messageOrder.id, 'contact opens the conversation for this order');
let sentMessage = false;
const conversation = nodes(ui.ClientOrdersView({ orders: [], selected: messageOrder, history: true, loading: false, error: null,
  onOpen() {}, onBack() {}, onHistory() {}, onRefresh() {}, onReview() {}, messagesVisible: true, currentUserId: 'customer-a',
  messages: [{ id: 'message-a', order_id: messageOrder.id, sender_id: 'merchant-a', sender_role: 'merchant', body: 'Votre commande est prête.', created_at: startedAt }],
  onSendMessage() { sentMessage = true; } }));
assert.ok(conversation.some((node) => node.props.children === 'Votre commande est prête.'));
const messageInput = conversation.find((node) => node.props.accessibilityLabel === t('clientOrderMessages.input'));
assert.ok(messageInput);
assert.equal(messageInput.props.maxLength, 230, 'mobile chat limits both participants to 230 characters');
conversation.find((node) => node.type === 'Pressable' && nodes(node).some((child) => child.props.children === t('clientOrderMessages.send'))).props.onPress();
assert.equal(sentMessage, true, 'the chat composer invokes send');
const legacyDetail = nodes(ui.ClientOrderDetail({ order: { ...base, status: 'completed', items: [],
  availability_id: 'legacy', quantity: 1, unit_price: '10000', dish_name: 'Ancien plat' }, onReview() {} }));
assert.ok(legacyDetail.some((n) => n.props.children === 'Ancien plat'));
const reviewedNoComment = nodes(ui.ClientOrderDetail({ order: { ...base, status: 'picked_up', review_id: 'review-empty', review_rating: 5, review_comment: null }, onReview() {} }));
assert.ok(reviewedNoComment.some((n) => n.props.children === t('reviews.thanks')));
assert.ok(reviewedNoComment.some((n) => n.props.children === '★ ★ ★ ★ ★'));
assert.ok(!reviewedNoComment.some((n) => n.props.children === 'Très bon'));
assert.equal(reviewedNoComment.filter((n) => n.type === 'Pressable' && nodes(n).some((child) => child.props.children === t('reviews.leaveReview'))).length, 0);
const reviewedDetail = nodes(ui.ClientOrderDetail({ order: { ...base, status: 'picked_up', review_id: 'review-a', review_rating: 4, review_comment: 'Excellent accueil' }, onReview() {} }));
assert.ok(reviewedDetail.some((n) => n.props.children === t('reviews.thanks')));
assert.ok(reviewedDetail.some((n) => n.props.children === '★ ★ ★ ★ ☆'));
assert.ok(reviewedDetail.some((n) => n.props.children === 'Excellent accueil'));
assert.ok(reviewedDetail.some((n) => n.props.children === t('reviews.published')));
assert.ok(reviewedDetail.some((n) => n.props.children === t('reviews.publishedBody')));
assert.equal(reviewedDetail.filter((n) => n.type === 'Pressable' && nodes(n).some((child) => child.props.children === t('reviews.leaveReview'))).length, 0);
let retried = false;
const errorView = nodes(ui.ClientOrdersView({ orders: [], selected: null, history: false, loading: false,
  error: t('orders.loadError'), onRefresh() { retried = true; } }));
errorView.find((n) => n.type === 'Pressable' && nodes(n).some((child) => child.props.children === t('clientOrders.retry'))).props.onPress();
assert.ok(retried);
for (const history of [false, true]) {
  const emptyView = nodes(ui.ClientOrderList({ orders: [], history, onOpen() {} }));
  assert.ok(emptyView.some((n) => n.props.children === t(history ? 'clientOrders.emptyHistoryBody' : 'clientOrders.emptyBody')));
}
const activeOrders = ['ordered', 'in_progress', 'ready', 'confirmed'];
const historyOrders = ['picked_up', 'completed', 'cancelled'];
assert.ok(activeOrders.every((status) => workflow.isActiveOrder(status)));
assert.ok(historyOrders.every((status) => !workflow.isActiveOrder(status)));

// Un ancien formulaire ne doit jamais s'afficher sur une commande non eligible.
for (const status of [...activeOrders, ...historyOrders]) {
  let formRendered = false;
  nodes(ui.ClientOrderDetail({ order: { ...base, status }, onReview() {}, renderReview() {
    formRendered = true; return React.createElement('ReviewForm');
  } }));
  assert.equal(formRendered, ['picked_up', 'completed'].includes(status), status);
}
let duplicateForm = false;
nodes(ui.ClientOrderDetail({ order: { ...base, status: 'picked_up', review_id: 'published' }, onReview() {},
  renderReview() { duplicateForm = true; return React.createElement('ReviewForm'); } }));
assert.equal(duplicateForm, false);

let rating = 0, comment = '', submitted = 0;
function reviewForm(busy = false) {
  return nodes(ui.ClientReviewForm({ rating, comment, busy, onRating(value) { rating = value; },
    onComment(value) { comment = value; }, onSubmit() { submitted++; }, onCancel() {} }));
}
assert.equal(reviewForm().find((node) => node.type === 'PrimaryButton').props.disabled, true);
assert.ok(nodes(ui.ClientReviewForm({ rating: 2, comment: 'Saisie conservée', busy: false, error: t('reviews.submitError'),
  onRating() {}, onComment() {}, onSubmit() {}, onCancel() {} })).some((node) => node.props.children === t('reviews.submitError')));
for (const value of [1, 3, 5]) {
  reviewForm().filter((node) => node.props.accessibilityRole === 'radio')[value - 1].props.onPress();
  assert.equal(rating, value);
  assert.equal(reviewForm().filter((node) => node.props.children === '★').length, value);
  assert.equal(reviewForm().find((node) => node.type === 'PrimaryButton').props.disabled, false);
}
reviewForm().find((node) => node.type === 'TextInput').props.onChangeText('Accueil chaleureux');
assert.equal(reviewForm().find((node) => node.type === 'TextInput').props.value, 'Accueil chaleureux');
assert.ok(reviewForm(true).filter((node) => node.type === 'Pressable').every((node) => node.props.disabled));
reviewForm().find((node) => node.type === 'PrimaryButton').props.onPress();
assert.equal(submitted, 1);

// Petit harnais de hooks, comme les tests UI existants sans renderer natif.
function renderer(api, scope, options = {}) {
  const slots = []; let index = 0; let effects = [];
  const timers = new Map(); let timerId = 0;
  const audio = { plays: 0, vibrations: 0 };
  const appState = { currentState: 'active', addEventListener: () => ({ remove() {} }) };
  const hooks = {
    useState(initial) { const i = index++; if (!(i in slots)) slots[i] = typeof initial === 'function' ? initial() : initial; return [slots[i], (v) => { slots[i] = typeof v === 'function' ? v(slots[i]) : v; }]; },
    useRef(initial) { const i = index++; if (!(i in slots)) slots[i] = { current: initial }; return slots[i]; },
    useEffect(fn, deps) {
      const i = index++; const old = slots[i];
      if (!old || deps.some((v, j) => !Object.is(v, old.deps[j]))) {
        old?.cleanup?.(); slots[i] = { deps }; effects.push(() => { slots[i].cleanup = fn(); });
      }
    },
  };
  const { OrdersScreen, useMerchantOrdersMonitor } = moduleFor(api, hooks, { appState,
    get audioPlays() { return audio.plays; }, set audioPlays(value) { audio.plays = value; },
    get vibrations() { return audio.vibrations; }, set vibrations(value) { audio.vibrations = value; },
    setInterval(fn, ms) { assert.ok([5000, 15000, 30000].includes(ms)); timers.set(++timerId, { fn, ms }); return timerId; },
    clearInterval(id) { timers.delete(id); },
  });
  let feed;
  function render() {
    index = 0;
    feed = options.monitor ? useMerchantOrdersMonitor('merchant-a') : undefined;
    const tree = nodes(OrdersScreen({ scope, refreshKey: 0, onReview() {}, visible: options.visible ?? true,
      merchantFeed: feed, reviewResult: options.reviewResult }));
    const pending = effects; effects = []; pending.forEach((f) => f()); return tree;
  }
  async function settle() { let tree; for (let i = 0; i < 5; i++) { await new Promise(setImmediate); tree = render(); } return tree; }
  return { render, settle, timers, appState, audio, get feed() { return feed; }, tick(ms) { [...timers.values()].filter((timer) => ms === undefined || timer.ms === ms).forEach(({ fn }) => fn()); },
    unmount() { slots.forEach((slot) => slot?.cleanup?.()); },
  };
}
async function main() {
  // Executer le vrai handler avec une API isolee : note requise, commentaire facultatif, double tap.
  const appSource = ts.createSourceFile('App.tsx', fs.readFileSync(`${__dirname}/../App.tsx`, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  let submitSource;
  function findSubmit(node) {
    if (ts.isFunctionDeclaration(node) && node.name?.text === 'submitReview') submitSource = node.getText(appSource);
    ts.forEachChild(node, findSubmit);
  }
  findSubmit(appSource);
  assert.ok(submitSource);
  let finishReview; const posts = [];
  const submission = { reviewOrder: { ...base, status: 'ready' }, reviewRating: 5, reviewComment: '', reviewLock: { current: false },
    me: { cook_profile: null }, ApiError,
    setReviewBusy() {}, setReviewOrder(value) { submission.reviewOrder = value; },
    setReviewRating(value) { submission.reviewRating = value; }, setReviewComment(value) { submission.reviewComment = value; },
    setReviewError(value) { submission.reviewError = value; }, setReviewResult(value) { submission.reviewResult = value; },
    t,
    createReview: async (payload) => { posts.push(payload); await new Promise((resolve) => { finishReview = resolve; });
      return { id: 'review-created', rating: payload.rating, comment: payload.comment ?? null }; },
  };
  vm.runInNewContext(ts.transpileModule(submitSource, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText, submission);
  await submission.submitReview(); assert.equal(posts.length, 0);
  submission.reviewOrder = { ...base, status: 'picked_up' };
  submission.reviewRating = 0;
  await submission.submitReview(); assert.equal(posts.length, 0);
  submission.reviewRating = 5;
  submission.reviewComment = 'Commentaire exact';
  await submission.submitReview('different-order'); assert.equal(posts.length, 0, 'Le formulaire doit correspondre à la commande affichée');
  const posting = submission.submitReview(base.id);
  await submission.submitReview(base.id); assert.equal(posts.length, 1);
  assert.equal(posts[0].order_id, base.id); assert.equal(posts[0].rating, 5); assert.equal(posts[0].comment, 'Commentaire exact');
  finishReview(); await posting;
  assert.equal(submission.reviewOrder, null); assert.equal(submission.reviewRating, 0); assert.equal(submission.reviewComment, '');
  assert.equal(submission.reviewResult.orderId, base.id);
  submission.reviewOrder = { ...base, status: 'picked_up' };
  submission.reviewRating = 2;
  submission.reviewComment = 'Ne doit pas disparaître';
  submission.createReview = async () => { throw new ApiError(503); };
  await submission.submitReview(base.id);
  assert.equal(submission.reviewOrder.id, base.id);
  assert.equal(submission.reviewRating, 2);
  assert.equal(submission.reviewComment, 'Ne doit pas disparaître');
  assert.equal(submission.reviewError, t('reviews.submitError'));
  submission.me.cook_profile = { id: 'merchant-a' };
  submission.reviewOrder = { ...submission.reviewOrder, cook_id: 'merchant-a' };
  submission.createReview = async () => { throw new ApiError(403, 'Vous ne pouvez pas noter cette commande.'); };
  await submission.submitReview(base.id);
  assert.equal(submission.reviewError, t('reviews.orderOwnershipError'), 'Le 403 de propriété ne doit pas être présenté comme une auto-évaluation');
  submission.createReview = async () => { throw new ApiError(403, 'Vous ne pouvez pas noter votre propre plat.'); };
  await submission.submitReview(base.id);
  assert.equal(submission.reviewError, t('reviews.ownOrderError'));
  assert.equal(submission.reviewComment, 'Ne doit pas disparaître');

  let rows = [base], pollReads = 0;
  const live = renderer({ ApiError, getOrders: async () => { pollReads++; return rows; } }, 'cook', {
    visible: false, monitor: true,
  });
  live.render(); await live.settle();
  assert.equal(live.feed.arrivals, 0, 'Le premier chargement est silencieux');
  assert.equal(live.timers.size, 1, 'Une seule surveillance meme si OrdersScreen est monte');
  assert.equal(live.audio.plays, 1, 'Le lecteur est initialise sans jouer');
  live.tick(); await live.settle();
  rows = [{ ...base, status: 'in_progress' }];
  live.tick(); await live.settle();
  assert.equal(live.feed.arrivals, 0, 'Une transition ne cree pas une alerte');
  rows = [...rows, { ...base, id: 'new-order' }, { ...base, id: 'second-new-order' },
    { ...base, id: 'old-history', status: 'completed' }];
  live.tick(); await live.settle();
  assert.equal(live.feed.arrivals, 2, 'Deux commandes entrantes detectees depuis Commerce');
  assert.equal(live.audio.vibrations, 1, 'Une seule vibration pour le batch');
  assert.equal(live.audio.plays, 2, 'Une seule alerte audio pour le batch');
  live.tick(); await live.settle();
  assert.equal(live.feed.arrivals, 2, 'Aucune alerte repetee');
  assert.equal(live.audio.plays, 2, 'Aucun son repete');
  live.appState.currentState = 'background';
  const beforeBackground = pollReads;
  live.tick(); await live.settle();
  assert.equal(pollReads, beforeBackground);
  live.unmount(); assert.equal(live.timers.size, 0);

  const queue = renderer({ ApiError, getOrders: async () => rows }, 'cook', { monitor: true });
  queue.render(); await queue.settle();
  rows = [...rows, { ...base, id: 'another-order' }];
  queue.tick();
  let queueTree = await queue.settle();
  assert.ok(queueTree.some((node) => node.props.children === t('orders.arrivalOne')));
  assert.equal([...queue.timers.values()].filter((timer) => timer.ms === 15000).length, 1, 'Un seul polling dans le scope marchand');
  assert.equal([...queue.timers.values()].filter((timer) => timer.ms === 30000).length, 1, 'Horloge locale de preparation');
  queueTree.find((node) => node.props.accessibilityRole === 'tab' && nodes(node).some((child) => child.props.children === t('orders.history'))).props.onPress();
  queueTree = await queue.settle();
  assert.equal(queue.timers.size, 2, 'La surveillance et l horloge restent actives dans historique');
  assert.ok(!queueTree.some((node) => node.props.children === t('orders.arrivalOne')));
  queue.unmount();

  const reviewedOrder = { ...base, status: 'picked_up', review_id: null };
  const reviewOptions = { reviewResult: null };
  const reviewedScreen = renderer({ ApiError, getOrders: async () => [reviewedOrder], getOrder: async () => reviewedOrder }, 'customer', reviewOptions);
  reviewedScreen.render();
  let reviewedTree = await reviewedScreen.settle();
  reviewedTree.find((node) => node.props.accessibilityRole === 'tab' && node.props.accessibilityState.selected === false).props.onPress();
  reviewedTree = await reviewedScreen.settle();
  reviewedTree.find((node) => node.props.accessibilityLabel?.startsWith(t('clientOrders.viewDetails'))).props.onPress();
  reviewedTree = await reviewedScreen.settle();
  reviewOptions.reviewResult = { orderId: base.id, id: 'review-created', rating: 2, comment: 'Commentaire exact' };
  reviewedTree = await reviewedScreen.settle();
  assert.ok(reviewedTree.some((node) => node.props.children === t('reviews.thanks')));
  assert.ok(reviewedTree.some((node) => node.props.children === 'Commentaire exact'));
  assert.ok(!reviewedTree.some((node) => node.props.children === t('reviews.leaveReview')));
  reviewedScreen.unmount();

  let release; let calls = 0;
  const gate = workflow.createOrderActionGate();
  const first = gate(base, async () => { calls++; await new Promise((resolve) => { release = resolve; }); });
  assert.equal(await gate(base, async () => { calls++; }), false);
  assert.equal(calls, 1); release(); await first;
  await assert.rejects(gate(base, async () => { throw new Error('test'); }));
  assert.equal(await gate(base, async () => {}), true);
  assert.equal(await gate({ ...base, status: 'ready' }, async () => { throw new Error('pickup forbidden'); }), false);

  for (const scope of ['customer', 'cook']) {
    let stored = { ...base }; const changes = []; let reads = 0;
    const api = { ApiError, getOrders: async (actual) => { assert.equal(actual, scope); return [stored]; },
      getOrder: async (id) => { assert.equal(id, base.id); reads++; return stored; },
      updateOrderStatus: async (id, status) => { assert.equal(id, base.id); changes.push(status); stored = { ...stored, status }; return stored; },
      confirmPickup: async (id) => { assert.equal(id, base.id); changes.push('picked_up'); stored = { ...stored, status: 'picked_up', picked_up_at: '2026-09-25T13:00:00Z' }; return stored; } };
    const app = renderer(api, scope);
    assert.ok(app.render().some((n) => n.type === 'ActivityIndicator'));
    let tree = await app.settle();
    tree.find((n) => n.type === 'Pressable' && n.props.accessibilityLabel?.startsWith(
      scope === 'customer' ? t('clientOrders.viewDetails') : t('orders.open'))).props.onPress();
    tree = await app.settle();
    assert.ok(tree.some((n) => n.props.children === 'Poulet yassa'));
    if (scope === 'cook') {
      let button = tree.find((n) => n.props.label === t('orders.startPreparation'));
      button.props.onPress(); button.props.onPress();
      tree = await app.settle();
      assert.deepEqual(changes, ['in_progress']);
      tree.find((n) => n.props.label === t('orders.markReady')).props.onPress();
      tree = await app.settle();
      assert.deepEqual(changes, ['in_progress', 'ready']);
      assert.equal(reads, 3);
      assert.ok(tree.some((n) => n.props.children === t('orders.awaitingPickup')));
      assert.equal(tree.filter((n) => n.type === 'PrimaryButton').length, 0);
    } else {
      stored = { ...stored, status: 'ready' };
      tree.find((n) => n.type === 'Pressable' && nodes(n).some((child) => child.props.children === t('orders.refresh'))).props.onPress();
      tree = await app.settle();
      assert.ok(tree.some((n) => n.props.children === t('clientOrders.readyTitle')));
      assert.ok(tree.some((n) => n.type === 'Pressable' && nodes(n).some((child) => child.props.children === t('clientOrders.showPickupCode'))));
      assert.ok(!tree.some((n) => n.props.children === t('clientExperience.pickupFuture')));
      assert.deepEqual(changes, []);
    }
  }
  let pickupOrder = { ...base, status: 'ready', pickup_code: '938096' };
  const pickupScreen = renderer({ ApiError, getOrders: async () => [pickupOrder], getOrder: async () => pickupOrder,
    requestPickupCode: async () => pickupOrder }, 'customer');
  pickupScreen.render();
  let pickupTree = await pickupScreen.settle();
  pickupTree.find((node) => node.type === 'Pressable' && node.props.accessibilityLabel?.startsWith(t('clientOrders.viewDetails'))).props.onPress();
  pickupTree = await pickupScreen.settle();
  pickupTree.find((node) => node.type === 'Pressable' && nodes(node).some((child) => child.props.children === t('clientOrders.showPickupCode'))).props.onPress();
  pickupTree = await pickupScreen.settle();
  assert.ok(pickupTree.some((node) => node.props.children === '938096'), 'Le code doit apparaître avant validation commerçant');
  pickupOrder = { ...pickupOrder, status: 'picked_up', picked_up_at: '2026-10-11T21:30:00Z' };
  pickupScreen.tick(5000);
  pickupTree = await pickupScreen.settle();
  assert.ok(!pickupTree.some((node) => node.props.children === '938096'), 'Le code doit disparaître après confirmation serveur');
  assert.ok(pickupTree.some((node) => node.props.children === t('clientOrders.pickedUpTitle')));
  assert.ok(!pickupScreen.timers.size, 'Le polling du détail s’arrête après picked_up');
  pickupScreen.unmount();

  const failed = renderer({ ApiError, getOrders: async () => { throw new ApiError(503); } }, 'customer');
  failed.render();
  assert.ok((await failed.settle()).some((n) => n.props.children === t('orders.loadError')));
  const empty = renderer({ ApiError, getOrders: async () => [] }, 'customer'); empty.render();
  assert.ok((await empty.settle()).some((n) => n.props.children === t('clientOrders.emptyTitle')));
  let current = { ...base };
  const conflicted = renderer({ ApiError, getOrders: async () => [current], getOrder: async () => current,
    updateOrderStatus: async () => { current = { ...base, status: 'ready' }; throw new ApiError(409); } }, 'cook');
  conflicted.render();
  let tree = await conflicted.settle();
  tree.find((n) => n.props.accessibilityLabel === t('orders.open')).props.onPress();
  tree = await conflicted.settle();
  tree.find((n) => n.props.label === t('orders.startPreparation')).props.onPress();
  tree = await conflicted.settle();
  assert.ok(tree.some((n) => n.props.children === t('orders.conflictError')));
  assert.equal(tree.filter((n) => n.type === 'PrimaryButton').length, 0);
  tree.find((n) => n.type === 'Pressable' && nodes(n).some((child) => child.props.children === t('orders.refresh'))).props.onPress();
  tree = await conflicted.settle();
  assert.ok(tree.some((n) => n.props.children === t('orders.readyShort')));

  const requests = [];
  const realApi = compile('services/api.ts', (path) => {
    if (path === '../config') return { API_URL: 'https://example.invalid', isApiConfigured: () => true };
    if (path === '../discovery') return {};
    throw new Error(path);
  }, { fetch: async (url, options) => { requests.push({ url, ...options }); return { ok: true, status: 200, text: async () => JSON.stringify(base) }; } });
  realApi.setAccessToken('test-only');
  await realApi.getOrders('customer'); await realApi.getOrders('cook'); await realApi.getOrder(base.id); await realApi.requestPickupCode(base.id);
  await realApi.getOrderMessages(base.id); await realApi.sendOrderMessage(base.id, 'Bonjour commerce');
  await realApi.updateOrderStatus(base.id, 'in_progress'); await realApi.updateOrderStatus(base.id, 'ready');
  await realApi.confirmPickup(base.id, '123456');
  await realApi.createReview({ order_id: base.id, rating: 5, comment: '' });
  await realApi.createReview({ order_id: base.id, rating: 4, comment: 'Exactement saisi' });
  assert.equal(requests[0].url, 'https://example.invalid/api/v1/orders?scope=customer');
  assert.equal(requests[1].url, 'https://example.invalid/api/v1/orders?scope=cook');
  assert.equal(requests[2].url, 'https://example.invalid/api/v1/orders/order-a');
  assert.equal(requests[3].method, 'POST');
  assert.equal(requests[3].url, 'https://example.invalid/api/v1/orders/order-a/pickup/code');
  assert.equal(requests[4].method, 'GET');
  assert.equal(requests[4].url, 'https://example.invalid/api/v1/orders/order-a/messages');
  assert.equal(requests[5].method, 'POST');
  assert.equal(requests[5].url, 'https://example.invalid/api/v1/orders/order-a/messages');
  assert.deepEqual(JSON.parse(requests[5].body), { body: 'Bonjour commerce' });
  assert.ok(requests.slice(6, 8).every((r) => r.method === 'PATCH' && r.url.endsWith('/order-a/status')));
  assert.deepEqual(requests.slice(6, 8).map((r) => JSON.parse(r.body).status), ['in_progress', 'ready']);
  assert.equal(requests[8].method, 'POST');
  assert.equal(requests[8].url, 'https://example.invalid/api/v1/orders/order-a/pickup/confirm');
  assert.deepEqual(JSON.parse(requests[8].body), { pickup_code: '123456' });
  assert.equal(requests[9].url, 'https://example.invalid/api/v1/reviews');
  assert.deepEqual(JSON.parse(requests[9].body), { order_id: base.id, rating: 5 });
  assert.deepEqual(JSON.parse(requests[10].body), { order_id: base.id, rating: 4, comment: 'Exactement saisi' });
  assert.ok(requests.every((r) => r.headers.Authorization === 'Bearer test-only'));
  console.log('Orders client/merchant multi-item, transitions, double tap, legacy, i18n, loading/errors/empty: PASS');
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
