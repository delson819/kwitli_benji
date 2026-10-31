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

let mockedState = [];
let stateChanges = [];
let stateIndex = 0;
let arrivals = 0;
let markedSeen = 0;
const merchantFeed = { orders: [], loading: false, error: null, refresh: async () => {},
  markSeen() { markedSeen++; }, updateOrder() {} };

function load(file) {
  const exports = {};
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(`${__dirname}/${file}`, 'utf8'), {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS },
  }).outputText, { exports, require(path) {
    if (path === 'react') return { ...React, useState(initial) {
      const index = stateIndex++;
      return [mockedState.length ? mockedState.shift() : initial, (value) => stateChanges.push({ index, value })];
    } };
    if (path === 'react/jsx-runtime') return require(path);
    if (path === 'react-native') return {
      ActivityIndicator: 'ActivityIndicator', Image: 'Image', Pressable: 'Pressable', Text: 'Text', TextInput: 'TextInput', View: 'View',
      StyleSheet: { create: (s) => s, hairlineWidth: 1 },
    };
    if (path === '../format') return { formatMoney: (amount, currency) => `${amount} ${currency}` };
    if (path === '../config') return { mediaUrl: (uri) => `http://api.test${uri}` };
    if (path === '../i18n') return { t };
    if (path === './OrdersScreen') return { OrdersScreen: 'OrdersScreen',
      useMerchantOrdersMonitor: () => ({ ...merchantFeed, arrivals }) };
    if (path.startsWith('../theme/')) return { colors: {}, fonts: {}, radius: {}, spacing: { xxs: 4, xs: 8, sm: 16, md: 24 } };
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
function renderWithState(...state) {
  mockedState = [...state];
  stateChanges = [];
  stateIndex = 0;
  return nodes(MerchantDashboard(baseProps));
}
function buttons(tree, label) {
  return tree.filter((node) => node.type === 'Pressable' &&
    React.Children.toArray(node.props.children).some((child) => child?.props?.children === label));
}
const { MerchantDashboard } = load('components/MerchantDashboard.tsx');
const dashboardSource = fs.readFileSync(`${__dirname}/components/MerchantDashboard.tsx`, 'utf8');
const noop = () => {};
const baseProps = {
  profile: { id: 'business', display_name: 'Restaurant Sénégal', bio: 'Cuisine locale', profile_photo_url: null, latitude: 45.4, longitude: -71.8, business_vertical: 'food_service', is_verified: false },
  loading: false,
  publishingArticle: false,
  publishingAvailability: false,
  articles: [{ id: 'dish', cook_id: 'business', name: 'Poulet yassa', description: 'Local', price: '4500', currency: 'XOF', photo_url: null, category: 'Plats', is_active: true }],
  availabilities: [{ id: 'availability', dish_id: 'dish', available_date: '2026-10-01', start_time: '11:00', end_time: '14:00', remaining_portions: 6, total_portions: 10, status: 'active' }],
  selectedAvailabilityArticle: null,
  profileName: 'Restaurant Sénégal',
  profileBio: 'Cuisine locale',
  pickupLatitude: '45.4',
  pickupLongitude: '-71.8',
  articleName: '',
  articleDescription: '',
  articlePrice: '',
  availabilityDate: '2026-10-01',
  startTime: '11:00',
  endTime: '14:00',
  stockQuantity: '8',
  profilePhoto: null,
  articlePhoto: null,
  currency: 'XOF',
  businessHours: Array.from({ length: 7 }, (_, weekday) => ({ id: `hours-${weekday}`, cook_profile_id: 'business', weekday,
    is_closed: weekday === 2, opens_at: weekday === 2 ? null : '10:00:00', closes_at: weekday === 2 ? null : '20:00:00' })),
  hoursSaving: false,
  onProfileNameChange: noop,
  onProfileBioChange: noop,
  onPickupLatitudeChange: noop,
  onPickupLongitudeChange: noop,
  onArticleNameChange: noop,
  onArticleDescriptionChange: noop,
  onArticlePriceChange: noop,
  onAvailabilityDateChange: noop,
  onStartTimeChange: noop,
  onEndTimeChange: noop,
  onStockQuantityChange: noop,
  onUseCurrentLocation: noop,
  onCreateProfile: noop,
  onSaveProfile: noop,
  onBusinessHourChange: noop,
  onSaveBusinessHours: noop,
  onSavePickup: noop,
  onPickProfilePhoto: noop,
  onReplaceProfilePhoto: noop,
  onPickArticlePhoto: noop,
  onReplaceArticlePhoto: noop,
  onSelectAvailabilityArticle: noop,
  onPublishArticle: noop,
  onPublishAvailability: noop,
  onCancelNewArticle: noop,
  onPickEditArticlePhoto: noop,
  onSaveEditArticlePhoto: noop,
  onUpdateArticle: noop,
  onUpdateAvailability: noop,
};

const tree = renderWithState('dashboard', false);
for (const text of [
  t('merchant.establishment'),
  t('merchant.catalog.foodService'),
  t('merchant.receivedOrders'),
  'Restaurant Sénégal',
  t('merchant.catalogOverview', { count: 1, article: t('merchant.article.foodService') }),
  t('merchant.ordersOverview'),
]) {
  assert.ok(includes(tree, text), text);
}
assert.ok(!includes(tree, 'Poulet yassa'));
assert.ok(!includes(tree, t('merchant.priceWithCurrency', { currency: 'FCFA' })));
assert.ok(!includes(tree, t('merchant.addArticle')));

const establishment = renderWithState('establishment', false);
const savedProfile = { ...baseProps.profile, profile_photo_url: '/uploads/persisted.jpg' };
for (let reload = 0; reload < 2; reload++) {
  mockedState = ['establishment', false];
  const restored = nodes(MerchantDashboard({ ...baseProps, profile: { ...savedProfile } }));
  assert.ok(restored.some((node) => node.type === 'Image' && node.props.source.uri === 'http://api.test/uploads/persisted.jpg'));
}
assert.equal(tree.find((node) => node.type === 'OrdersScreen').props.visible, false,
  'La surveillance reste montee sur le dashboard');
assert.ok(tree.find((node) => node.type === 'OrdersScreen').props.merchantFeed,
  'OrdersScreen consomme le monitor du dashboard');
arrivals = 2;
const alerted = renderWithState('dashboard', false);
assert.ok(includes(alerted, t('orders.arrivalMany', { count: 2 })), 'Le dashboard affiche les nouvelles commandes');
buttons(alerted, t('merchant.receivedOrders'))[0].props.onPress();
assert.equal(markedSeen, 1, 'Consulter les commandes acquitte le badge');
arrivals = 0;
for (const text of [
  t('merchant.establishment'),
  t('merchant.establishmentName'),
  t('merchant.establishmentDescription'),
  t('merchant.descriptionHint'),
  t('merchant.businessVertical'),
  t('merchant.vertical.foodService'),
  t('merchant.pickupPoint'),
  t('merchant.pickupCoordinatesHint'),
  t('merchant.pendingProfile'),
  t('merchant.pendingProfileHint'),
  t('merchant.saveProfile'),
  t('merchant.businessHours'),
  t('merchant.weekday.monday'),
  t('merchant.openingTime'),
  t('merchant.closingTime'),
  t('merchant.saveBusinessHours'),
  t('merchant.savePickup'),
]) {
  assert.ok(includes(establishment, text), text);
}
mockedState = ['establishment', false];
stateIndex = 0;
const verifiedEstablishment = nodes(MerchantDashboard({ ...baseProps,
  profile: { ...baseProps.profile, is_verified: true },
}));
assert.ok(includes(verifiedEstablishment, t('merchant.verified')));
assert.ok(includes(verifiedEstablishment, t('merchant.verifiedHint')));
assert.ok(!includes(verifiedEstablishment, t('merchant.pendingProfileHint')));

const catalog = renderWithState('catalog', false);
for (const text of [
  t('merchant.catalog.foodService'),
  'Poulet yassa',
  '4500 XOF',
  'Plats',
  t('merchant.addArticle'),
  t('merchant.editArticle'),
  t('merchant.activeArticle'),
]) {
  assert.ok(includes(catalog, text), text);
}
assert.ok(!includes(catalog, t('merchant.priceWithCurrency', { currency: 'FCFA' })));
for (const legacyStock of [
  t('merchant.stockSummary', { remaining: 6, total: 10 }),
  t('merchant.date'),
  t('merchant.portionsAvailable'),
  '2026-10-01',
  '6/10 en stock',
]) {
  assert.ok(!includes(catalog, legacyStock), `Le stock daté ne doit pas être visible: ${legacyStock}`);
}
assert.equal(buttons(catalog, t('merchant.editArticle')).length, 1);
assert.equal(buttons(catalog, t('merchant.addAvailability')).length, 0);

mockedState = ['catalog', false];
stateIndex = 0;
const inactiveCatalog = nodes(MerchantDashboard({ ...baseProps,
  articles: [{ ...baseProps.articles[0], is_active: false }],
}));
assert.ok(includes(inactiveCatalog, t('merchant.inactiveArticle')));
assert.ok(!includes(inactiveCatalog, t('merchant.activeArticle')));

const createForm = renderWithState('catalog', true);
assert.ok(includes(createForm, t('merchant.priceWithCurrency', { currency: 'FCFA' })));
assert.ok(includes(createForm, t('merchant.articleCategory')));
assert.ok(includes(createForm, t('merchant.activeArticle')));
assert.ok(includes(createForm, t('merchant.inactiveArticle')));
assert.ok(!includes(createForm, t('merchant.date')));
assert.equal(buttons(catalog, t('merchant.photoAction')).length, 0);

const orders = renderWithState('orders', false);
assert.equal(orders.filter((node) => node.type === 'OrdersScreen').length, 1);

for (const legacy of ['Ma cuisine', 'Profil cuisinier', 'Mes plats', 'Créer un plat']) {
  assert.ok(!includes(tree, legacy), legacy);
}

mockedState = ['establishment', false];
const onboarding = nodes(MerchantDashboard({ ...baseProps, profile: null, articles: [], availabilities: [] }));
assert.ok(includes(onboarding, t('merchant.createEstablishment')));
assert.ok(includes(onboarding, t('merchant.establishmentName')));
assert.ok(includes(onboarding, t('merchant.establishmentDescription')));
assert.ok(dashboardSource.includes('updateDraft({ isActive: false })'), 'Inactive article toggle must update article state');
assert.ok(dashboardSource.includes('updateDraft({ isActive: true })'), 'Active article toggle must update article state');
assert.ok(dashboardSource.includes('is_active: draft.isActive'), 'Article PATCH must use backend is_active field');
assert.ok(dashboardSource.includes('updateAvailabilityDraft({ availabilityStatus: "inactive" })'), 'Unavailable toggle must update availability state');
assert.ok(dashboardSource.includes('updateAvailabilityDraft({ availabilityStatus: "active" })'), 'Available toggle must update availability state');
assert.ok(dashboardSource.includes('status: draft.availabilityStatus'), 'Availability PATCH must use backend status field');
assert.ok(!dashboardSource.includes('availabilityStatus: draft.isActive'), 'Availability status must not be derived from article status');
assert.ok(!dashboardSource.includes('is_active: draft.availabilityStatus'), 'Article status must not be derived from availability status');

async function verifyEditing() {
  const calls = [];
  const articleDraft = { articleId: 'dish', name: 'Poulet yassa', description: 'Local', price: '4500', currency: 'XOF', category: 'Plats', isActive: false, photo: null };
  mockedState = ['catalog', false, articleDraft];
  stateIndex = 0;
  const articleTree = nodes(MerchantDashboard({ ...baseProps,
    onUpdateArticle: async (id, payload) => calls.push({ kind: 'article', id, payload }),
    onUpdateAvailability: async () => calls.push({ kind: 'availability' }),
  }));
  await buttons(articleTree, t('merchant.saveArticle'))[0].props.onPress();
  assert.deepEqual(calls.map((entry) => entry.kind), ['article']);
  assert.equal(calls[0].payload.is_active, false);
  calls.length = 0;
  buttons(articleTree, t('common.cancel'))[0].props.onPress();
  assert.equal(calls.length, 0);

  mockedState = ['catalog', false, articleDraft];
  stateIndex = 0;
  stateChanges = [];
  const photoTree = nodes(MerchantDashboard({ ...baseProps,
    onPickEditArticlePhoto: async () => ({ uri: 'file:///new-photo.jpg', mimeType: 'image/jpeg', fileName: 'new-photo.jpg' }),
    onSaveEditArticlePhoto: async (id, asset) => calls.push({ kind: 'photo', id, asset }),
    onUpdateArticle: async (id) => calls.push({ kind: 'article', id }),
  }));
  buttons(photoTree, t('photo.gallery'))[0].props.onPress();
  await new Promise((resolve) => setImmediate(resolve));
  const photoChange = stateChanges.find((entry) => entry.index === 2 && typeof entry.value === 'function');
  assert.ok(photoChange, JSON.stringify(stateChanges.map((entry) => [entry.index, typeof entry.value])));
  const stagedPhoto = photoChange.value(articleDraft);
  assert.equal(stagedPhoto.photo.uri, 'file:///new-photo.jpg');
  assert.equal(calls.length, 0, 'Photo selection must not upload before save');
  mockedState = ['catalog', false, stagedPhoto];
  stateIndex = 0;
  const photoSaveTree = nodes(MerchantDashboard({ ...baseProps,
    onSaveEditArticlePhoto: async (id, asset) => calls.push({ kind: 'photo', id, asset }),
    onUpdateArticle: async (id) => calls.push({ kind: 'article', id }),
  }));
  buttons(photoSaveTree, t('merchant.saveArticle'))[0].props.onPress();
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(calls.map((entry) => entry.kind), ['article', 'photo']);
  assert.equal(calls[1].id, 'dish');

  mockedState = ['catalog', true, null, null, false, 'Plats', false, 'inactive'];
  stateIndex = 0;
  const creation = nodes(MerchantDashboard({ ...baseProps,
    selectedAvailabilityArticle: baseProps.articles[0],
    onPublishArticle: async (options) => { calls.push({ kind: 'createArticle', options }); return true; },
    onPublishAvailability: (status) => calls.push({ kind: 'createAvailability', status }),
  }));
  await buttons(creation, t('merchant.addArticle')).at(-1).props.onPress();
  assert.equal(calls.at(-1).kind, 'createArticle');
  assert.equal(calls.at(-1).options.category, 'Plats');
  assert.equal(calls.at(-1).options.is_active, false);
}
verifyEditing().then(() => console.log('Merchant dashboard sections, wording and bridge data: PASS')).catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
