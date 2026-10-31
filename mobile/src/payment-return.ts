type ParsedPaymentReturn = {
  path: string | null;
  hostname?: string | null;
  queryParams: Record<string, string | string[] | undefined> | null;
};

export function paymentIdentityFromReturn(parsed: ParsedPaymentReturn): { paymentId?: string; txRef?: string } | null {
  if (parsed.path !== "payment-return" && !(parsed.hostname === "payment-return" && !parsed.path)) return null;
  const id = parsed.queryParams?.payment_id;
  const reference = parsed.queryParams?.tx_ref;
  const paymentId = typeof id === "string" && id.length <= 120 && id ? id : undefined;
  const txRef = typeof reference === "string" && reference.length <= 120 && reference ? reference : undefined;
  return paymentId || txRef ? { paymentId, txRef } : null;
}

export function paymentIdFromReturn(parsed: ParsedPaymentReturn): string | null {
  const paymentId = parsed.queryParams?.payment_id;
  return parsed.path === "payment-return" && typeof paymentId === "string" && paymentId
    ? paymentId
    : null;
}
