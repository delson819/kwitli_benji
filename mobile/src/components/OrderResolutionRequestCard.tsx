import { useState } from "react";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { ApiError, createOrderResolutionRequest, type OrderHistory, type OrderResolutionReason } from "../services/api";
import { t } from "../i18n";
import { colors } from "../theme/colors";
import { fonts } from "../theme/typography";
import { radius } from "../theme/radius";
import { spacing } from "../theme/spacing";
import { PrimaryButton } from "./PrimaryButton";

const clientReasons = [
  "order_not_received", "incorrect_order", "item_missing", "excessive_delay",
  "quality_issue", "merchant_unavailable", "other",
] as const satisfies readonly OrderResolutionReason[];

const merchantReasons = [
  "ingredient_unavailable", "item_out_of_stock", "exceptional_closure",
  "menu_price_error", "technical_issue", "other",
] as const satisfies readonly OrderResolutionReason[];

const FINISHED_FOR_MERCHANT = ["picked_up", "completed", "cancelled"];

// Ne jamais afficher un code technique (NETWORK_ERROR, API_REQUEST_FAILED...) au client.
export function resolutionErrorMessage(cause: unknown): string {
  if (cause instanceof ApiError && cause.status === 409 && /deja en attente/i.test(cause.message)) {
    return t("orderResolution.alreadyPending");
  }
  return t("orderResolution.submitError");
}

export function OrderResolutionRequestCard({ order, hideHeading = false, role = "customer" }: {
  order: OrderHistory; hideHeading?: boolean; role?: "customer" | "merchant";
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState<OrderResolutionReason | null>(null);
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const merchant = role === "merchant";
  const reasons: readonly OrderResolutionReason[] = merchant ? merchantReasons : clientReasons;

  if (order.status === "cancelled" || (merchant && FINISHED_FOR_MERCHANT.includes(order.status))) return null;
  if (submitted) return <View style={styles.card}>
    <Text style={styles.title}>{t("orderResolution.submitted")}</Text>
    <Text style={styles.body}>{t("orderResolution.pendingBody")}</Text>
  </View>;

  async function submit() {
    if (!reason || !description.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      await createOrderResolutionRequest(order.id, { reason, description: description.trim() });
      setSubmitted(true);
      setOpen(false);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409 && /deja en attente/i.test(cause.message)) {
        // Une demande existe deja : l'afficher comme envoyee plutot qu'en erreur.
        setSubmitted(true);
        setOpen(false);
        return;
      }
      setError(resolutionErrorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  return <View style={styles.card}>
    {!hideHeading && <Text style={styles.title}>{t(merchant ? "orderResolution.merchantTitle" : "orderResolution.title")}</Text>}
    <Text style={styles.body}>{t(merchant ? "orderResolution.merchantBody" : "orderResolution.body")}</Text>
    {!open ? <Pressable accessibilityRole="button" onPress={() => setOpen(true)} style={styles.action}>
      <Text style={styles.actionButtonText}>{t(merchant ? "orderResolution.requestMerchantCancellation"
        : ["ordered", "confirmed"].includes(order.status) ? "orderResolution.requestCancellation" : "orderResolution.requestRefund")}</Text>
    </Pressable> : <View style={styles.form}>
      <Text style={styles.label}>{t("orderResolution.reasonLabel")}</Text>
      <View style={styles.reasons}>{reasons.map((item) => <Pressable key={item}
        accessibilityRole="radio" accessibilityState={{ checked: reason === item, disabled: busy }} disabled={busy}
        onPress={() => setReason(item)} style={[styles.reason, reason === item && styles.reasonSelected]}>
        <Text style={[styles.reasonText, reason === item && styles.reasonTextSelected]}>{t(`orderResolution.reasons.${item}`)}</Text>
      </Pressable>)}</View>
      <TextInput accessibilityLabel={t("orderResolution.descriptionLabel")} value={description}
        onChangeText={setDescription} editable={!busy} multiline maxLength={1000}
        placeholder={t("orderResolution.descriptionPlaceholder")} textAlignVertical="top" style={styles.input} />
      {!!error && <Text accessibilityRole="alert" style={styles.error}>{error}</Text>}
      <PrimaryButton label={t("orderResolution.submit")} disabled={!reason || !description.trim()}
        loading={busy} onPress={() => void submit()} />
      <Pressable accessibilityRole="button" disabled={busy} onPress={() => setOpen(false)} style={styles.cancel}>
        <Text style={styles.actionText}>{t("common.cancel")}</Text>
      </Pressable>
    </View>}
  </View>;
}

const styles = StyleSheet.create({
  card: { gap: spacing.sm, padding: spacing.md, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.line, backgroundColor: colors.surface },
  title: { fontFamily: fonts.bold, color: colors.darkCocoa, fontSize: 18 },
  body: { fontFamily: fonts.regular, color: colors.cocoaMuted, fontSize: 14, lineHeight: 21 },
  action: { minHeight: 46, justifyContent: "center", alignItems: "center", borderRadius: radius.md, backgroundColor: colors.brandGreen, paddingHorizontal: spacing.md },
  actionText: { fontFamily: fonts.bold, color: colors.brandGreen, fontSize: 14 },
  actionButtonText: { fontFamily: fonts.bold, color: colors.warmCream, fontSize: 14 },
  form: { gap: spacing.sm },
  label: { fontFamily: fonts.semiBold, color: colors.darkCocoa, fontSize: 14 },
  reasons: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs },
  reason: { borderWidth: 1, borderColor: colors.line, borderRadius: radius.pill, paddingVertical: spacing.xs, paddingHorizontal: spacing.sm },
  reasonSelected: { borderColor: colors.brandGreen, backgroundColor: colors.creamDeep },
  reasonText: { fontFamily: fonts.medium, color: colors.darkCocoa, fontSize: 13 },
  reasonTextSelected: { color: colors.brandGreen },
  input: { minHeight: 92, borderWidth: 1, borderColor: colors.line, borderRadius: radius.md, padding: spacing.sm, color: colors.darkCocoa, fontFamily: fonts.regular },
  error: { color: colors.error, fontFamily: fonts.regular, fontSize: 14 },
  cancel: { minHeight: 44, justifyContent: "center", alignItems: "center" },
});
