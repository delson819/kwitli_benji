import { useEffect, useRef, useState, type ReactNode } from "react";
import { ActivityIndicator, AppState, Pressable, StyleSheet, Text, TextInput, Vibration, View } from "react-native";
import { createAudioPlayer, setAudioModeAsync } from "expo-audio";
import { ApiError, confirmPickup as confirmOrderPickup, getOrder, getOrderMessages, getOrders, requestPickupCode, sendOrderMessage, updateOrderStatus, type OrderHistory, type OrderMessage } from "../services/api";
import { createOrderActionGate, isActiveOrder, nextMerchantStatus, orderLines, orderStatusKeys } from "../orders-workflow";
import { formatMoney } from "../format";
import { ACTIVE_LOCALE } from "../language";
import { ACTIVE_MARKET_TIMEZONE, resolveTimezone } from "../market";
import { t } from "../i18n";
import { colors } from "../theme/colors";
import { fonts } from "../theme/typography";
import { radius } from "../theme/radius";
import { spacing } from "../theme/spacing";
import { PrimaryButton } from "./PrimaryButton";
import { ClientOrdersView, OrderMessagesModal } from "./ClientOrderViews";
import { OrderResolutionRequestCard } from "./OrderResolutionRequestCard";

const NEW_ORDER_ALERT_URI = "data:audio/wav;base64,UklGRtQEAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YbAEAACAmKmwqpmCaldQVWZ9laiwq5yFbFlQVGN6kqawrZ6Ib1tRU2F3kKSvrqCKcl1RUl90jaKurqKNdV9SUVxxiqCtr6SQeGFTUVtuh52ssKaTe2RUUFlshJursKiWfmZWUFdpgZiqsKqYgWlXUFZmfpaosKubhGxZUFRke5OmsKydh25bUVNheJCkr62ginFcUVJfdY2irq6ijXRfUlFdcoqgrq+kkHdhU1Fbb4ierbCmknpjVFBZbIWcq7ColX1mVVBXaoKZqrCpmIBoV1BWZ36WqbCrmoNrWFBVZHuUp7CsnYZuWlBTYniRpa+tn4lwXFFSYHaOo6+uoYxzXlJSXnOLoa6vpI92YFNRXHCIn62vpZJ5Y1RQWm2FnKywp5R8ZVVQWGqCmqqwqZd/aFZQVmh/l6mwqpqCalhQVWV8lKewrJyFbVpQVGN5kqWvrZ+IcFxRU2B2j6SvrqGLc15SUl5zjKGur6OOdmBSUVxwiZ+tr6WReGJTUFpuhp2ssKeUe2RVUFhrg5qrsKmWfmdWUFdogJipsKqZgmpXUFVmfZWosKuchWxZUFRjepKmsK2eiG9bUVNhd5Ckr66ginJdUVJfdI2irq6ijXVfUlFccYqgra+kkHhhU1FbboedrLCmk3tkVFBZbISbq7Coln5mVlBXaYGYqrCqmIFpV1BWZn6WqLCpmIBoV1BWZn6WqLCrnIVsWVBUY3qSprCtnohvW1FTYXeQpK+uoIpyXVFSX3SNoq6uoo11X1JRXHGKoK2vpJB4YlNQWm6Gnaywp5R7ZFVQWGuDmquwqZZ+Z1ZQV2g=";

type Scope = "customer" | "cook";
export type MerchantOrderFeed = {
  orders: OrderHistory[];
  loading: boolean;
  error: string | null;
  arrivals: number;
  refresh: () => Promise<void>;
  markSeen: () => void;
  updateOrder: (order: OrderHistory) => void;
};

export function useMerchantOrdersMonitor(merchantId: string | null): MerchantOrderFeed {
  const [orders, setOrders] = useState<OrderHistory[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [arrivals, setArrivals] = useState(0);
  const knownOrders = useRef<Set<string> | null>(null);
  const alertPlayer = useRef<ReturnType<typeof createAudioPlayer> | null>(null);
  const refreshRef = useRef<() => Promise<void>>(async () => undefined);

  useEffect(() => {
    if (!merchantId) return;
    let player: ReturnType<typeof createAudioPlayer> | null = null;
    try {
      player = createAudioPlayer({ uri: NEW_ORDER_ALERT_URI });
      alertPlayer.current = player;
      void setAudioModeAsync({ playsInSilentMode: true, interruptionMode: "mixWithOthers" }).catch((cause) => {
        if (__DEV__) console.warn("NEW_ORDER_AUDIO_SETUP_ERROR", cause);
      });
    } catch (cause) {
      if (__DEV__) console.warn("NEW_ORDER_AUDIO_SETUP_ERROR", cause);
    }
    return () => {
      alertPlayer.current = null;
      player?.release();
    };
  }, [merchantId]);

  useEffect(() => {
    if (!merchantId) return;
    let cancelled = false;
    let pending = false;
    knownOrders.current = null;
    setOrders([]);
    setArrivals(0);
    setLoading(true);

    async function refresh() {
      if (pending || AppState.currentState === "background") return;
      pending = true;
      try {
        const rows = await getOrders("cook");
        if (cancelled) return;
        const known = knownOrders.current;
        const incoming = known ? rows.filter((order) => !known.has(order.id) && isActiveOrder(order.status)) : [];
        knownOrders.current = new Set([...(known ?? []), ...rows.map((order) => order.id)]);
        setOrders(rows);
        setError(null);
        if (incoming.length) {
          setArrivals((count) => count + incoming.length);
          const player = alertPlayer.current;
          if (player) {
            void player.seekTo(0).then(() => player.play()).catch((cause) => {
              if (__DEV__) console.warn("NEW_ORDER_AUDIO_PLAY_ERROR", cause);
            });
          }
          try { Vibration.vibrate(120); } catch (cause) {
            if (__DEV__) console.warn("NEW_ORDER_VIBRATION_ERROR", cause);
          }
        }
      } catch (cause) {
        if (__DEV__) console.warn("MERCHANT_ORDERS_LOAD_FAILED", {
          kind: cause instanceof ApiError ? "http" : "network",
          status: cause instanceof ApiError ? cause.status : null,
        });
        if (!cancelled) setError(t("orders.loadError"));
      } finally {
        pending = false;
        if (!cancelled) setLoading(false);
      }
    }

    refreshRef.current = refresh;
    void refresh();
    const timer = setInterval(() => void refresh(), 15000);
    const listener = AppState.addEventListener("change", (state) => { if (state === "active") void refresh(); });
    return () => {
      cancelled = true;
      refreshRef.current = async () => undefined;
      clearInterval(timer);
      listener.remove();
    };
  }, [merchantId]);

  return {
    orders, loading, error, arrivals,
    refresh: () => refreshRef.current(),
    markSeen: () => setArrivals(0),
    updateOrder: (order) => setOrders((rows) => rows.map((row) => row.id === order.id ? { ...row, ...order } : row)),
  };
}

function orderDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  // SQLite renvoie parfois un timestamp UTC sans suffixe de fuseau.
  const date = new Date(/[zZ]|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}

function orderTime(value: string, businessTimezone?: string) {
  const date = orderDate(value);
  return date ? date.toLocaleString(ACTIVE_LOCALE, {
    weekday: "long", day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit",
    timeZone: resolveTimezone(businessTimezone, ACTIVE_MARKET_TIMEZONE),
  }) : "";
}

function shortOrderNumber(id: string): string {
  return `#K${id.replace(/[^a-z0-9]/gi, "").slice(0, 4).toUpperCase()}`;
}

export function elapsedLabel(order: OrderHistory, nowMs = Date.now(), history = false): string {
  const startedAt = order.status === "in_progress" ? order.in_progress_at : order.created_at;
  const date = orderDate(startedAt);
  if (!date || !startedAt) return "";
  const elapsedMs = Math.max(0, nowMs - date.getTime());
  if (history || elapsedMs >= 24 * 60 * 60 * 1000) return orderTime(startedAt);
  const seconds = Math.floor(elapsedMs / 1000);
  const minutes = Math.floor(elapsedMs / 60000);
  if (order.status === "in_progress") {
    if (seconds < 60) return t("orders.preparingSinceSeconds", { count: seconds });
    if (minutes < 60) return t("orders.preparingSince", { count: minutes });
    return t("orders.preparingSinceHours", { hours: Math.floor(minutes / 60), minutes: minutes % 60 });
  }
  if (seconds === 0) return t("orders.justNow");
  if (seconds < 60) return t("orders.secondsAgo", { count: seconds });
  if (minutes < 60) return t("orders.minutesAgo", { count: minutes });
  return t("orders.hoursAgo", { hours: Math.floor(minutes / 60), minutes: minutes % 60 });
}

export function OrderList({ orders, onOpen, onAction, actionBusy = false, nowMs, history = false }: {
  orders: OrderHistory[]; onOpen: (order: OrderHistory) => void; onAction?: (order: OrderHistory) => void; actionBusy?: boolean;
  nowMs?: number; history?: boolean;
}) {
  const sortedOrders = [...orders].sort((left, right) => {
    // Les commandes pretes passent en tete : le client attend au comptoir.
    const readyDifference = Number(right.status === "ready") - Number(left.status === "ready");
    if (readyDifference) return readyDifference;
    return new Date(left.created_at).getTime() - new Date(right.created_at).getTime();
  });
  return <View style={styles.stack}>
    {!orders.length && <Text style={styles.muted}>{t("orders.empty")}</Text>}
    {sortedOrders.map((order) => {
      const lines = orderLines(order);
      const units = lines.reduce((sum, item) => sum + item.quantity, 0);
      const next = nextMerchantStatus(order.status);
      return <View key={order.id} style={styles.card}>
        <View style={styles.row}>
          <Text style={styles.subtitle}>{shortOrderNumber(order.id)}</Text>
          {order.status === "ordered" && <Text style={styles.newBadge}>{t("orders.new")}</Text>}
        </View>
        <View style={styles.row}>
          <Text style={styles.status}>{order.status === "ready" ? t("orders.readyShort") : t(orderStatusKeys[order.status])}</Text>
          <Text style={styles.muted}>{elapsedLabel(order, nowMs, history)}</Text>
        </View>
        <Text style={styles.body}>{lines.map((item) => `${item.quantity} × ${item.dish_name}`).join("\n")}</Text>
        <Text style={styles.muted}>{t(lines.length === 1 ? "orders.oneLineUnits" : "orders.manyLinesUnits", { lines: lines.length, units })}</Text>
        {order.status === "ready" ? <Text style={styles.readyNote}>{t("orders.awaitingPickup")}</Text>
          : next && onAction && <PrimaryButton disabled={actionBusy} loading={actionBusy} onPress={() => onAction(order)}
            label={t(next === "in_progress" ? "orders.startPreparation" : "orders.markReady")} />}
        <Pressable accessibilityRole="button"
          accessibilityLabel={t(order.status === "ready" ? "orders.openPickupValidation" : "orders.open")}
          onPress={() => onOpen(order)} style={styles.detailLink}>
          <Text style={styles.link}>{t(order.status === "ready" ? "orders.openPickupValidation" : "orders.open")}</Text>
        </Pressable>
        <Text style={styles.total}>{formatMoney(order.total_price, order.currency)}</Text>
      </View>;
    })}
  </View>;
}

export function OrderDetail({ order, scope, busy, onTransition, onReview, onConfirmPickup, pickupError, pickupCodeInput, onPickupCodeChange, onOpenMessages }: {
  order: OrderHistory; scope: Scope; busy: boolean; onTransition: () => void; onReview: (order: OrderHistory) => void;
  onConfirmPickup?: (code: string) => void; pickupError?: string | null; pickupCodeInput?: string; onPickupCodeChange?: (code: string) => void;
  onOpenMessages?: (order: OrderHistory) => void;
}) {
  const code = pickupCodeInput ?? "";
  const next = nextMerchantStatus(order.status);
  return <View style={styles.stack}>
    <Text style={styles.subtitle}>{t("orders.detail")}</Text>
    <Text style={styles.body}>{order.cook_display_name}</Text>
    <Text style={styles.muted}>{orderTime(order.created_at)}</Text>
    {order.in_progress_at && <Text style={styles.muted}>{t("orders.startedAt")}: {orderTime(order.in_progress_at)}</Text>}
    {order.ready_at && <Text style={styles.muted}>{t("orders.readyAt")}: {orderTime(order.ready_at)}</Text>}
    {order.picked_up_at && <Text style={styles.muted}>{t("orders.pickedUpAt")}: {orderTime(order.picked_up_at)}</Text>}
    <Text style={styles.status} accessibilityLiveRegion="polite">{t(orderStatusKeys[order.status])}</Text>
    {order.status === "ready" && <View style={styles.notice}><Text style={styles.status}>
      {t(scope === "cook" ? "orders.awaitingPickup" : "orders.readyNotice")}
    </Text></View>}
    {scope === "cook" && order.status === "ready" && onConfirmPickup && <View style={styles.pickupValidation}>
      <Text style={styles.subtitle}>{t("orders.validatePickup")}</Text>
      <TextInput accessibilityLabel={t("orders.pickupCodeInput")} value={code}
        onChangeText={(value) => onPickupCodeChange?.(value.replace(/\D/g, "").slice(0, 6))}
        keyboardType="number-pad" maxLength={6} editable={!busy} placeholder="000000" style={styles.pickupInput} />
      {!!pickupError && <Text accessibilityRole="alert" style={styles.error}>{pickupError}</Text>}
      <Pressable accessibilityRole="button" accessibilityState={{ disabled: busy || code.length !== 6, busy }}
        disabled={busy || code.length !== 6} onPress={() => onConfirmPickup(code)} style={styles.pickupButton}>
        <Text style={styles.pickupButtonText}>{busy ? t("orders.validatingPickup") : t("orders.validatePickup")}</Text>
      </Pressable>
    </View>}
    {orderLines(order).map((item) => <View key={item.id} style={styles.card}>
      <Text style={styles.subtitle}>{item.dish_name}</Text>
      <Text style={styles.body}>{t("orders.linePrice", { quantity: item.quantity, price: formatMoney(item.unit_price, order.currency) })}</Text>
      <Text style={styles.body}>{formatMoney(item.line_total, order.currency)}</Text>
    </View>)}
    <View style={styles.row}><Text style={styles.subtitle}>{t("orders.total")}</Text><Text style={styles.subtitle}>{formatMoney(order.total_price, order.currency)}</Text></View>
    {scope === "cook" && next && <PrimaryButton disabled={busy} loading={busy} onPress={onTransition}
      label={t(next === "in_progress" ? "orders.startPreparation" : "orders.markReady")} />}
    {scope === "cook" && onOpenMessages && <Pressable accessibilityRole="button" accessibilityLabel={t("orders.customerMessages")}
      onPress={() => onOpenMessages(order)} style={styles.card}>
      <Text style={styles.link}>{t("orders.customerMessages")}</Text>
      <Text style={styles.muted}>{t("orders.customerMessagesHint")}</Text>
    </Pressable>}
    {scope === "cook" && <OrderResolutionRequestCard order={order} role="merchant" />}
    {scope === "customer" && ["completed", "picked_up"].includes(order.status) && !order.review_id &&
      <PrimaryButton label={t("reviews.leaveReview")} onPress={() => onReview(order)} />}
  </View>;
}

export function OrdersScreen({ scope, refreshKey, onReview, renderReview, visible = true, merchantFeed, reviewResult, currentUserId = null }: {
  scope: Scope; refreshKey: number; onReview: (order: OrderHistory, rating?: number) => void;
  renderReview?: (order: OrderHistory) => ReactNode;
  visible?: boolean; merchantFeed?: MerchantOrderFeed;
  reviewResult?: { orderId: string; id: string; rating: number; comment: string | null } | null;
  currentUserId?: string | null;
}) {
  const [orders, setOrders] = useState<OrderHistory[]>([]);
  const [selected, setSelected] = useState<OrderHistory | null>(null);
  const [helpExpanded, setHelpExpanded] = useState(false);
  const [history, setHistory] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [pickupCodeBusy, setPickupCodeBusy] = useState(false);
  const [pickupCodeVisible, setPickupCodeVisible] = useState(false);
  const [pickupActionError, setPickupActionError] = useState<string | null>(null);
  const [pickupValidationError, setPickupValidationError] = useState<string | null>(null);
  const [merchantPickupCode, setMerchantPickupCode] = useState("");
  const [messagesVisible, setMessagesVisible] = useState(false);
  const [messages, setMessages] = useState<OrderMessage[]>([]);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [messagesError, setMessagesError] = useState<string | null>(null);
  const [messageDraft, setMessageDraft] = useState("");
  const [messageSending, setMessageSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [clock, setClock] = useState(() => Date.now());
  const generation = useRef(0);
  const action = useRef(createOrderActionGate());
  const acting = useRef(false);
  const messageSendingRef = useRef(false);
  const messagesGeneration = useRef(0);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; generation.current++; }; }, []);
  useEffect(() => {
    if (scope !== "cook" || !visible) return;
    setClock(Date.now());
    const timer = setInterval(() => setClock(Date.now()), 30000);
    return () => clearInterval(timer);
  }, [scope, visible]);
  useEffect(() => {
    if (!reviewResult || scope !== "customer") return;
    const applyReview = (order: OrderHistory) => order.id === reviewResult.orderId
      ? { ...order, review_id: reviewResult.id, review_rating: reviewResult.rating, review_comment: reviewResult.comment }
      : order;
    setSelected((current) => current ? applyReview(current) : null);
    setOrders((rows) => rows.map(applyReview));
  }, [reviewResult, scope]);

  useEffect(() => {
    if (scope === "cook" && merchantFeed) return;
    const request = ++generation.current;
    setLoading(true); setError(null); setSelected(null);
    getOrders(scope).then((rows) => { if (request === generation.current) setOrders(rows); })
      .catch(() => { if (request === generation.current) { setOrders([]); setError(t("orders.loadError")); } })
      .finally(() => { if (request === generation.current) setLoading(false); });
    return () => { generation.current++; };
  }, [scope, refreshKey, reload, Boolean(merchantFeed)]);

  // Liste client : se rafraichit seule tant qu'une commande est en cours.
  const hasActiveCustomerOrder = scope === "customer" && orders.some((order) => isActiveOrder(order.status));
  useEffect(() => {
    if (scope !== "customer" || !visible || selected || !hasActiveCustomerOrder) return;
    let cancelled = false;
    let pending = false;
    async function refreshList() {
      if (pending || AppState.currentState !== "active") return;
      pending = true;
      try {
        const rows = await getOrders("customer");
        if (!cancelled && alive.current) setOrders(rows);
      } catch {
        // Une erreur temporaire garde la liste affichee.
      } finally {
        pending = false;
      }
    }
    const timer = setInterval(() => void refreshList(), 15000);
    const listener = AppState.addEventListener("change", (state) => {
      if (state === "active") void refreshList();
    });
    return () => {
      cancelled = true;
      clearInterval(timer);
      listener.remove();
    };
  }, [scope, visible, selected?.id, hasActiveCustomerOrder]);

  useEffect(() => {
    // Detail client : suivre la preparation sans appuyer sur Rafraichir.
    if (scope !== "customer" || !visible || !selected || !isActiveOrder(selected.status)) return;
    const selectedOrderId = selected.id;
    const pollMs = selected.status === "ready" ? 5000 : 15000;
    let cancelled = false;
    let pending = false;

    async function refreshSelectedOrder() {
      if (pending || AppState.currentState !== "active") return;
      pending = true;
      try {
        const updated = await getOrder(selectedOrderId);
        if (cancelled || !alive.current) return;
        setSelected((current) => current?.id === updated.id ? { ...current, ...updated } : current);
        setOrders((rows) => rows.map((row) => row.id === updated.id ? { ...row, ...updated } : row));
        if (updated.status !== "ready") setPickupCodeVisible(false);
      } catch {
        // Temporary refresh errors must not hide the still-valid pickup code.
      } finally {
        pending = false;
      }
    }

    const timer = setInterval(() => void refreshSelectedOrder(), pollMs);
    const listener = AppState.addEventListener("change", (state) => {
      if (state === "active") void refreshSelectedOrder();
    });
    return () => {
      cancelled = true;
      clearInterval(timer);
      listener.remove();
    };
  }, [scope, visible, selected?.id, selected?.status]);

  async function open(order: OrderHistory) {
    const request = ++generation.current;
    setHelpExpanded(false);
    setPickupCodeVisible(false);
    setPickupActionError(null);
    setPickupValidationError(null);
    setMerchantPickupCode("");
    setLoading(true); setError(null);
    try {
      const detail = await getOrder(order.id);
      if (request === generation.current) {
        setSelected({ ...order, ...detail });
        if (scope === "customer") setOrders((rows) => rows.map((row) => row.id === order.id ? { ...row, ...detail } : row));
      }
    } catch { if (request === generation.current) setError(t("orders.loadError")); }
    finally { if (request === generation.current) setLoading(false); }
  }

  async function transition(target: OrderHistory | null = selected) {
    if (!target || acting.current || scope !== "cook") return;
    acting.current = true;
    generation.current++;
    setBusy(true); setError(null);
    try {
      await action.current(target, async (id, status) => {
        const updated = await updateOrderStatus(id, status);
        if (!alive.current) return;
        setSelected((current) => current?.id === id ? { ...current, ...updated } : current);
        if (merchantFeed) merchantFeed.updateOrder({ ...target, ...updated });
        else setOrders((rows) => rows.map((row) => row.id === id ? { ...row, ...updated } : row));
        const detail = await getOrder(id);
        if (alive.current) setSelected((current) => current?.id === id ? { ...current, ...detail } : current);
      });
    } catch (e) {
      if (alive.current) {
        setError(t(e instanceof ApiError && [401, 403].includes(e.status) ? "orders.accessError"
          : e instanceof ApiError && e.status === 409 ? "orders.conflictError" : "orders.actionError"));
        // En cas de reponse perdue, ne pas proposer une action basee sur un statut perime.
        setSelected(null);
        if (merchantFeed) void merchantFeed.refresh();
        else {
          setOrders([]);
          // Recharger l'etat serveur au lieu de laisser une liste vide.
          void getOrders(scope).then((rows) => { if (alive.current) setOrders(rows); }).catch(() => undefined);
        }
      }
    } finally { acting.current = false; if (alive.current) setBusy(false); }
  }

  async function showCustomerPickupCode(target: OrderHistory) {
    if (scope !== "customer" || target.status !== "ready" || pickupCodeBusy) return;
    setPickupCodeBusy(true);
    setPickupActionError(null);
    try {
      const updated = await requestPickupCode(target.id);
      if (!alive.current) return;
      setSelected((current) => current?.id === target.id ? { ...current, ...updated } : current);
      setOrders((rows) => rows.map((row) => row.id === target.id ? { ...row, ...updated } : row));
      setPickupCodeVisible(true);
    } catch (cause) {
      setPickupActionError(cause instanceof ApiError && cause.status === 409
        ? t("clientOrders.pickupCodeUnavailable") : t("clientOrders.pickupCodeError"));
    } finally {
      if (alive.current) setPickupCodeBusy(false);
    }
  }

  async function openOrderMessages(target: OrderHistory) {
    const request = ++messagesGeneration.current;
    setMessagesVisible(true);
    setMessagesLoading(true);
    setMessagesError(null);
    setMessages([]);
    setMessageDraft("");
    try {
      const rows = await getOrderMessages(target.id);
      if (request === messagesGeneration.current) setMessages(rows);
    } catch {
      if (request === messagesGeneration.current) setMessagesError(t("clientOrderMessages.loadError"));
    } finally {
      if (request === messagesGeneration.current) setMessagesLoading(false);
    }
  }

  async function sendMessage() {
    if (!selected || messageSendingRef.current || !messageDraft.trim()) return;
    messageSendingRef.current = true;
    setMessageSending(true);
    setMessagesError(null);
    try {
      try {
        await sendOrderMessage(selected.id, messageDraft);
        setMessageDraft("");
      } catch {
        setMessagesError(t("clientOrderMessages.sendError"));
        return;
      }
      try {
        const rows = await getOrderMessages(selected.id);
        setMessages(rows);
      } catch {
        setMessagesError(t("clientOrderMessages.loadError"));
      }
    } finally {
      messageSendingRef.current = false;
      setMessageSending(false);
    }
  }

  // Conversation ouverte : recharger les nouveaux messages de l'autre participant.
  useEffect(() => {
    if (!messagesVisible || !selected) return;
    const orderId = selected.id;
    let cancelled = false;
    const timer = setInterval(() => {
      if (AppState.currentState !== "active") return;
      const request = messagesGeneration.current;
      void getOrderMessages(orderId).then((rows) => {
        if (!cancelled && request === messagesGeneration.current) setMessages(rows);
      }).catch(() => undefined);
    }, 15000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [messagesVisible, selected?.id]);

  function closeOrderMessages() {
    messagesGeneration.current++;
    setMessagesVisible(false);
    setMessagesError(null);
  }

  async function confirmMerchantPickup(code: string) {
    if (scope !== "cook" || !selected || selected.status !== "ready" || acting.current) return;
    acting.current = true;
    setBusy(true);
    setPickupValidationError(null);
    try {
      const updated = await confirmOrderPickup(selected.id, code);
      if (!alive.current) return;
      const merged = { ...selected, ...updated };
      setSelected(merged);
      setMerchantPickupCode("");
      if (merchantFeed) merchantFeed.updateOrder(merged);
      else setOrders((rows) => rows.map((row) => row.id === merged.id ? merged : row));
    } catch (cause) {
      setPickupValidationError(cause instanceof ApiError && cause.status === 409
        ? t("orders.pickupCodeInvalid") : t("orders.actionError"));
    } finally {
      acting.current = false;
      if (alive.current) setBusy(false);
    }
  }

  if (!visible) return null;
  const shownOrders = merchantFeed?.orders ?? orders;
  const shownLoading = merchantFeed?.loading ?? loading;
  const shownError = error ?? merchantFeed?.error ?? null;
  if (scope === "customer") return <ClientOrdersView
    orders={orders.filter((order) => history !== isActiveOrder(order.status))}
    selected={selected} history={history} loading={loading} error={error}
    onOpen={(order) => void open(order)} onBack={() => { closeOrderMessages(); setHelpExpanded(false); setSelected(null); }} onHistory={setHistory}
    onRefresh={() => selected ? void open(selected) : setReload((value) => value + 1)} onReview={onReview}
    renderReview={renderReview} helpExpanded={helpExpanded} onToggleHelp={() => setHelpExpanded((value) => !value)}
    onRequestPickupCode={(order) => void showCustomerPickupCode(order)} pickupCodeVisible={pickupCodeVisible}
    pickupCodeBusy={pickupCodeBusy} pickupActionError={pickupActionError}
    onContactMerchant={(order) => void openOrderMessages(order)} messagesVisible={messagesVisible} messages={messages}
    currentUserId={currentUserId} messagesLoading={messagesLoading} messagesError={messagesError}
    messageDraft={messageDraft} messageSending={messageSending} onCloseMessages={closeOrderMessages}
    onMessageDraftChange={setMessageDraft} onSendMessage={() => void sendMessage()}
  />;

  return <View style={styles.stack}>
    <Text style={styles.title}>{t("orders.received")}</Text>
    {!history && (merchantFeed?.arrivals ?? 0) > 0 && <Pressable accessibilityRole="button" accessibilityLiveRegion="polite"
      onPress={() => { setSelected(null); merchantFeed?.markSeen(); }} style={styles.notice}>
      <Text style={styles.status}>{t(merchantFeed?.arrivals === 1 ? "orders.arrivalOne" : "orders.arrivalMany", { count: merchantFeed?.arrivals ?? 0 })}</Text>
    </Pressable>}
    <View style={styles.row}>
      {selected ? <Pressable disabled={busy} style={styles.control} onPress={() => setSelected(null)}><Text style={styles.link}>{t("common.back")}</Text></Pressable>
        : <View style={styles.row}>{[false, true].map((value) => <Pressable key={String(value)} accessibilityRole="tab" accessibilityState={{ selected: history === value }}
          style={styles.control} onPress={() => setHistory(value)}><Text style={history === value ? styles.status : styles.muted}>{t(value ? "orders.history" : "orders.active")}</Text></Pressable>)}</View>}
      <Pressable disabled={busy || shownLoading} style={styles.control} onPress={() => merchantFeed ? void merchantFeed.refresh() : setReload((value) => value + 1)}><Text style={styles.link}>{t("orders.refresh")}</Text></Pressable>
    </View>
    {shownError && <Text accessibilityRole="alert" style={styles.error}>{shownError}</Text>}
    {shownLoading ? <ActivityIndicator color={colors.brandGreen} /> : selected
      ? <OrderDetail key={selected.id} order={selected} scope={scope} busy={busy} onTransition={() => void transition()} onReview={onReview}
        onConfirmPickup={scope === "cook" ? (code) => void confirmMerchantPickup(code) : undefined} pickupError={pickupValidationError}
        pickupCodeInput={merchantPickupCode} onPickupCodeChange={setMerchantPickupCode}
        onOpenMessages={scope === "cook" ? (order) => void openOrderMessages(order) : undefined} />
      : !shownError && <OrderList orders={shownOrders.filter((order) => history !== isActiveOrder(order.status))} nowMs={clock} history={history} onOpen={(order) => void open(order)}
        onAction={(order) => void transition(order)} actionBusy={busy} />}
    <OrderMessagesModal role="merchant" visible={messagesVisible} order={selected} messages={messages}
      currentUserId={currentUserId} loading={messagesLoading} error={messagesError} draft={messageDraft}
      sending={messageSending} onClose={closeOrderMessages} onDraftChange={setMessageDraft} onSend={() => void sendMessage()} />
  </View>;
}

const styles = StyleSheet.create({
  stack: { gap: spacing.sm },
  title: { fontFamily: fonts.editorialBold, color: colors.darkCocoa, fontSize: 26 },
  subtitle: { fontFamily: fonts.bold, color: colors.darkCocoa, fontSize: 17 },
  body: { fontFamily: fonts.regular, color: colors.darkCocoa, fontSize: 15 },
  muted: { fontFamily: fonts.regular, color: colors.cocoaMuted, fontSize: 14 },
  status: { fontFamily: fonts.bold, color: colors.brandGreen, fontSize: 15 },
  link: { fontFamily: fonts.bold, color: colors.brandGreen, fontSize: 14 },
  error: { fontFamily: fonts.regular, color: colors.error, fontSize: 14 },
  card: { gap: spacing.xs, padding: spacing.sm, borderWidth: 1, borderColor: colors.line, borderRadius: radius.lg, backgroundColor: colors.surface },
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.xs, flexWrap: "wrap" },
  newBadge: { color: colors.mangoOrange, fontFamily: fonts.bold, fontSize: 11, letterSpacing: 1 },
  readyNote: { color: colors.brandGreen, fontFamily: fonts.semiBold, fontSize: 14 },
  detailLink: { alignSelf: "flex-start", minHeight: 40, justifyContent: "center" },
  total: { color: colors.cocoaMuted, fontFamily: fonts.semiBold, fontSize: 14 },
  control: { minHeight: 44, justifyContent: "center", paddingHorizontal: spacing.xs },
  notice: { padding: spacing.sm, borderRadius: radius.md, backgroundColor: colors.creamDeep },
  pickupValidation: { gap: spacing.sm, padding: spacing.md, borderWidth: 1, borderColor: colors.line, borderRadius: radius.lg, backgroundColor: colors.surface },
  pickupInput: { minHeight: 52, borderWidth: 1, borderColor: colors.line, borderRadius: radius.md, paddingHorizontal: spacing.md, textAlign: "center", letterSpacing: 8, fontSize: 22, color: colors.darkCocoa },
  pickupButton: { minHeight: 48, alignItems: "center", justifyContent: "center", borderRadius: radius.md, padding: spacing.sm, backgroundColor: colors.brandGreen },
  pickupButtonText: { color: colors.warmCream, fontFamily: fonts.bold, fontSize: 15 },
});
