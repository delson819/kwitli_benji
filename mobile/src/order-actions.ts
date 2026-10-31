export type CartItem<T> = {
  item: T;
  quantity: number;
};

type StockedItem = {
  currency: string;
  availability_id?: string | null;
  dish_id?: string;
  cook_id: string;
};

export function cartItemId(item: { dish_id?: string; availability_id?: string | null }): string {
  return item.dish_id ?? item.availability_id ?? "";
}

export function hasMixedCartCurrency<T extends { currency: string }>(cart: CartItem<T>[], item: T): boolean {
  return cart.some((line) => line.item.currency !== item.currency);
}

export function requiresCartReplacement<T extends StockedItem>(cart: CartItem<T>[], item: T): boolean {
  return cart.some((line) => line.item.cook_id !== item.cook_id);
}

export function canOrderQuantity(quantity: number, _stock?: number | null): boolean {
  return Number.isInteger(quantity) && quantity >= 1 && quantity <= 50;
}

export function boundedQuantity(requested: number, _availableStock?: number | null): number {
  if (!Number.isFinite(requested)) return 1;
  return Math.min(50, Math.max(1, Math.trunc(requested)));
}

export function cartItemCount<T>(cart: CartItem<T>[]): number {
  return cart.reduce((sum, line) => sum + line.quantity, 0);
}

export function cartTotal<T extends { price: string; currency: string }>(cart: CartItem<T>[]): string {
  if (cart.length && hasMixedCartCurrency(cart, cart[0].item)) throw new Error("MIXED_CART_CURRENCY");
  const cents = cart.reduce((sum, line) => sum + Math.round(Number(line.item.price) * 100) * line.quantity, 0);
  return (cents / 100).toFixed(2);
}

export function changeCartQuantity<T extends StockedItem>(cart: CartItem<T>[], id: string, quantity: number): CartItem<T>[] {
  return cart.map((line) => cartItemId(line.item) === id && canOrderQuantity(quantity)
    ? { ...line, quantity } : line);
}

export function removeCartItem<T extends StockedItem>(cart: CartItem<T>[], id: string): CartItem<T>[] {
  return cart.filter((line) => cartItemId(line.item) !== id);
}

export function addCartItem<T extends StockedItem>(
  cart: CartItem<T>[],
  item: T,
  requestedQuantity: number,
): CartItem<T>[] {
  if (!canOrderQuantity(requestedQuantity) || !cartItemId(item) || requiresCartReplacement(cart, item) || hasMixedCartCurrency(cart, item)) return cart;
  const quantity = boundedQuantity(requestedQuantity);
  if (quantity === 0) return cart;

  const existing = cart.find((line) => cartItemId(line.item) === cartItemId(item));
  if (!existing) return [...cart, { item, quantity }];

  const nextQuantity = boundedQuantity(
    existing.quantity + quantity,
    undefined,
  );
  return cart.map((line) => (
    cartItemId(line.item) === cartItemId(item)
      ? { item, quantity: nextQuantity }
      : line
  ));
}
