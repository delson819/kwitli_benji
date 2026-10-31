export type PaymentMethod = "card";

export const PAYMENT_METHODS: readonly PaymentMethod[] = ["card"];

export function validQuantity(value: string): number | null {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

export function orderTotal(price: string, quantity: number): string {
  return (Number(price) * quantity).toFixed(2);
}

export function canContinueToPayment(
  quantity: string,
  remainingPortions: number,
  paymentMethod: PaymentMethod | null,
): boolean {
  const parsedQuantity = validQuantity(quantity);
  return paymentMethod !== null && parsedQuantity !== null && parsedQuantity <= remainingPortions;
}
