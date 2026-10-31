import AsyncStorage from "@react-native-async-storage/async-storage";
import type { CartItem } from "./order-actions";
import type { DiscoverItem, Payment } from "./services/api";

const PAYMENT_SESSION_KEY = "kwitli.checkout-payment";

type CheckoutLineIdentity = { item: { dish_id: string; availability_id?: string | null }; quantity: number };
export type PaymentIdentity = { paymentId?: string; txRef?: string };
export type StoredPaymentSession = PaymentIdentity & {
  sessionId: string;
  state: "active" | "completed";
  userId: string;
  checkoutKey: string;
  paymentAttempt: number;
  merchantName?: string | null;
  lines?: CartItem<DiscoverItem>[];
};

export function newCheckoutSession(userId: string, lines: CartItem<DiscoverItem>[]): StoredPaymentSession {
  return {
    sessionId: `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`,
    state: "active", userId, checkoutKey: checkoutPaymentKey(lines), paymentAttempt: 0,
    merchantName: lines[0]?.item.cook_display_name, lines: lines.map(line => ({ ...line })),
  };
}

export function sameCheckout(a: StoredPaymentSession, b: StoredPaymentSession): boolean {
  return a.state === "active" && b.state === "active" && a.sessionId === b.sessionId
    && a.userId === b.userId && a.checkoutKey === b.checkoutKey
    && sameCart(a.lines ?? [], b.lines ?? []);
}

export function sameCart(a: CartItem<DiscoverItem>[], b: CartItem<DiscoverItem>[]): boolean {
  const signature = (lines: CartItem<DiscoverItem>[]) => lines.map(({ item, quantity }) =>
    JSON.stringify([item.dish_id ?? item.availability_id, quantity, item.cook_id, item.currency, item.price])).sort().join("|");
  return signature(a) === signature(b);
}

export function paymentMatchesCheckout(session: StoredPaymentSession, payment: Payment): boolean {
  if (session.state !== "active" || !session.lines?.length) return false;
  if (session.paymentId && session.paymentId !== payment.id) return false;
  if (session.txRef && session.txRef !== payment.provider_reference) return false;
  const key = payment.items.map((line) => {
    const legacyLine = line.availability_id == null ? undefined
      : session.lines!.find((checkoutLine) => checkoutLine.item.availability_id === line.availability_id);
    return `${line.dish_id ?? legacyLine?.item.dish_id ?? line.availability_id}:${line.quantity}`;
  }).sort().join("|");
  const total = session.lines.reduce((sum, line) => sum + Math.round(Number(line.item.price) * 100) * line.quantity, 0);
  return key === session.checkoutKey && payment.amount_in_cents === total
    && session.lines.every(line => line.item.currency === payment.currency
      && line.item.cook_id === session.lines![0].item.cook_id);
}

// Serialiser les ecritures pour qu'une cloture ne supprime jamais une nouvelle session.
let writes: Promise<void> = Promise.resolve();
function write(operation: () => Promise<void>): Promise<void> {
  const next = writes.then(operation, operation);
  writes = next.catch(() => undefined);
  return next;
}

export function checkoutPaymentKey(lines: CheckoutLineIdentity[]): string {
  return lines
    .map(({ item, quantity }) => `${item.dish_id ?? item.availability_id}:${quantity}`)
    .sort()
    .join("|");
}

export function paymentIdempotencyKey(session: StoredPaymentSession): string {
  return `${session.sessionId}:${session.paymentAttempt}`;
}

function legacyCheckoutPaymentKey(lines: CheckoutLineIdentity[]): string {
  return lines.map(({ item, quantity }) => `${item.availability_id}:${quantity}`).sort().join("|");
}

export async function saveCheckoutPayment(session: StoredPaymentSession): Promise<void> {
  await write(() => AsyncStorage.setItem(PAYMENT_SESSION_KEY, JSON.stringify(session)));
}

export async function loadCheckoutPayment(userId: string): Promise<StoredPaymentSession | null> {
  await writes;
  const raw = await AsyncStorage.getItem(PAYMENT_SESSION_KEY);
  if (!raw) return null;
  const stored = JSON.parse(raw) as Partial<StoredPaymentSession>;
  if (stored.userId !== userId) return null;
  // Les anciennes sessions sans identite de checkout sont volontairement non recuperables.
  if (typeof stored.sessionId !== "string" || !stored.sessionId || stored.state !== "active") return null;
  if (typeof stored.checkoutKey !== "string" || !stored.lines?.length
    || (checkoutPaymentKey(stored.lines) !== stored.checkoutKey
      && legacyCheckoutPaymentKey(stored.lines) !== stored.checkoutKey)) return null;
  const paymentAttempt = stored.paymentAttempt ?? 0;
  if (!Number.isSafeInteger(paymentAttempt) || paymentAttempt < 0) return null;
  return { ...stored, paymentAttempt, checkoutKey: checkoutPaymentKey(stored.lines) } as StoredPaymentSession;
}

export async function completeCheckoutPayment(sessionId: string): Promise<void> {
  await write(async () => {
    const raw = await AsyncStorage.getItem(PAYMENT_SESSION_KEY);
    if (!raw) return;
    const stored = JSON.parse(raw) as StoredPaymentSession;
    if (stored.sessionId !== sessionId) return;
    await AsyncStorage.setItem(PAYMENT_SESSION_KEY, JSON.stringify({
      sessionId, userId: stored.userId, state: "completed", checkoutKey: stored.checkoutKey,
    }));
  });
}

export async function readExistingPayment<T>(
  stored: PaymentIdentity | null, returned: PaymentIdentity | null,
  byId: (id: string) => Promise<T>, byReference: (reference: string) => Promise<T>,
): Promise<T | null> {
  if (!stored) return null;
  if (returned?.paymentId && returned.paymentId !== stored.paymentId) return null;
  if (returned?.txRef && returned.txRef !== stored.txRef) return null;
  const id = stored.paymentId;
  if (id) return byId(id);
  const reference = returned?.txRef ?? stored?.txRef;
  return reference ? byReference(reference) : null;
}

export function clearCheckoutPayment(): Promise<void> {
  return write(() => AsyncStorage.removeItem(PAYMENT_SESSION_KEY));
}
