const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const React = require('react');
const fr = require('../locales/fr.json');
const es = require('../locales/es-CO.json');
const t = (key, params = {}) => {
  assert.equal(typeof fr[key], 'string', key);
  assert.equal(typeof es[key], 'string', key);
  return fr[key].replace(/\{(\w+)\}/g, (_, name) => params[name]);
};
let alert;
function load(file) {
  const exports = {};
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(`${__dirname}/${file}`, 'utf8'), {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS },
  }).outputText, { exports, require(path) {
    if (path === 'react') return { useEffect() {}, useRef(value) { return { current: value }; }, useState(value) { return [value, () => {}]; } };
    if (path === 'react/jsx-runtime') return require(path);
    if (path.includes('Ionicons')) return { default: 'Icon' };
    if (path === 'react-native') return { View: 'View', Text: 'Text', Image: 'Image', Pressable: 'Pressable', TextInput: 'TextInput',
      Alert: { alert(...args) { alert = args; } }, StyleSheet: { create: (s) => s }, useWindowDimensions: () => ({ width: 390 }),
      Animated: { View: 'AnimatedView', Value: class { interpolate() { return 0; } setValue() {} }, timing: () => ({ start() {}, stop() {} }) } };
    if (path === '../i18n') return { t };
    if (path === '../config') return { mediaUrl: String };
    if (path === '../client-content') return load('client-content.ts');
    if (path === '../language') return { ACTIVE_LOCALE: 'fr' };
    if (path === './language') return { ACTIVE_LOCALE: 'fr' };
    if (path === './market' || path === '../market') return { ACTIVE_MARKET: { currency: 'XOF', measurementSystem: 'metric', timezone: 'Africa/Dakar' }, ACTIVE_MARKET_TIMEZONE: 'Africa/Dakar', resolveTimezone: (business, market) => business || market || 'UTC' };
    if (path === '../format') return { formatTime: String, formatMoney: (amount, currency) => `${amount} ${currency}`, formatDistance: String,
      formatRating: (value) => Number(value).toFixed(1).replace('.', ','), formatReviewDate: () => '3 octobre 2026' };
    if (path === '../hooks/useReducedMotion') return { useReducedMotion: () => true };
    if (path === './PortionIndicator') return { PortionIndicator: 'PortionIndicator' };
    if (path === '../components/BusinessDiscoveryCard') return load('components/BusinessDiscoveryCard.tsx');
    if (path === '../theme/layout') return { breakpoints: { compactPhone: 320 }, controlSizes: { minimumTouch: 44 }, iconSizes: { compact: 14, large: 24 } };
    if (path === '../order-actions') return load('order-actions.ts');
    if (path === '../payment-flow') return load('payment-flow.ts');
    if (path === '../payment-ui-state') return load('payment-ui-state.ts');
    if (path === '../orders-workflow') return load('orders-workflow.ts');
    if (path === './PrimaryButton') return { PrimaryButton: 'PrimaryButton' };
    if (path === './BrandWordmark') return load('components/BrandWordmark.tsx');
    if (path === './OrderResolutionRequestCard') return { OrderResolutionRequestCard: 'OrderResolutionRequestCard' };
    if (path === './PaymentActions') return load('components/PaymentActions.tsx');
    if (path.startsWith('../theme/')) return { colors: {}, fonts: {}, spacing: {}, radius: {}, fontSizes: {}, lineHeights: {} };
    throw new Error(path);
  } });
  return exports;
}
function nodes(element) {
  if (!React.isValidElement(element)) return [];
  if (typeof element.type === 'function') return nodes(element.type(element.props));
  return [element, ...React.Children.toArray(element.props.children).flatMap(nodes)];
}
const includes = (tree, text) => tree.some((node) => node.props.children === text);
const visibleText = (tree) => tree.filter((node) => node.type === 'Text').map((node) =>
  React.Children.toArray(node.props.children).filter((part) => typeof part === 'string' || typeof part === 'number').join('')).join('|');
const homeSource = fs.readFileSync(`${__dirname}/../App.tsx`, 'utf8');
assert.ok(homeSource.includes('home.filter.nearby'));
assert.ok(homeSource.includes('home.filter.fresh'));
assert.ok(homeSource.includes('home.filter.new'));
assert.ok(!homeSource.includes('home.filter.scarce'));
const dish = { dish_id: 'dish', availability_id: null, name: 'Poulet yassa', description: 'Spécialité locale', price: '4500', currency: 'XOF', available_date: null, remaining_portions: null, photo_url: null, start_time: null, end_time: null };
const profile = { cook_id: 'commerce', display_name: 'Chez Awa', bio: null, profile_photo_url: null, rating_average: null, rating_count: 0, is_open: true, available_dishes: [dish], recent_reviews: [] };
const { menuArticle } = load('client-menu.ts');
const { clientDisplayName } = load('client-content.ts');
const { groupDiscoverItemsByBusiness } = load('client-content.ts');
assert.equal(clientDisplayName('Restaurant DEV Sénégal'), 'Restaurant Sénégal');
const discoverRows = [
  { cook_id: 'commerce-a', dish_id: 'dish-a', cook_display_name: 'Restaurant A', dish_name: 'Poulet yassa', profile_photo_url: null, distance_km: 0.4, is_open: true },
  { cook_id: 'commerce-b', dish_id: 'dish-b', cook_display_name: 'Boulangerie B', dish_name: 'Pain', profile_photo_url: null, distance_km: 0.8, is_open: false },
  { cook_id: 'commerce-a', dish_id: 'dish-c', cook_display_name: 'Restaurant A', dish_name: 'Jus bissap', profile_photo_url: null, distance_km: 0.4, is_open: true },
];
const businessGroups = groupDiscoverItemsByBusiness(discoverRows);
assert.equal(JSON.stringify(businessGroups.map((group) => group.map((row) => row.cook_id))), '[ ["commerce-a","commerce-a"],["commerce-b"] ]'.replaceAll(' ', ''));
let openedBusiness = false;
const { BusinessDiscoveryCard } = load('components/BusinessDiscoveryCard.tsx');
const businessCard = nodes(BusinessDiscoveryCard({ items: businessGroups[0], onPress: () => { openedBusiness = true; } }));
assert.ok(includes(businessCard, 'Restaurant A'));
assert.ok(includes(businessCard, t('clientExperience.openMenu')));
assert.ok(!visibleText(businessCard).includes('articles disponibles'));
businessCard.find((node) => node.type === 'Pressable').props.onPress();
assert.equal(openedBusiness, true);
const article = menuArticle(profile, 'dish');
assert.equal(article.available_date, null);
assert.equal(article.availability_id, null);
assert.equal(article.remaining_portions, null);
assert.equal(article.currency, 'XOF');
assert.equal(article.is_open, true);
assert.equal(article.distance_km, null);
assert.equal(article.ready_at, null);
assert.equal(menuArticle(profile, 'different'), null);
let opened;
const { PublicBusinessProfile } = load('components/PublicBusinessProfile.tsx');
const menu = nodes(PublicBusinessProfile({ profile, favorite: false, busy: false, onOpen: (id) => { opened = id; } }));
assert.ok(includes(menu, 'Chez Awa'));
assert.ok(includes(menu, 'Poulet yassa'));
assert.ok(includes(menu, '4500 XOF'));
assert.ok(!visibleText(menu).includes('null'));
assert.equal(menu.filter((node) => node.type === 'Image').length, 0);
assert.ok(includes(menu, t('clientExperience.localEstablishment')));
assert.ok(!visibleText(menu).includes('articles disponibles'));
menu.find((node) => node.props.accessibilityLabel === 'Voir Poulet yassa').props.onPress();
assert.equal(opened, 'dish');
const closedProfile = { ...profile, is_open: false };
const closedMenu = nodes(PublicBusinessProfile({ profile: closedProfile, busy: false }));
assert.ok(includes(closedMenu, t('clientExperience.businessClosed')));
assert.equal(menuArticle(closedProfile, 'dish').is_open, false);
const { DishDetail } = load('components/DishDetail.tsx');
const closedDetail = nodes(DishDetail({
  dish: menuArticle(closedProfile, 'dish'), quantity: '1', cartQuantity: 0, hasCart: false,
  onContinueShopping() {}, replacementPending: false, onCancelReplacement() {}, onConfirmReplacement() {},
  favorite: false, onBack() {}, onOpenCook() {}, onToggleFavorite() {}, onQuantityChange() {}, onAddToCart() {},
}));
assert.ok(includes(closedDetail, t('clientExperience.businessClosedMessage')));
assert.equal(closedDetail.find((node) => node.type === 'PrimaryButton').props.disabled, true);
const busyMenu = nodes(PublicBusinessProfile({ profile, busy: true }));
assert.equal(busyMenu.find((node) => node.props.accessibilityLabel === 'Voir Poulet yassa').props.disabled, true);
assert.ok(includes(nodes(PublicBusinessProfile({ profile: { ...profile, available_dishes: [] } })), t('clientExperience.menuEmpty')));
const longDish = { ...dish, name: 'Un nom de spécialité locale particulièrement long', description: 'Une description généreuse '.repeat(10) };
const longMenu = nodes(PublicBusinessProfile({ profile: { ...profile, available_dishes: [longDish] }, busy: false }));
assert.equal(longMenu.find((node) => node.props.children === longDish.name).props.numberOfLines, 2);
assert.equal(longMenu.find((node) => node.props.children === longDish.description.trim()).props.numberOfLines, 2);
const internalDish = { ...dish, description: 'Article DEV pour PayDunya Sandbox.' };
const cleanMenu = nodes(PublicBusinessProfile({ profile: { ...profile, bio: 'Profil DEV', available_dishes: [internalDish] }, busy: false }));
assert.ok(!includes(cleanMenu, internalDish.description));
assert.ok(!includes(cleanMenu, 'Profil DEV'));
const profileWithoutDatedAvailability = nodes(PublicBusinessProfile({
  profile: { ...profile, available_dishes: null, recent_reviews: null }, busy: false,
}));
assert.ok(includes(profileWithoutDatedAvailability, t('clientExperience.menuEmpty')));
const reviewProfile = { ...profile, rating_average: '4.00', rating_count: 3, recent_reviews: [
  { id: 'review-3', rating: 3, comment: 'Bon', created_at: '2026-10-03T17:36:00Z', email: 'private@example.test', customer_id: 'private-id' },
  { id: 'review-2', rating: 4, comment: null, created_at: '2026-10-02T17:36:00Z' },
] };
const reviewedMenu = nodes(PublicBusinessProfile({ profile: reviewProfile, busy: false }));
const reviewedText = visibleText(reviewedMenu);
assert.ok(reviewedText.includes('4,0 · 3 avis'));
assert.ok(reviewedText.includes(t('reviews.clientsTitle')));
assert.ok(reviewedText.includes('3/5'));
assert.ok(reviewedText.includes('Bon'));
assert.ok(reviewedText.includes('3 octobre 2026'));
assert.ok(!reviewedText.includes('private@example.test') && !reviewedText.includes('private-id'));
assert.ok(!visibleText(menu).includes('0,0'));
const reviewedArticle = menuArticle(reviewProfile, dish.dish_id);
assert.equal(reviewedArticle.rating_average, '4.00');
assert.equal(reviewedArticle.review_count, 3);
const { DishCard } = load('components/DishCard.tsx');
assert.ok(visibleText(nodes(DishCard({ dish: { ...reviewedArticle, cook_rating: '5.00' }, onPress() {} }))).includes('4,0 (3)'));
const newCardText = visibleText(nodes(DishCard({ dish: { ...article, cook_rating: '5.00' }, onPress() {} })));
assert.ok(newCardText.includes(t('cookProfile.new')));
assert.ok(!newCardText.includes('0,0'));
const format = load('format.ts');
assert.equal(format.formatRating('4.00'), '4,0');
assert.equal(format.formatReviewDate('2026-10-03T17:36:00Z'), '3 octobre 2026');
assert.equal(format.formatDate(null), '');
assert.equal(format.formatDate(undefined), '');
assert.equal(format.formatTime(null), '');
assert.equal(format.formatReviewDate(null), '');
const originalTimezone = process.env.TZ;
process.env.TZ = 'America/Toronto';
assert.equal(format.formatReviewDate('2026-10-04T01:00:00'), '4 octobre 2026');
if (originalTimezone === undefined) delete process.env.TZ;
else process.env.TZ = originalTimezone;
let continued = false;
const welcome = nodes(load('components/ClientWelcome.tsx').ClientWelcome({ onContinue() { continued = true; } }));
for (const step of [1, 2, 3]) assert.ok(includes(welcome, t(`clientExperience.onboardingTitle${step}`)));
welcome.find((node) => node.type === 'PrimaryButton').props.onPress();
assert.ok(continued);
const { CartSummary } = load('components/CartSummary.tsx');
let orders = false, home = false;
const props = { lines: [{ item: article, quantity: 2 }], busy: false, onOrders() { orders = true; }, onHome() { home = true; } };
const confirmed = nodes(CartSummary({ ...props, payment: { status: 'approved', amount_in_cents: 900000, currency: 'XOF', items: [{ quantity: 2 }] } }));
assert.ok(includes(confirmed, t('clientExperience.confirmed')));
assert.ok(includes(confirmed, 'Chez Awa'));
const resolutionActions = nodes(load('components/PaymentActions.tsx').PaymentActions({
  payment: { id: 'paid-conflict', status: 'paid_stock_conflict', provider: 'flutterwave' },
  uiState: 'resolution_required', paymentError: null, paymentBusy: false,
  onPay() { throw new Error('Resolution state must never allow a retry.'); }, onCheckPayment() {}, payTotal: '4500 XOF',
}));
assert.ok(visibleText(resolutionActions).includes(t('checkout.paidStockConflict')));
assert.ok(!resolutionActions.some((node) => node.type === 'PrimaryButton'));
assert.ok(includes(confirmed, t('clientExperience.received', { name: 'Chez Awa' })));
assert.ok(includes(confirmed, '9000.00 XOF'));
const confirmedAfterReturn = nodes(CartSummary({ ...props, lines: [], merchantName: 'Restaurant DEV Sénégal', payment: { status: 'approved', amount_in_cents: 1000000, currency: 'XOF', items: [{ quantity: 3 }] } }));
assert.ok(includes(confirmedAfterReturn, 'Restaurant Sénégal'));
assert.ok(includes(confirmedAfterReturn, t('clientExperience.received', { name: 'Restaurant Sénégal' })));
assert.equal(confirmed.filter((node) => node.type === 'TextInput').length, 0);
for (const node of confirmed.filter((n) => n.type === 'Pressable')) node.props.onPress();
assert.ok(orders && home);
for (const status of ['pending', 'declined', 'error', 'cancelled']) {
  assert.ok(!includes(nodes(CartSummary({ ...props, payment: { status } })), t('clientExperience.confirmed')));
}
const pending = nodes(CartSummary({ ...props, payment: { id: 'pending', status: 'pending' } }));
assert.ok(includes(pending, t('clientExperience.verification')));
assert.ok(includes(pending, t('clientExperience.verificationBody')));
const order = { id: 'order', status: 'ready', created_at: '2026-09-25T10:00:00Z', cook_display_name: 'Chez Awa', total_price: '9000', currency: 'XOF', items: [{ id: 'line', dish_name: 'Poulet yassa', quantity: 2, unit_price: '4500', line_total: '9000' }] };
let pickupRequested = false;
let contactRequested = false;
const detail = nodes(load('components/ClientOrderViews.tsx').ClientOrderDetail({ order, onReview() {}, onRequestPickupCode() { pickupRequested = true; }, onContactMerchant() { contactRequested = true; } }));
assert.ok(includes(detail, t('clientOrders.readyTitle')));
const pickupButton = detail.find((n) => n.type === 'Pressable' && includes(nodes(n), t('clientOrders.showPickupCode')));
assert.ok(pickupButton);
assert.equal(t('clientOrders.showPickupCode'), 'Afficher mon code de retrait');
pickupButton.props.onPress();
assert.equal(pickupRequested, true);
assert.ok(!detail.some((n) => n.type === 'Pressable' && includes(nodes(n), t('clientExperience.pickupFuture'))));
assert.ok(includes(detail, t('clientOrders.contactMerchant')));
assert.ok(includes(detail, t('clientOrderMessages.contactHint')));
detail.find((node) => node.type === 'Pressable' && includes(nodes(node), t('clientOrders.contactMerchant'))).props.onPress();
assert.equal(contactRequested, true);
assert.ok(includes(detail, t('clientOrders.helpTitle')));
const helpToggle = detail.find((n) => n.type === 'Pressable' && n.props.accessibilityState?.expanded === false);
assert.ok(helpToggle);
assert.equal(typeof helpToggle.props.onPress, 'function');
const { ClientReviewForm } = load('components/ClientReviewForm.tsx');
let rating = 0, comment = '', submitted = false;
const reviewProps = { rating, comment, busy: false, onRating(value) { rating = value; }, onComment(value) { comment = value; }, onSubmit() { submitted = true; } };
const review = nodes(ClientReviewForm(reviewProps));
const stars = review.filter((n) => n.props.accessibilityRole === 'radio');
assert.equal(stars.length, 5);
assert.ok(stars.every((n) => n.props.style.minHeight >= 44));
assert.equal(review.find((n) => n.type === 'PrimaryButton').props.disabled, true);
stars[2].props.onPress();
assert.equal(rating, 3);
const selectedReview = nodes(ClientReviewForm({ ...reviewProps, rating }));
assert.equal(selectedReview.find((n) => n.type === 'PrimaryButton').props.disabled, false);
assert.equal(selectedReview.filter((n) => n.props.accessibilityState?.checked).length, 1);
review.find((n) => n.type === 'TextInput').props.onChangeText('Très bon');
assert.equal(comment, 'Très bon');
selectedReview.find((n) => n.type === 'PrimaryButton').props.onPress();
assert.ok(submitted);
const busyReview = nodes(ClientReviewForm({ ...reviewProps, busy: true }));
assert.ok(busyReview.filter((n) => n.type === 'Pressable').every((n) => n.props.disabled));
assert.equal(busyReview.find((n) => n.type === 'TextInput').props.editable, false);
assert.equal(busyReview.find((n) => n.type === 'PrimaryButton').props.loading, true);
let privacyOpened = false, loggedOut = false;
const { ClientProfile } = load('components/ClientProfile.tsx');
const profileView = nodes(ClientProfile({ firstName: 'Awa', lastName: 'Diop', email: 'awa@example.test',
  onPrivacy() { privacyOpened = true; }, onLogout() { loggedOut = true; } }));
for (const text of ['Awa Diop', 'awa@example.test', t('clientProfile.account'), t('clientProfile.preferences'),
  t('clientProfile.notificationsUnavailable'), t('clientProfile.privacySection'), t('clientProfile.session')]) {
  assert.ok(includes(profileView, text), text);
}
assert.ok(!includes(profileView, t('clientExperience.notificationsBody')));
assert.equal(profileView.filter((n) => n.props.accessibilityRole === 'switch').length, 0);
assert.equal(profileView.filter((n) => n.type === 'TextInput').length, 0);
const profileButtons = profileView.filter((n) => n.type === 'Pressable');
assert.equal(profileButtons.length, 2);
profileButtons.forEach((button) => button.props.onPress());
assert.ok(privacyOpened && loggedOut);
console.log('Client welcome, menu, confirmation, help, pickup, review and profile: PASS');
