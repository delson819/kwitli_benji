import { API_URL, isApiConfigured } from "../config";
import { buildDiscoverPath, type BusinessVertical, type DiscoverFilter } from "../discovery";
import type { ServiceArea } from "../location";

export type { BusinessVertical, DiscoverFilter } from "../discovery";

let accessToken: string | null = null;

export class ApiError extends Error {
  constructor(public readonly status: number, message: string, public readonly causeType?: string) {
    super(message);
  }
}

type ApiDiagnosticStage = "login" | "register" | "hydration_me" | "health_probe";
type AuthDiagnosticStage = Extract<ApiDiagnosticStage, "login" | "register">;
type AuthDiagnosticEvent = "TOKEN_SAVE_START" | "TOKEN_SAVED" | "PROFILE_LOADED";

function safeDiagnosticPath(path: string): string {
  return path.split("?", 1)[0].replace(
    /\/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}(?=\/|$)/gi,
    "/:id",
  );
}

function safeErrorType(error: unknown): string {
  if (error !== null && typeof error === "object" && "name" in error
      && typeof error.name === "string" && /^[A-Za-z][A-Za-z0-9]*Error$/.test(error.name)) {
    return error.name;
  }
  return "Error";
}

function logApiDiagnostic(method: string, path: string, result: string, stage?: ApiDiagnosticStage): void {
  if (typeof __DEV__ !== "undefined" && __DEV__) {
    const stageLabel = stage ? ` stage=${stage}` : "";
    const safePath = safeDiagnosticPath(path);
    const target = stage === "health_probe" ? `${API_URL}${safePath}` : safePath;
    console.info(`[API DEBUG] ${method} ${target} -> ${result}${stageLabel}`);
  }
}

export function logAuthDiagnostic(event: AuthDiagnosticEvent, stage: AuthDiagnosticStage): void {
  if (typeof __DEV__ !== "undefined" && __DEV__) {
    console.info(`[API DEBUG] AUTH ${event} stage=${stage}`);
  }
}

export type User = { id: string; email: string; first_name: string; last_name: string | null; can_cook: boolean };
export type CookProfile = { id: string; display_name: string; bio: string | null; profile_photo_url: string | null; latitude: number; longitude: number; business_vertical: BusinessVertical; is_verified: boolean };
export type BusinessHour = { id: string | null; cook_profile_id: string; weekday: number; is_closed: boolean; opens_at: string | null; closes_at: string | null };
export type Me = { user: User; cook_profile: CookProfile | null };
export type Token = { access_token: string; token_type: string };

export type DiscoverItem = {
  availability_id: string | null; dish_id: string; dish_name: string; cook_id: string; cook_display_name: string;
  profile_photo_url: string | null;
  business_vertical: BusinessVertical;
  description: string; cook_rating: string; rating_average: string | null; review_count: number;
  photo_url: string | null; price: string; currency: string; remaining_portions: number | null; available_date: string | null;
  start_time: string | null; end_time: string | null; ready_at: string | null; featured_type: string | null; distance_km: number | null;
  is_open: boolean;
};

export type Dish = { id: string; cook_id: string; name: string; description: string; price: string; currency: string; photo_url: string | null; category: string | null; is_active: boolean };
export type Availability = { id: string; dish_id: string; available_date: string; start_time: string; end_time: string; remaining_portions: number; total_portions: number; status: string };
export type DishPublication = { dish: Dish; availability: Availability };
export type OrderStatus = "ordered" | "in_progress" | "ready" | "picked_up" | "confirmed" | "completed" | "cancelled";
export type OrderItem = { id: string; dish_id: string; availability_id: string | null; dish_name: string; photo_url: string | null; quantity: number; unit_price: string; line_total: string };
export type Order = { id: string; availability_id: string | null; quantity: number | null; unit_price: string | null; total_price: string; currency: string; status: OrderStatus; pickup_code: string | null; confirmed_at: string | null; in_progress_at: string | null; ready_at: string | null; picked_up_at: string | null; completed_at: string | null; cancelled_at: string | null; pickup_expires_at: string | null; created_at: string; cook_id: string; cook_display_name: string; items: OrderItem[] };
export type PublicReview = { id: string; rating: number; comment: string | null; created_at: string };
export type PublicCookProfile = {
  cook_id: string; display_name: string; bio: string | null; profile_photo_url: string | null;
  business_vertical: BusinessVertical;
  is_open: boolean;
  rating_average: string | null; rating_count: number; orders_completed: number; is_verified: boolean;
  active_dishes_count: number; member_since: string; recent_reviews: PublicReview[];
  available_dishes: { dish_id: string; availability_id: string | null; name: string; description: string; photo_url: string | null; price: string; currency: string; remaining_portions: number | null; start_time: string | null; end_time: string | null; is_active?: boolean }[];
};
export type FavoriteCook = { id: string; cook_id: string; display_name: string; profile_photo_url: string | null; rating_average: string | null; rating_count: number; has_active_availability: boolean; created_at: string };
export type OrderHistory = Order & {
  dish_name: string | null; dish_photo_url: string | null; review_id: string | null;
  review_rating?: number | null; review_comment?: string | null;
};
export type OrderMessage = { id: string; order_id: string; sender_id: string; sender_role: "customer" | "merchant"; body: string; created_at: string };
export type OrderResolutionReason = "order_not_received" | "incorrect_order" | "item_missing" | "excessive_delay"
  | "quality_issue" | "merchant_unavailable" | "ingredient_unavailable" | "item_out_of_stock"
  | "exceptional_closure" | "menu_price_error" | "technical_issue" | "other";
export type OrderResolutionRequest = {
  id: string; order_id: string; requester_id: string; requester_role: "customer" | "merchant";
  request_type: "client_cancellation" | "client_claim" | "merchant_cancellation";
  reason: OrderResolutionReason; description: string; status: "submitted" | "approved" | "rejected" | "resolution_requested";
  reviewed_by: string | null; reviewed_at: string | null; decision_note: string | null; created_at: string;
};
export type MobileMoneyNetwork = "WAVE" | "ORANGEMONEY";
export type Payment = { items: { availability_id: string | null; dish_id: string | null; quantity: number; amount_in_cents: number }[]; id: string; order_id?: string | null; availability_id: string | null; quantity: number; amount_in_cents: number; currency: string; provider: string; provider_reference: string; status: "pending" | "approved" | "declined" | "error" | "cancelled" | "paid_stock_conflict" | "reconcile_required" | "refund_pending" | "refunded"; checkout_url: string | null; next_action?: { type: "external" | "wait"; url?: string | null } | null; created_at: string; approved_at: string | null; declined_at: string | null };
export type RecoveredPayment = Payment & { order_id?: string | null };
type ApiDetail = { detail?: unknown };

function responseDetail(payload: unknown): unknown {
  return payload !== null && typeof payload === "object" ? (payload as ApiDetail).detail : undefined;
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

async function request<T>(
  path: string,
  method = "GET",
  body?: object,
  authenticated = false,
  extraHeaders: Record<string, string> = {},
  diagnosticStage?: ApiDiagnosticStage,
  onHttpStatus?: (status: number) => void,
): Promise<T> {
  if (!isApiConfigured()) throw new ApiError(0, "API_URL_NOT_CONFIGURED");
  if (authenticated && !accessToken) throw new ApiError(401, "AUTH_REQUIRED");

  logApiDiagnostic(method, path, "SEND", diagnosticStage);
  let responseStatus: number | null = null;
  try {
    const response = await fetch(`${API_URL}${path}`, {
      method,
      headers: {
        ...(body ? { "Content-Type": "application/json" } : {}),
        ...(authenticated && accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        ...extraHeaders,
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    responseStatus = response.status;
    onHttpStatus?.(response.status);
    logApiDiagnostic(method, path, `HTTP ${response.status}`, diagnosticStage);
    const responseBody = await response.text();
    let payload: unknown = null;
    if (responseBody) {
      try {
        payload = JSON.parse(responseBody) as unknown;
      } catch {
        throw new ApiError(response.status, response.ok ? "INVALID_API_RESPONSE" : "API_REQUEST_FAILED");
      }
    }
    if (!response.ok) {
      const detail = responseDetail(payload);
      throw new ApiError(response.status, typeof detail === "string" ? detail : "API_REQUEST_FAILED");
    }
    return payload as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    const errorType = safeErrorType(error);
    logApiDiagnostic(
      method,
      path,
      responseStatus === null ? `NETWORK_ERROR ${errorType}` : `RESPONSE_ERROR ${errorType} HTTP ${responseStatus}`,
      diagnosticStage,
    );
    throw new ApiError(0, "NETWORK_ERROR", errorType);
  }
}

export function register(payload: { email: string; password: string; first_name: string; last_name?: string }): Promise<Token> {
  return request<Token>("/api/v1/auth/register", "POST", payload, false, {}, "register");
}

export function login(payload: { email: string; password: string }): Promise<Token> {
  return request<Token>("/api/v1/auth/login", "POST", payload, false, {}, "login");
}

export type ApiHealth = { status: string };

export function getApiHealth(onHttpStatus?: (status: number) => void): Promise<ApiHealth> {
  return request<ApiHealth>("/api/v1/health", "GET", undefined, false, {}, "health_probe", onHttpStatus);
}

export function requestPasswordReset(email: string): Promise<{ message: string }> {
  return request<{ message: string }>("/api/v1/auth/password-reset/request", "POST", { email });
}

export function confirmPasswordReset(token: string, newPassword: string): Promise<{ message: string }> {
  return request<{ message: string }>("/api/v1/auth/password-reset/confirm", "POST", {
    token,
    new_password: newPassword,
  });
}

export function getMe(stage?: "hydration_me"): Promise<Me> {
  return request<Me>("/api/v1/me", "GET", undefined, true, {}, stage);
}
export function getServiceAreas(): Promise<ServiceArea[]> { return request<ServiceArea[]>("/api/v1/service-areas"); }
export function getDiscover(location: { latitude: number; longitude: number; radiusKm: number; filter?: DiscoverFilter; vertical?: BusinessVertical }): Promise<DiscoverItem[]> {
  return request<DiscoverItem[]>(buildDiscoverPath(location));
}

export function createCook(payload: { display_name: string; bio?: string; latitude: number; longitude: number; business_vertical?: BusinessVertical }): Promise<CookProfile> {
  return request<CookProfile>("/api/v1/cooks", "POST", payload, true);
}

export function updateCook(payload: { display_name?: string; bio?: string | null; latitude?: number; longitude?: number; business_vertical?: BusinessVertical }): Promise<CookProfile> {
  return request<CookProfile>("/api/v1/cooks/me", "PATCH", payload, true);
}

export function getCookBusinessHours(): Promise<BusinessHour[]> {
  return request<BusinessHour[]>("/api/v1/cooks/me/hours", "GET", undefined, true);
}

export function saveCookBusinessHours(days: Array<Pick<BusinessHour, "weekday" | "is_closed" | "opens_at" | "closes_at">>): Promise<BusinessHour[]> {
  return request<BusinessHour[]>("/api/v1/cooks/me/hours", "PUT", { days }, true);
}

export function createDish(payload: { name: string; description: string; price: string; currency: string; category?: string | null; is_active?: boolean }): Promise<Dish> {
  return request<Dish>("/api/v1/dishes", "POST", payload, true);
}

export function updateDish(dishId: string, payload: {
  name?: string; description?: string; price?: string; category?: string | null; is_active?: boolean;
}): Promise<Dish> {
  return request<Dish>(`/api/v1/dishes/${encodeURIComponent(dishId)}`, "PATCH", payload, true);
}

export function publishDishWithAvailability(payload: {
  name: string; description: string; price: string; currency: string;
  available_date: string; start_time: string; end_time: string; total_portions: number;
}): Promise<DishPublication> {
  return request<DishPublication>("/api/v1/dishes/with-availability", "POST", payload, true);
}

export function getDishes(): Promise<Dish[]> { return request<Dish[]>("/api/v1/dishes", "GET", undefined, true); }

export function createAvailability(payload: { dish_id: string; available_date: string; start_time: string; end_time: string; total_portions: number; status?: "active" | "inactive" }): Promise<Availability> {
  return request<Availability>("/api/v1/availabilities", "POST", payload, true);
}

export function getAvailabilities(): Promise<Availability[]> { return request<Availability[]>("/api/v1/availabilities", "GET", undefined, true); }
export function getAvailability(id: string): Promise<Availability> { return request<Availability>(`/api/v1/availabilities/${encodeURIComponent(id)}`, "GET", undefined, true); }
export function updateAvailability(id: string, payload: {
  available_date?: string; start_time?: string; end_time?: string; total_portions?: number; remaining_portions?: number; status?: "active" | "inactive";
}): Promise<Availability> {
  return request<Availability>(`/api/v1/availabilities/${encodeURIComponent(id)}`, "PATCH", payload, true);
}

export function createOrder(payload: { availability_id: string; quantity: number }): Promise<Order> {
  return request<Order>("/api/v1/orders", "POST", payload, true);
}
export function createPayment(payload: { items: Array<{ dish_id: string; quantity: number } | { availability_id: string; quantity: number }>; network?: MobileMoneyNetwork; phone_number?: string; return_url?: string }, idempotencyKey: string): Promise<Payment> {
  return request<Payment>("/api/v1/payments", "POST", payload, true, { "Idempotency-Key": idempotencyKey });
}
export function getPayment(paymentId: string): Promise<RecoveredPayment> { return request<RecoveredPayment>(`/api/v1/payments/${encodeURIComponent(paymentId)}`, "GET", undefined, true); }
export function getPaymentByReference(reference: string): Promise<RecoveredPayment> { return request<RecoveredPayment>(`/api/v1/payments/by-tx-ref/${encodeURIComponent(reference)}`, "GET", undefined, true); }
export function paySandboxInvoice(paymentId: string): Promise<Payment> { return request<Payment>(`/api/v1/payments/${paymentId}/paydunya/test-payment`, "POST", undefined, true); }
export function paymentCheckoutUrl(payment: Payment): string | null { return payment.checkout_url ? (payment.checkout_url.startsWith("http") ? payment.checkout_url : `${API_URL}${payment.checkout_url}`) : null; }

export function getPublicCook(cookId: string): Promise<PublicCookProfile> { return request<PublicCookProfile>(`/api/v1/cooks/${cookId}/public`); }
export function getFavorites(): Promise<FavoriteCook[]> { return request<FavoriteCook[]>("/api/v1/favorites/cooks", "GET", undefined, true); }
export function addFavorite(cookId: string): Promise<{ is_favorite: boolean }> { return request(`/api/v1/favorites/cooks/${cookId}`, "POST", undefined, true); }
export function removeFavorite(cookId: string): Promise<void> { return request<void>(`/api/v1/favorites/cooks/${cookId}`, "DELETE", undefined, true); }
export function getFavoriteStatus(cookId: string): Promise<{ is_favorite: boolean }> { return request(`/api/v1/favorites/cooks/${cookId}/status`, "GET", undefined, true); }
export function getOrders(scope: "customer" | "cook"): Promise<OrderHistory[]> { return request<OrderHistory[]>(`/api/v1/orders?scope=${scope}`, "GET", undefined, true); }
export function getOrder(orderId: string): Promise<Order> { return request<Order>(`/api/v1/orders/${orderId}`, "GET", undefined, true); }
export function getOrderMessages(orderId: string): Promise<OrderMessage[]> {
  return request<OrderMessage[]>(`/api/v1/orders/${encodeURIComponent(orderId)}/messages`, "GET", undefined, true);
}
export function sendOrderMessage(orderId: string, body: string): Promise<OrderMessage> {
  return request<OrderMessage>(`/api/v1/orders/${encodeURIComponent(orderId)}/messages`, "POST", { body }, true);
}
export function updateOrderStatus(orderId: string, status: "in_progress" | "ready"): Promise<Order> { return request<Order>(`/api/v1/orders/${orderId}/status`, "PATCH", { status }, true); }
export function confirmPickup(orderId: string, pickupCode?: string): Promise<Order> {
  return request<Order>(`/api/v1/orders/${orderId}/pickup/confirm`, "POST", pickupCode ? { pickup_code: pickupCode } : {}, true);
}
export function requestPickupCode(orderId: string): Promise<Order> {
  return request<Order>(`/api/v1/orders/${encodeURIComponent(orderId)}/pickup/code`, "POST", {}, true);
}
export function createOrderResolutionRequest(orderId: string, payload: {
  reason: OrderResolutionReason; description: string;
}): Promise<OrderResolutionRequest> {
  return request<OrderResolutionRequest>(`/api/v1/orders/${encodeURIComponent(orderId)}/resolution-requests`, "POST", payload, true);
}
export function createReview(payload: { order_id: string; rating: number; comment?: string }): Promise<PublicReview> {
  const comment = payload.comment && payload.comment.trim().length > 0 ? payload.comment : undefined;
  return request<PublicReview>("/api/v1/reviews", "POST", { order_id: payload.order_id, rating: payload.rating, ...(comment ? { comment } : {}) }, true);
}

// Une erreur proxy (502, 413...) peut renvoyer du HTML ou rien : ne jamais planter sur response.json().
async function uploadPayload(response: Response): Promise<unknown> {
  const text = await response.text().catch(() => "");
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    if (response.ok) throw new ApiError(response.status, "INVALID_API_RESPONSE");
    return null;
  }
}

function uploadNetworkError(error: unknown): never {
  throw new ApiError(0, "NETWORK_ERROR", safeErrorType(error));
}

export async function uploadDishPhoto(dishId: string, asset: { uri: string; mimeType?: string | null; fileName?: string | null }): Promise<Dish> {
  if (!isApiConfigured()) throw new ApiError(0, "API_URL_NOT_CONFIGURED");
  if (!accessToken) throw new ApiError(401, "AUTH_REQUIRED");
  const endpoint = `/api/v1/dishes/${dishId}/photo`;
  const form = new FormData();
  form.append("image", { uri: asset.uri, name: asset.fileName ?? "dish.jpg", type: asset.mimeType ?? "image/jpeg" } as never);
  if (__DEV__) console.log("UPLOAD START", { endpoint, filename: asset.fileName ?? "dish.jpg", mime: asset.mimeType ?? "image/jpeg" });
  const response = await fetch(`${API_URL}${endpoint}`, { method: "POST", headers: { Authorization: `Bearer ${accessToken}` }, body: form })
    .catch((error: unknown) => {
      if (__DEV__) console.warn("UPLOAD ERROR", { endpoint, reason: "network", error: error instanceof Error ? error.message : String(error) });
      return uploadNetworkError(error);
    });
  if (__DEV__) console.log("UPLOAD HTTP STATUS", { endpoint, status: response.status });
  const payload = await uploadPayload(response);
  if (!response.ok) {
    const detail = responseDetail(payload);
    if (__DEV__) console.warn("UPLOAD ERROR", { endpoint, status: response.status, detail: typeof detail === "string" ? detail : null });
    throw new ApiError(response.status, typeof detail === "string" ? detail : "API_REQUEST_FAILED");
  }
  if (__DEV__) console.log("UPLOAD SUCCESS", { endpoint, status: response.status });
  return payload as Dish;
}

export async function uploadCookProfilePhoto(asset: { uri: string; mimeType?: string | null; fileName?: string | null }): Promise<CookProfile> {
  if (!isApiConfigured()) throw new ApiError(0, "API_URL_NOT_CONFIGURED");
  if (!accessToken) throw new ApiError(401, "AUTH_REQUIRED");
  const endpoint = "/api/v1/cooks/me/photo";
  const form = new FormData();
  form.append("image", { uri: asset.uri, name: asset.fileName ?? "profile.jpg", type: asset.mimeType ?? "image/jpeg" } as never);
  if (__DEV__) console.log("UPLOAD START", { endpoint, filename: asset.fileName ?? "profile.jpg", mime: asset.mimeType ?? "image/jpeg" });
  const response = await fetch(`${API_URL}${endpoint}`, { method: "POST", headers: { Authorization: `Bearer ${accessToken}` }, body: form })
    .catch((error: unknown) => {
      if (__DEV__) console.warn("UPLOAD ERROR", { endpoint, reason: "network", error: error instanceof Error ? error.message : String(error) });
      return uploadNetworkError(error);
    });
  if (__DEV__) console.log("UPLOAD HTTP STATUS", { endpoint, status: response.status });
  const payload = await uploadPayload(response);
  const detail = responseDetail(payload);
  if (!response.ok) {
    if (__DEV__) console.warn("UPLOAD ERROR", { endpoint, status: response.status, detail: typeof detail === "string" ? detail : null });
    throw new ApiError(response.status, typeof detail === "string" ? detail : "API_REQUEST_FAILED");
  }
  if (__DEV__) console.log("UPLOAD SUCCESS", { endpoint, status: response.status });
  return payload as CookProfile;
}
