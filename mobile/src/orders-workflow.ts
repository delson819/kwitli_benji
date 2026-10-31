import type { Order, OrderHistory, OrderStatus } from "./services/api";

export const orderStatusKeys = {
  ordered: "orders.status.ordered", in_progress: "orders.status.in_progress", ready: "orders.status.ready",
  picked_up: "orders.status.picked_up", completed: "orders.status.completed", confirmed: "orders.status.confirmed",
  cancelled: "orders.status.cancelled",
} as const;

export function isActiveOrder(status: OrderStatus): boolean {
  return ["ordered", "in_progress", "ready", "confirmed"].includes(status);
}

export function nextMerchantStatus(status: OrderStatus): "in_progress" | "ready" | null {
  return status === "ordered" ? "in_progress" : status === "in_progress" ? "ready" : null;
}

export function orderLines(order: OrderHistory) {
  if (order.items.length) return order.items;
  // Lecture des anciennes commandes sans lignes historisees.
  if (order.availability_id && order.quantity && order.unit_price) return [{
    id: order.id, dish_id: "", availability_id: order.availability_id, dish_name: order.dish_name ?? order.cook_display_name,
    photo_url: order.dish_photo_url, quantity: order.quantity, unit_price: order.unit_price, line_total: order.total_price,
  }];
  return [];
}

export function createOrderActionGate() {
  let pending = false;
  return async (order: Order, update: (id: string, status: "in_progress" | "ready") => Promise<void>) => {
    const target = nextMerchantStatus(order.status);
    if (pending || !target) return false;
    pending = true;
    try { await update(order.id, target); return true; }
    finally { pending = false; }
  };
}
