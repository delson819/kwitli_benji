import type { Payment } from "./services/api";

export type PaymentUiState = "idle" | "redirecting" | "verifying" | "approved" | "failed" | "resolution_required";

const TERMINAL_FAILURES: Payment["status"][] = ["declined", "error", "cancelled"];
const RESOLUTION_STATUSES: Payment["status"][] = [
  "paid_stock_conflict",
  "reconcile_required",
  "refund_pending",
  "refunded",
];

export function resolvePaymentUiState(
  payment: Payment | null,
  busy: boolean,
  hasStaleError: boolean,
): PaymentUiState {
  if (payment?.status === "approved") return "approved";
  if (payment && TERMINAL_FAILURES.includes(payment.status)) return "failed";
  if (payment?.id && RESOLUTION_STATUSES.includes(payment.status)) return "resolution_required";
  if (payment?.id && (payment.status === "pending" || hasStaleError)) return "verifying";
  if (payment?.id) return "resolution_required";
  if (busy) return "redirecting";
  return "idle";
}
