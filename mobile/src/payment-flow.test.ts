import { canContinueToPayment, orderTotal, PAYMENT_METHODS } from "./payment-flow.ts";

function expect(condition: boolean): void {
  if (!condition) throw new Error("Payment flow assertion failed.");
}

expect(!canContinueToPayment("1", 5, null));
expect(canContinueToPayment("1", 5, "card"));
expect(!PAYMENT_METHODS.includes("pse" as never));
expect(orderTotal("18000.00", 2) === "36000.00");
