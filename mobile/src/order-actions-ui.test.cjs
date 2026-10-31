const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const React = require('react');

// Execute le composant avec des primitives natives neutres pour tester ses callbacks.
const source = fs.readFileSync(`${__dirname}/components/DishDetail.tsx`, 'utf8');
const compiled = ts.transpileModule(source, {
  compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS },
}).outputText;
const exportsObject = {};
const loadTs = (path) => {
  const exports = {};
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(path, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS },
  }).outputText, { exports });
  return exports;
};
vm.runInNewContext(compiled, {
  exports: exportsObject,
  require: (name) => {
    if (name === 'react/jsx-runtime') return require(name);
    if (name === 'react-native') return { Image: 'Image', Pressable: 'Pressable', Text: 'Text', View: 'View', StyleSheet: { create: (s) => s } };
    if (name.includes('Ionicons')) return 'Icon';
    if (name === '../order-actions') return loadTs(`${__dirname}/order-actions.ts`);
    if (name === '../payment-flow') return loadTs(`${__dirname}/payment-flow.ts`);
    if (name === '../client-content') return loadTs(`${__dirname}/client-content.ts`);
    if (name === '../config') return { mediaUrl: (s) => s };
    if (name === '../format') return { formatMoney: String, formatDate: String, formatTime: String, formatDistance: String,
      formatRating: (value) => Number(value).toFixed(1).replace('.', ',') };
    if (name === '../i18n') return { t: (s, params = {}) => {
      if (s.startsWith('cart.inCartQuantity')) return `${s}:${params.quantity}`;
      if (s === 'cart.addWithTotal') return `${s}:${params.total}`;
      if (s === 'dishDetail.lowStock') return `${s}:${params.stock}`;
      if (s === 'reviews.countPlural') return `${params.count} avis`;
      return s;
    } };
    if (name === './PrimaryButton') return { PrimaryButton: 'PrimaryButton' };
    if (name === './PaymentActions') return { PaymentActions: 'PaymentActions' };
    if (name.startsWith('../theme/')) return { colors: {}, radius: {}, spacing: {}, fonts: {}, fontSizes: {} };
    throw new Error(`Unexpected dependency: ${name}`);
  },
});
function nodes(element) {
  if (!React.isValidElement(element)) return [];
  return [element, ...React.Children.toArray(element.props.children).flatMap(nodes)];
}
const dish = { dish_id: 'dish-1', availability_id: null, price: '19000.00', dish_name: 'Poulet', cook_display_name: 'Cuisine', cook_rating: '0', photo_url: '/photo.jpg', is_open: true };
let added, ordered, changed, cancelled = false, confirmed = false;
const props = {
  dish, quantity: '2', cartQuantity: 0, orderSummaryVisible: false, replacementPending: false,
  onAddToCart: (q) => { added = q; }, onOrderNow: (q) => { ordered = q; },
  onQuantityChange: (q) => { changed = q; },
  onCancelReplacement: () => { cancelled = true; }, onConfirmReplacement: () => { confirmed = true; },
};
const render = (overrides = {}) => nodes(exportsObject.DishDetail({ ...props, ...overrides }));
const button = (tree, label) => tree.find((n) => n.props.label === label || n.props.accessibilityLabel === label || nodes(n).some((c) => c.type === 'Text' && c.props.children === label) && n.type === 'Pressable');
let tree = render();
button(tree, 'cart.add').props.onPress();
assert.equal(button(tree, 'order.orderNow'), undefined);
assert.equal(added, 2);

button(tree, 'detail.increaseQuantity').props.onPress();
assert.equal(changed, '3');
assert.equal(button(render({ quantity: '1' }), 'detail.decreaseQuantity').props.disabled, true);
assert.equal(button(render({ quantity: '8' }), 'detail.increaseQuantity').props.disabled, false);
assert.equal(button(render({ quantity: '50' }), 'detail.increaseQuantity').props.disabled, true);
tree = render({ dish: { ...dish, remaining_portions: 0 } });
assert.equal(button(tree, 'cart.add').props.disabled, false);

tree = render({ replacementPending: true });
button(tree, 'cart.cancel').props.onPress();
button(tree, 'cart.replace').props.onPress();
assert.ok(cancelled && confirmed);
tree = render({ hasCart: true, onContinueShopping() { ordered = 'home'; } });
assert.equal(button(tree, 'cart.viewCart'), undefined);
button(tree, 'cart.continueShopping').props.onPress();
assert.equal(ordered, 'home');
assert.ok(button(tree, 'cart.continueShopping'));
assert.ok(tree.some((n) => n.type === 'Image' && n.props.source.uri === '/photo.jpg'));
for (const text of ['Poulet', 'Cuisine', '19000.00']) {
  assert.ok(tree.some((n) => n.type === 'Text' && n.props.children === text), text);
}
assert.equal(tree.find((n) => n.type === 'PrimaryButton').props.label, 'cart.addWithTotal:38000.00');
let restaurantOpened = false;
const ratedTree = render({ dish: { ...dish, rating_average: '4.00', review_count: 3 }, onOpenCook() { restaurantOpened = true; } });
assert.ok(ratedTree.some((n) => n.type === 'Text' && React.Children.toArray(n.props.children).join('') === '4,0 · 3 avis'));
button(ratedTree, 'dish.cookA11y').props.onPress();
assert.equal(restaurantOpened, true);
assert.ok(!tree.some((n) => n.type === 'Text' && JSON.stringify(n.props.children).includes('0,0')));
const noStockUiTree = render({ dish: { ...dish, remaining_portions: 0 }, quantity: '1' });
assert.ok(!noStockUiTree.some((n) => n.type === 'Text' && JSON.stringify(n.props.children).includes('stock')));
assert.equal(button(tree, 'order.orderNow'), undefined);
const { addCartItem } = loadTs(`${__dirname}/order-actions.ts`);
let itemCart = [];
for (const expected of [0, 1, 2]) {
  if (expected) itemCart = addCartItem(itemCart, dish, 1);
  const cartQuantity = itemCart[0]?.quantity ?? 0;
  const rendered = render({ quantity: '1', cartQuantity, hasCart: !!itemCart.length });
  const messages = rendered.filter((n) => n.type === 'Text' && typeof n.props.children === 'string' && n.props.children.startsWith('cart.inCartQuantity'));
  assert.equal(messages.length, expected ? 1 : 0);
  if (expected) assert.equal(messages[0].props.children, `cart.inCartQuantity${expected === 1 ? 'Singular' : 'Plural'}:${expected}`);
  assert.equal(button(rendered, 'cart.viewCart'), undefined);
}
for (const locale of ['fr', 'es-CO']) {
  const catalog = JSON.parse(fs.readFileSync(`${__dirname}/../locales/${locale}.json`, 'utf8'));
  for (const key of ['cart.inCartQuantitySingular', 'cart.inCartQuantityPlural']) assert.ok(catalog[key].includes('{quantity}'));
}
console.log('DishDetail callbacks, request quantity limit, replacement confirmation and single cart path: PASS');

const appSource = ts.createSourceFile('App.tsx', fs.readFileSync(`${__dirname}/../App.tsx`, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
let logout;
function findLogout(node) {
  if (ts.isFunctionDeclaration(node) && node.name?.text === 'logout') logout = node;
  ts.forEachChild(node, findLogout);
}
findLogout(appSource);
assert.ok(logout, 'Logout handler must exist.');
let cart = ['previous-user-item'], pending = {}, summary = true;
const noop = () => {};
vm.runInNewContext(`(${logout.getText(appSource)})()`, {
  deleteAccessToken: async () => {}, setAccessToken: noop, setMe: noop, setSessionExpired: noop, setDishes: noop,
  clearCheckoutPayment: async () => {},
  activeCheckout: { current: null }, returnedPayment: { current: null }, cartChanged: { current: false },
  setSelectedDish: noop, setMode: noop, setScreen: noop,
  setCheckoutLines: () => { summary = false; }, setCheckoutMerchantName: noop, setPaidIds: noop, setPayment: noop, setOpeningPayment: noop,
  paymentSession: { current: 0 }, unopenedCheckout: { current: null }, cartReturn: { current: null },
  setCart: (value) => { cart = value; },
  setPendingCartReplacement: (value) => { pending = value; },
  setOrderSummaryVisible: (value) => { summary = value; },
}).then(() => {
  assert.equal(cart.length, 0);
  assert.equal(pending, null);
  assert.equal(summary, false);
  console.log('Logout clears local cart, pending replacement and summary: PASS');
}).catch((error) => { console.error(error); process.exitCode = 1; });
