import { addCartItem, boundedQuantity, canOrderQuantity, requiresCartReplacement, cartItemCount, cartTotal, changeCartQuantity, removeCartItem } from "./order-actions.ts";
import { orderTotal } from "./payment-flow.ts";

function expect(condition: boolean, message: string): void {
  if (!condition) throw new Error(message);
}

const dish = { availability_id: "availability-1", cook_id: "seller-1", remaining_portions: 5, price: "19000.00", currency: "COP", dish_name: "Poulet", photo_url: "/photo.jpg" };

expect(boundedQuantity(1, 5) === 1, "Quantity 1 must be accepted.");
expect(boundedQuantity(2, 5) === 2, "Quantity 2 must be accepted.");
expect(boundedQuantity(5, 5) === 5, "Maximum stock must be accepted.");
expect(boundedQuantity(6, 5) === 6, "Quantity is not capped by legacy dated stock.");
expect(boundedQuantity(51) === 50, "Client quantity respects the API safety limit.");
expect(orderTotal("18000.00", 2) === "36000.00", "Order total must follow quantity.");

const firstCart = addCartItem([], dish, 2);
expect(firstCart.length === 1, "Add to cart must create one cart line.");
expect(firstCart[0]?.quantity === 2, "Cart must preserve the selected quantity.");

const cappedCart = addCartItem(firstCart, dish, 5);
expect(cappedCart.length === 1, "Adding the same dish must not duplicate its cart line.");
expect(cappedCart[0]?.quantity === 7, "Accumulated cart quantity is independent of legacy stock.");

const noStockDish = { dish_id: "dish-2", availability_id: null, cook_id: "seller-1", price: "100.00", currency: "COP", dish_name: "Riz", photo_url: null };
expect(addCartItem([], noStockDish, 1).length === 1, "Active catalog items do not require a dated stock record.");

for (const stock of [0, 1, 8]) {
  expect(boundedQuantity(0, stock) === 1, "Minimum quantity is independent of legacy availability.");
  expect(boundedQuantity(99, stock) === 50, "Maximum quantity is a request limit, not stock.");
}
expect(canOrderQuantity(50), "Order now accepts the API maximum without stock data.");
expect(!canOrderQuantity(51), "Order now rejects quantities above the API limit.");
expect(!canOrderQuantity(1.5, 8), "Fractional quantities are rejected.");
expect(!canOrderQuantity(NaN, 8), "Invalid quantities are rejected.");
expect(orderTotal("19000.00", 2) === "38000.00", "Summary total matches unit price times quantity.");
expect(firstCart[0]?.item.price === dish.price && firstCart[0]?.item.cook_id === dish.cook_id, "Cart keeps current price and seller.");
const otherSeller = { ...dish, availability_id: "other", cook_id: "seller-2" };
expect(requiresCartReplacement(firstCart, otherSeller), "Different seller requires confirmation.");
expect(addCartItem(firstCart, otherSeller, 1) === firstCart, "Unconfirmed replacement leaves the cart intact.");
const replaced = addCartItem([], otherSeller, 2);
expect(replaced.length === 1 && replaced[0]?.item.cook_id === "seller-2" && replaced[0]?.quantity === 2, "Confirmed replacement contains only the new seller.");
expect(!requiresCartReplacement(firstCart, dish), "Same seller does not require confirmation.");
expect(addCartItem(firstCart, { ...dish, availability_id: "second" }, 1).length === 2, "Different items from the same seller coexist.");
expect(addCartItem(firstCart, dish, 0) === firstCart, "Invalid additions leave cart unchanged.");
expect(cartItemCount(firstCart) === 2, "Counter counts portions.");
expect(cartTotal(firstCart) === "38000.00", "Cart total uses quantities.");
expect(cartTotal([]) === "0.00", "Empty total is zero.");
const secondLine = { ...dish, availability_id: "second", price: "24000.00" };
const twoLines = addCartItem(addCartItem([], dish, 1), secondLine, 1);
expect(cartItemCount(twoLines) === 2 && cartTotal(twoLines) === "43000.00", "Two different dishes have correct count and total.");
expect(changeCartQuantity(twoLines, dish.availability_id, 3)[0].quantity === 3, "Cart quantity can increase.");
expect(changeCartQuantity(twoLines, dish.availability_id, 6)[0].quantity === 6, "Cart quantity is independent of legacy stock.");
expect(removeCartItem(twoLines, dish.availability_id).length === 1, "Removal removes only selected item.");
const xof = { ...dish, currency: "XOF", price: "4500.00", availability_id: "xof" };
expect(addCartItem(firstCart, xof, 1) === firstCart, "Mixed currencies are rejected without conversion.");
expect(cartTotal(addCartItem([], xof, 2)) === "9000.00", "XOF total retains its monetary value.");
let mixedRejected = false;
try { cartTotal([...firstCart, { item: xof, quantity: 1 }]); } catch { mixedRejected = true; }
expect(mixedRejected, "Corrupted mixed cart cannot produce a total.");
