import type { ReactNode } from "react";
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import Ionicons from "@expo/vector-icons/Ionicons";
import { clientDisplayName } from "../client-content";
import type { OrderHistory, OrderMessage } from "../services/api";
import { orderLines, orderStatusKeys } from "../orders-workflow";
import { formatMoney } from "../format";
import { ACTIVE_LOCALE } from "../language";
import { ACTIVE_MARKET_TIMEZONE, resolveTimezone } from "../market";
import { t } from "../i18n";
import { colors } from "../theme/colors";
import { fonts } from "../theme/typography";
import { radius } from "../theme/radius";
import { spacing } from "../theme/spacing";
import { OrderResolutionRequestCard } from "./OrderResolutionRequestCard";

function dateTime(value: string, businessTimezone?: string) {
  const date = new Date(/[zZ]|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString(ACTIVE_LOCALE, {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
    timeZone: resolveTimezone(businessTimezone, ACTIVE_MARKET_TIMEZONE),
  });
}

function StatusBadge({ order }: { order: OrderHistory }) {
  return <View style={[styles.badge, order.status === "ready" && styles.readyBadge]}>
    <View style={[styles.dot, order.status === "ready" && styles.readyDot]} />
    <Text style={[styles.badgeText, order.status === "ready" && styles.readyText]}>{clientStatusLabel(order.status)}</Text>
  </View>;
}

function clientStatusLabel(status: OrderHistory["status"]) {
  return t(status === "completed" ? "orders.status.picked_up" : orderStatusKeys[status]);
}

export function ClientOrderList({ orders, history, onOpen }: {
  orders: OrderHistory[]; history: boolean; onOpen: (order: OrderHistory) => void;
}) {
  if (!orders.length) return <View style={styles.empty}>
    <Text style={styles.heading}>{t(history ? "clientOrders.emptyHistoryTitle" : "clientOrders.emptyTitle")}</Text>
    <Text style={styles.muted}>{t(history ? "clientOrders.emptyHistoryBody" : "clientOrders.emptyBody")}</Text>
  </View>;
  return <View style={styles.stack}>{orders.map((order) => <Pressable key={order.id}
    accessibilityRole="button" accessibilityLabel={`${t("clientOrders.viewDetails")} · ${clientDisplayName(order.cook_display_name)}`}
    onPress={() => onOpen(order)} style={({ pressed }) => [styles.card, pressed && styles.pressed]}>
    <View style={styles.stackSmall}>
      <Text style={styles.heading}>{clientDisplayName(order.cook_display_name)}</Text>
      <StatusBadge order={order} />
      <Text style={styles.caption}>{dateTime(order.created_at)}</Text>
    </View>
    <View style={styles.footer}>
      <Text style={styles.amount}>{formatMoney(order.total_price, order.currency)}</Text>
      <Text style={styles.link}>{t("clientOrders.viewDetails")}</Text>
    </View>
  </Pressable>)}</View>;
}

function timeOnly(value: string | null | undefined) {
  if (!value) return "";
  const date = new Date(/[zZ]|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleTimeString(ACTIVE_LOCALE, {
    hour: "2-digit", minute: "2-digit", timeZone: resolveTimezone(undefined, ACTIVE_MARKET_TIMEZONE),
  });
}

function shortOrderNumber(id: string): string {
  return `#K${id.replace(/[^a-z0-9]/gi, "").slice(0, 4).toUpperCase()}`;
}

const STEP_ICONS = { ordered: "checkmark", in_progress: "restaurant", ready: "bag-handle" } as const;

// Frise de la maquette : rond orange plein pour les etapes passees, contour pour la suite.
export function ClientOrderProgress({ order }: { order: OrderHistory }) {
  if (order.status === "cancelled") return null;
  const steps = ["ordered", "in_progress", "ready"] as const;
  const current = order.status === "confirmed" ? 0 : steps.indexOf(order.status as typeof steps[number]);
  const terminal = order.status === "picked_up" || order.status === "completed";
  const times = { ordered: order.created_at, in_progress: order.in_progress_at, ready: order.ready_at };
  return <View style={styles.card}>
    <Text style={styles.section}>{t("clientOrders.progress")}</Text>
    {steps.map((step, index) => {
      const done = terminal || index < current;
      const active = !terminal && index === current;
      const time = done || active ? timeOnly(times[step]) : "";
      return <View key={step} style={styles.step} accessible accessibilityLabel={
        `${t(orderStatusKeys[step])}, ${t(done ? "clientOrders.stepDone" : active ? "clientOrders.stepCurrent" : "clientOrders.stepNext")}`
      }>
        <View style={styles.track}>
          <View style={[styles.stepDot, (done || active) && styles.stepReached]}>
            <Ionicons color={done || active ? colors.ink : colors.cocoaMuted}
              name={done ? "checkmark" : `${STEP_ICONS[step]}-outline` as const} size={16} />
          </View>
          {index < steps.length - 1 && <View style={[styles.connector, done && styles.connectorDone]} />}
        </View>
        <View style={styles.stepCopy}>
          <Text style={[styles.stepText, (done || active) && styles.stepTextReached, active && styles.stepTextActive]}>{t(orderStatusKeys[step])}</Text>
          {!!time && <Text style={styles.stepTime}>{time}</Text>}
        </View>
      </View>;
    })}
  </View>;
}

// En-tete sombre « Ça se prépare ! » pour les commandes en cours.
function OrderHero({ order }: { order: OrderHistory }) {
  const title = order.status === "ready" ? t("clientOrders.readyStatusTitle")
    : order.status === "in_progress" ? t("clientOrders.heroPreparing") : t("clientOrders.heroOrdered");
  // Coche orange comme sur la maquette ; un sac quand la commande est prete.
  const icon = order.status === "ready" ? "bag-handle" : "checkmark";
  return <View style={styles.hero} accessibilityLiveRegion="polite">
    <View style={styles.heroIcon}>
      <Ionicons color={colors.ink} name={icon} size={40} />
    </View>
    <Text accessibilityRole="header" style={styles.heroTitle}>{title}</Text>
    <Text style={styles.heroSubtitle}>{t("clientOrders.heroSubtitle", {
      name: clientDisplayName(order.cook_display_name), number: shortOrderNumber(order.id),
    })}</Text>
  </View>;
}

function ReviewPromptCard({ order, onReview, renderReview }: { order: OrderHistory; onReview: (order: OrderHistory, rating?: number) => void; renderReview?: (order: OrderHistory) => ReactNode }) {
  if (!["completed", "picked_up"].includes(order.status)) return null;
  const form = !order.review_id && renderReview?.(order);
  if (form) return <>{form}</>;
  const publishedStars = "★".repeat(order.review_rating ?? 0).padEnd(5, "☆").split("").join(" ");
  return <View style={styles.reviewCard}>
    <Text style={styles.heading}>{order.review_id ? t("reviews.thanks") : t("reviews.title")}</Text>
    {!order.review_id && <Text style={styles.body}>{t("reviews.invitationBody")}</Text>}
    {order.review_id ? <Text style={styles.stars} accessibilityLabel={t("reviews.starsPreview")}>{publishedStars}</Text> :
      <View style={styles.starsRow} accessibilityLabel={t("reviews.starsPreview")}>{[1, 2, 3, 4, 5].map((value) =>
        <Pressable key={value} accessibilityRole="radio" accessibilityLabel={t("clientExperience.rating", { rating: value })}
          onPress={() => onReview(order, value)} style={styles.star}>
          <Text style={styles.starText}>☆</Text>
        </Pressable>)}
      </View>}
    {order.review_id ? <View style={styles.stackSmall}>
      {!!order.review_comment && <Text style={styles.body}>{order.review_comment}</Text>}
      <Text style={styles.link}>{t("reviews.published")}</Text>
      <Text style={styles.muted}>{t("reviews.publishedBody")}</Text>
    </View> : <Pressable accessibilityRole="button" style={styles.primaryAction} onPress={() => onReview(order)}>
      <Text style={styles.primaryActionText}>{t("reviews.leaveReview")}</Text>
    </Pressable>}
  </View>;
}

export function OrderMessagesModal({ visible, order, messages, currentUserId, loading, error, draft, sending,
  onClose, onDraftChange, onSend, role = "customer" }: {
  visible: boolean; order: OrderHistory | null; messages: OrderMessage[]; currentUserId: string | null;
  loading: boolean; error: string | null; draft: string; sending: boolean; onClose: () => void;
  onDraftChange: (value: string) => void; onSend: () => void; role?: "customer" | "merchant";
}) {
  return <Modal visible={visible && !!order} animationType="slide" onRequestClose={onClose}>
    <View style={styles.messagesScreen}>
      <View style={styles.messagesHeader}>
        <Text style={styles.heading}>{t(role === "merchant" ? "orders.customerMessages" : "clientOrders.contactMerchant")}</Text>
        <Pressable accessibilityRole="button" onPress={onClose} style={styles.control}>
          <Text style={styles.link}>{t("clientOrderMessages.close")}</Text>
        </Pressable>
      </View>
      {role === "customer" && <Text style={styles.muted}>{order ? clientDisplayName(order.cook_display_name) : ""}</Text>}
      {loading && messages.length === 0 ? <ActivityIndicator color={colors.brandGreen} /> : <ScrollView style={styles.messagesList} contentContainerStyle={styles.messagesContent}>
        {messages.length === 0 && !error && <Text style={styles.muted}>{t("clientOrderMessages.empty")}</Text>}
        {messages.map((message) => <View key={message.id} style={[
          styles.messageBubble, (message.sender_role === role || message.sender_id === currentUserId) && styles.messageMine,
        ]}>
          <Text style={styles.messageText}>{message.body}</Text>
          <Text style={styles.messageTime}>{dateTime(message.created_at)}</Text>
        </View>)}
      </ScrollView>}
      {!!error && <Text accessibilityRole="alert" style={styles.error}>{error}</Text>}
      <View style={styles.messageComposer}>
        <TextInput accessibilityLabel={t("clientOrderMessages.input")} value={draft} onChangeText={onDraftChange}
          editable={!sending} multiline maxLength={230} placeholder={t("clientOrderMessages.placeholder")}
          style={styles.messageInput} />
        <Pressable accessibilityRole="button" accessibilityState={{ disabled: sending || !draft.trim(), busy: sending }}
          disabled={sending || !draft.trim()} onPress={onSend} style={[styles.messageSend, (sending || !draft.trim()) && styles.disabledAction]}>
          {sending ? <ActivityIndicator color={colors.warmCream} /> : <Text style={styles.messageSendText}>{t("clientOrderMessages.send")}</Text>}
        </Pressable>
      </View>
    </View>
  </Modal>;
}

export function ClientOrderDetail({ order, onReview, renderReview, helpExpanded = false, onToggleHelp = () => undefined,
  onRequestPickupCode, pickupCodeVisible = false, pickupCodeBusy = false, pickupActionError = null, onContactMerchant }: {
  order: OrderHistory; onReview: (order: OrderHistory, rating?: number) => void;
  renderReview?: (order: OrderHistory) => ReactNode;
  helpExpanded?: boolean; onToggleHelp?: () => void;
  onRequestPickupCode?: (order: OrderHistory) => void; pickupCodeVisible?: boolean; pickupCodeBusy?: boolean; pickupActionError?: string | null;
  onContactMerchant?: (order: OrderHistory) => void;
}) {
  const establishmentName = clientDisplayName(order.cook_display_name);
  const inProgress = ["ordered", "confirmed", "in_progress", "ready"].includes(order.status);
  return <View style={styles.stack}>
    {inProgress ? <OrderHero order={order} /> : <View style={styles.stackSmall}>
      <StatusBadge order={order} />
      <Text style={styles.title}>{t("clientOrders.detailTitle")}</Text>
    </View>}
    {inProgress && <ClientOrderProgress order={order} />}
    {order.status === "ready" && <View style={styles.readyPanel} accessibilityLiveRegion="polite">
      <Text style={styles.heading}>{t("clientOrders.readyTitle")}</Text>
      <View style={styles.pickupPlace}>
        <Ionicons color={colors.accent} name="location" size={22} />
        <Text style={styles.body}>{t("clientOrders.pickupAt", { name: establishmentName })}</Text>
      </View>
      {order.pickup_expires_at && <Text style={styles.muted}>{t("clientOrders.pickupUntil", { time: dateTime(order.pickup_expires_at) })}</Text>}
      <View style={styles.pickupAction}>
        {pickupCodeVisible && !!order.pickup_code && <View style={styles.pickupCode}>
          <Text style={styles.pickupCodeCaption}>{t("clientOrders.pickupCodeLabel")}</Text>
          <Text accessibilityLabel={t("clientOrders.pickupCodeLabel")} selectable style={styles.pickupCodeText}>{order.pickup_code}</Text>
          <Text style={styles.pickupCodeHint}>{t("clientOrders.pickupCodeInstructions")}</Text>
        </View>}
        <Pressable accessibilityRole="button" accessibilityLabel={t("clientOrders.showPickupCode")}
          accessibilityState={{ disabled: pickupCodeBusy || !onRequestPickupCode, busy: pickupCodeBusy }}
          disabled={pickupCodeBusy || !onRequestPickupCode}
          onPress={() => onRequestPickupCode?.(order)} style={({ pressed }) => [styles.pickupButton, pressed && styles.pressed]}>
          {pickupCodeBusy ? <ActivityIndicator color={colors.accent} /> : <Ionicons color={colors.accent} name="qr-code-outline" size={20} />}
          <Text style={styles.pickupButtonLabel}>{t("clientOrders.showPickupCode")}</Text>
        </Pressable>
        {!!pickupActionError && <Text accessibilityRole="alert" style={styles.error}>{pickupActionError}</Text>}
      </View>
    </View>}
    {(order.status === "picked_up" || order.status === "completed") && <View style={styles.notice} accessibilityLiveRegion="polite">
      <Text style={styles.heading}>{t("clientOrders.pickedUpTitle")}</Text>
      <Text style={styles.body}>{t("clientOrders.pickedUpBody")}</Text>
      {order.picked_up_at && <Text style={styles.muted}>{dateTime(order.picked_up_at)}</Text>}
    </View>}
    <View style={styles.card}>
      <Text style={styles.section}>{t("clientOrders.summary")}</Text>
      <Text style={styles.heading}>{establishmentName}</Text>
      <Text style={styles.caption}>{dateTime(order.created_at)}</Text>
      <View style={styles.footer}>
        <Text style={styles.heading}>{t("orders.total")}</Text>
        <Text style={styles.amount}>{formatMoney(order.total_price, order.currency)}</Text>
      </View>
    </View>
    <View style={styles.card}>
      <Text style={styles.section}>{t("clientOrders.items")}</Text>
      {orderLines(order).map((item) => <View key={item.id} style={styles.item}>
        <View style={styles.itemDescription}>
          <Text style={styles.itemName}>{item.dish_name}</Text>
          <Text style={styles.muted}>{t("orders.linePrice", { quantity: item.quantity, price: formatMoney(item.unit_price, order.currency) })}</Text>
        </View>
        <Text style={styles.lineAmount}>{formatMoney(item.line_total, order.currency)}</Text>
      </View>)}
    </View>
    {["ordered", "confirmed", "in_progress"].includes(order.status) && <View style={styles.pickup}>
      <Text style={styles.section}>{t("clientOrders.pickup")}</Text>
      <Text style={styles.heading}>{establishmentName}</Text>
      <Text style={styles.body}>{t("clientOrders.pickupOnSite")}</Text>
      {order.pickup_expires_at && <Text style={styles.muted}>{t("clientOrders.pickupUntil", { time: dateTime(order.pickup_expires_at) })}</Text>}
    </View>}
    {!inProgress && <ClientOrderProgress order={order} />}
    <Pressable accessibilityRole="button" onPress={() => onContactMerchant?.(order)}
      style={({ pressed }) => [styles.contactCard, pressed && styles.pressed]}>
      <Ionicons color={colors.ink} name="chatbubble-ellipses-outline" size={22} />
      <View style={[styles.stackSmall, styles.flexOne]}>
        <Text style={styles.section}>{t("clientOrders.contactMerchant")}</Text>
        <Text style={styles.muted}>{t("clientOrderMessages.contactHint")}</Text>
      </View>
      <Ionicons color={colors.ink} name="chevron-forward" size={18} />
    </Pressable>
    <ReviewPromptCard order={order} onReview={onReview} renderReview={renderReview} />
    <View style={styles.helpCard}>
      <Pressable accessibilityRole="button" accessibilityState={{ expanded: helpExpanded }}
        onPress={onToggleHelp} style={styles.helpHeader}>
        <Text style={styles.helpTitle}>{t("clientOrders.helpTitle")}</Text>
        <Text style={styles.helpToggle}>{helpExpanded ? "−" : "+"}</Text>
      </Pressable>
      {helpExpanded && <View style={styles.helpBody}>
        <Text style={styles.muted}>{t("clientExperience.helpIntro")}</Text>
        <OrderResolutionRequestCard order={order} hideHeading />
      </View>}
    </View>
  </View>;
}

export function ClientOrdersView({ orders, selected, history, loading, error, onOpen, onBack, onHistory, onRefresh, onReview, renderReview, helpExpanded, onToggleHelp,
  onRequestPickupCode, pickupCodeVisible, pickupCodeBusy, pickupActionError, onContactMerchant, messagesVisible, messages, currentUserId,
  messagesLoading, messagesError, messageDraft, messageSending, onCloseMessages, onMessageDraftChange, onSendMessage }: {
  orders: OrderHistory[]; selected: OrderHistory | null; history: boolean; loading: boolean; error: string | null;
  onOpen: (order: OrderHistory) => void; onBack: () => void; onHistory: (value: boolean) => void;
  onRefresh: () => void; onReview: (order: OrderHistory, rating?: number) => void;
  renderReview?: (order: OrderHistory) => ReactNode;
  helpExpanded?: boolean; onToggleHelp?: () => void;
  onRequestPickupCode?: (order: OrderHistory) => void; pickupCodeVisible?: boolean; pickupCodeBusy?: boolean; pickupActionError?: string | null;
  onContactMerchant?: (order: OrderHistory) => void; messagesVisible?: boolean; messages?: OrderMessage[]; currentUserId?: string | null;
  messagesLoading?: boolean; messagesError?: string | null; messageDraft?: string; messageSending?: boolean;
  onCloseMessages?: () => void; onMessageDraftChange?: (value: string) => void; onSendMessage?: () => void;
}) {
  return <View style={styles.stack}>
    <View style={styles.toolbar}>
      <Text style={styles.title}>{t("orders.title")}</Text>
      <Pressable accessibilityRole="button" disabled={loading} onPress={onRefresh} style={styles.control}>
        <Text style={styles.link}>{t("orders.refresh")}</Text>
      </Pressable>
    </View>
    {selected ? <View style={styles.detailToolbar}>
      <Pressable accessibilityRole="button" onPress={onBack} style={styles.control}>
        <Text style={styles.link}>{t("clientOrders.back")}</Text>
      </Pressable>
    </View> : <View style={styles.tabs}>{[false, true].map((value) => <Pressable key={String(value)}
      accessibilityRole="tab" accessibilityState={{ selected: history === value }} onPress={() => onHistory(value)}
      style={[styles.tab, history === value && styles.tabSelected]}>
      <Text style={history === value ? styles.tabActiveText : styles.muted}>{t(value ? "orders.history" : "orders.active")}</Text>
    </Pressable>)}</View>}
    {error ? <View style={styles.empty}>
      <Text style={styles.body} accessibilityRole="alert">{error}</Text>
      <Pressable accessibilityRole="button" disabled={loading} onPress={onRefresh} style={styles.control}><Text style={styles.link}>{t("clientOrders.retry")}</Text></Pressable>
    </View> : loading ? <View style={styles.empty}>
      <ActivityIndicator color={colors.brandGreen} />
      <Text style={styles.muted}>{t("clientOrders.loading")}</Text>
    </View> : selected ? <ClientOrderDetail order={selected} onReview={onReview} renderReview={renderReview}
      helpExpanded={helpExpanded} onToggleHelp={onToggleHelp} onRequestPickupCode={onRequestPickupCode}
      pickupCodeVisible={pickupCodeVisible} pickupCodeBusy={pickupCodeBusy} pickupActionError={pickupActionError}
      onContactMerchant={onContactMerchant} />
      : <ClientOrderList orders={orders} history={history} onOpen={onOpen} />}
    <OrderMessagesModal visible={!!messagesVisible} order={selected} messages={messages ?? []} currentUserId={currentUserId ?? null}
      loading={!!messagesLoading} error={messagesError ?? null} draft={messageDraft ?? ""} sending={!!messageSending}
      onClose={onCloseMessages ?? (() => undefined)} onDraftChange={onMessageDraftChange ?? (() => undefined)}
      onSend={onSendMessage ?? (() => undefined)} />
  </View>;
}

const styles = StyleSheet.create({
  stack: { gap: spacing.md },
  stackSmall: { gap: spacing.xs },
  title: { fontFamily: fonts.editorialBold, color: colors.darkCocoa, fontSize: 27, flexShrink: 1 },
  heading: { fontFamily: fonts.bold, color: colors.darkCocoa, fontSize: 18 },
  section: { fontFamily: fonts.bold, color: colors.brandGreen, fontSize: 15 },
  body: { fontFamily: fonts.regular, color: colors.darkCocoa, fontSize: 15, lineHeight: 23 },
  muted: { fontFamily: fonts.regular, color: colors.cocoaMuted, fontSize: 14, lineHeight: 21 },
  caption: { fontFamily: fonts.regular, color: colors.cocoaMuted, fontSize: 12 },
  link: { fontFamily: fonts.bold, color: colors.brandGreen, fontSize: 14 },
  amount: { fontFamily: fonts.extraBold, color: colors.brandGreen, fontSize: 20 },
  card: { gap: spacing.sm, padding: spacing.md, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.line, backgroundColor: colors.surface },
  footer: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", gap: spacing.xs, paddingTop: spacing.sm, borderTopWidth: StyleSheet.hairlineWidth, borderColor: colors.line },
  badge: { alignSelf: "flex-start", flexDirection: "row", alignItems: "center", gap: spacing.xs, paddingHorizontal: spacing.sm, paddingVertical: spacing.xxs, borderRadius: radius.pill, backgroundColor: colors.creamDeep, maxWidth: "100%" },
  badgeText: { fontFamily: fonts.semiBold, color: colors.brandGreen, fontSize: 13, flexShrink: 1 },
  dot: { width: 6, height: 6, borderRadius: 3, backgroundColor: colors.brandGreen },
  readyBadge: { backgroundColor: colors.brandGreen },
  readyText: { color: colors.warmCream },
  readyDot: { backgroundColor: colors.cornYellow },
  item: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: spacing.xs, paddingVertical: spacing.xs },
  itemDescription: { flexGrow: 1, flexShrink: 1, flexBasis: 170, gap: spacing.xxs },
  itemName: { fontFamily: fonts.semiBold, color: colors.darkCocoa, fontSize: 16 },
  lineAmount: { fontFamily: fonts.bold, color: colors.darkCocoa, fontSize: 15 },
  notice: { backgroundColor: colors.creamDeep, borderRadius: radius.md, padding: spacing.md, gap: spacing.xs },
  readyPanel: { gap: spacing.sm, padding: spacing.md, borderRadius: radius.lg, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.line },
  pickupPlace: { flexDirection: "row", alignItems: "center", gap: spacing.xs },
  contactCard: { flexDirection: "row", alignItems: "center", gap: spacing.sm, padding: spacing.md, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.line, backgroundColor: colors.surface },
  flexOne: { flex: 1 },
  hero: { alignItems: "center", gap: spacing.xs, paddingVertical: spacing.lg, paddingHorizontal: spacing.md, borderRadius: radius.xl, backgroundColor: colors.ink },
  heroIcon: { width: 84, height: 84, alignItems: "center", justifyContent: "center", borderRadius: 42, backgroundColor: colors.accent, marginBottom: spacing.xs },
  heroTitle: { color: colors.surface, fontFamily: fonts.extraBold, fontSize: 30, lineHeight: 36, letterSpacing: -0.8, textAlign: "center" },
  heroSubtitle: { color: "#D6D6D6", fontFamily: fonts.medium, fontSize: 15, textAlign: "center" },
  messagesScreen: { flex: 1, padding: spacing.md, paddingTop: spacing.lg, backgroundColor: colors.warmCream, gap: spacing.sm },
  messagesHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.xs },
  messagesList: { flex: 1 },
  messagesContent: { gap: spacing.sm, paddingVertical: spacing.sm },
  messageBubble: { maxWidth: "85%", alignSelf: "flex-start", padding: spacing.sm, borderRadius: radius.md, backgroundColor: colors.surface, gap: spacing.xxs },
  messageMine: { alignSelf: "flex-end", backgroundColor: colors.creamDeep },
  messageText: { fontFamily: fonts.regular, color: colors.darkCocoa, fontSize: 15 },
  messageTime: { fontFamily: fonts.regular, color: colors.cocoaMuted, fontSize: 11, alignSelf: "flex-end" },
  messageComposer: { flexDirection: "row", alignItems: "flex-end", gap: spacing.xs },
  messageInput: { flex: 1, maxHeight: 120, minHeight: 46, borderWidth: 1, borderColor: colors.line, borderRadius: radius.md, paddingHorizontal: spacing.sm, paddingVertical: spacing.xs, color: colors.darkCocoa, backgroundColor: colors.surface, fontFamily: fonts.regular },
  messageSend: { minHeight: 46, justifyContent: "center", alignItems: "center", paddingHorizontal: spacing.md, borderRadius: radius.md, backgroundColor: colors.brandGreen },
  messageSendText: { color: colors.warmCream, fontFamily: fonts.bold, fontSize: 14 },
  helpCard: { borderRadius: radius.lg, borderWidth: 1, borderColor: colors.line, backgroundColor: colors.surface, overflow: "hidden" },
  helpHeader: { minHeight: 52, flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.sm, paddingHorizontal: spacing.md },
  helpTitle: { flex: 1, fontFamily: fonts.semiBold, color: colors.darkCocoa, fontSize: 15 },
  helpToggle: { color: colors.brandGreen, fontFamily: fonts.bold, fontSize: 22 },
  helpBody: { gap: spacing.sm, paddingHorizontal: spacing.md, paddingBottom: spacing.md },
  detailToolbar: { gap: spacing.xs },
  reviewCard: { gap: spacing.sm, padding: spacing.md, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.mutedSage, backgroundColor: colors.surface },
  stars: { fontFamily: fonts.bold, color: colors.cornYellow, fontSize: 25, letterSpacing: 1 },
  starsRow: { flexDirection: "row", flexWrap: "wrap" },
  star: { minWidth: 44, minHeight: 44, alignItems: "center", justifyContent: "center" },
  starText: { color: colors.cornYellow, fontSize: 25 },
  pickup: { gap: spacing.xs, paddingHorizontal: spacing.xs },
  pickupAction: { gap: spacing.sm, paddingTop: spacing.xs },
  pickupButton: { minHeight: 56, flexDirection: "row", gap: spacing.xs, justifyContent: "center", alignItems: "center", borderRadius: radius.lg, backgroundColor: colors.ink, paddingHorizontal: spacing.md },
  pickupButtonLabel: { color: colors.surface, fontFamily: fonts.bold, fontSize: 16, textAlign: "center", flexShrink: 1 },
  pickupCode: { alignItems: "center", gap: spacing.xxs, padding: spacing.md, borderRadius: radius.lg, backgroundColor: colors.accentSoft },
  pickupCodeCaption: { color: colors.ink, fontFamily: fonts.medium, fontSize: 14 },
  pickupCodeText: { color: colors.ink, fontFamily: fonts.extraBold, fontSize: 44, lineHeight: 52, letterSpacing: 4 },
  pickupCodeHint: { color: colors.cocoaMuted, fontFamily: fonts.regular, fontSize: 13, lineHeight: 19, textAlign: "center" },
  error: { color: colors.error, fontFamily: fonts.regular, fontSize: 14 },
  step: { flexDirection: "row", alignItems: "flex-start", gap: spacing.sm },
  track: { width: 36, alignItems: "center" },
  stepDot: { width: 36, height: 36, borderRadius: 18, alignItems: "center", justifyContent: "center", borderWidth: 1.5, borderColor: colors.line, backgroundColor: colors.surface },
  stepReached: { borderColor: colors.accent, backgroundColor: colors.accent },
  connector: { width: 2, height: 18, backgroundColor: colors.line },
  connectorDone: { backgroundColor: colors.accent },
  stepCopy: { flex: 1, minHeight: 36, flexDirection: "row", alignItems: "center", gap: spacing.sm },
  stepText: { fontFamily: fonts.medium, fontSize: 15, color: colors.cocoaMuted },
  stepTextReached: { color: colors.ink },
  stepTextActive: { fontFamily: fonts.extraBold },
  stepTime: { fontFamily: fonts.regular, fontSize: 14, color: colors.cocoaMuted },
  empty: { alignItems: "center", paddingVertical: spacing.lg, paddingHorizontal: spacing.md, gap: spacing.sm },
  toolbar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.xs, flexWrap: "wrap" },
  control: { minHeight: 44, justifyContent: "center", alignSelf: "flex-start", paddingHorizontal: spacing.xs },
  tabs: { flexDirection: "row", padding: spacing.xxs, borderRadius: radius.md, backgroundColor: colors.creamDeep, gap: spacing.xxs },
  tab: { flex: 1, minHeight: 44, alignItems: "center", justifyContent: "center", borderRadius: radius.sm },
  tabSelected: { backgroundColor: colors.surface },
  tabActiveText: { color: colors.brandGreen, fontFamily: fonts.bold, fontSize: 14 },
  pressed: { opacity: 0.8 },
  primaryAction: { minHeight: 48, alignItems: "center", justifyContent: "center", alignSelf: "flex-start", paddingHorizontal: spacing.md, borderRadius: radius.pill, backgroundColor: colors.brandGreen },
  primaryActionText: { fontFamily: fonts.bold, color: colors.warmCream, fontSize: 14 },
  disabledAction: { opacity: 0.65 },
});
