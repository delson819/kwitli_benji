import { useEffect } from "react";
import { Image, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { clientDisplayName } from "../client-content";
import { t } from "../i18n";
import { mediaUrl } from "../config";
import { formatMoney } from "../format";
import { cartItemId, cartTotal, type CartItem } from "../order-actions";
import { orderTotal } from "../payment-flow";
import { resolvePaymentUiState } from "../payment-ui-state";
import type { DiscoverItem, MobileMoneyNetwork, Payment } from "../services/api";
import { colors } from "../theme/colors";
import { fonts } from "../theme/typography";
import { spacing } from "../theme/spacing";
import { radius } from "../theme/radius";
import { PaymentActions } from "./PaymentActions";

export function CartSummary({ lines, merchantName: merchantNameSource, payment, error, busy, onPay, onCheck, onOrders, onBack, onHome, network, phone, onNetwork, onPhone }: {
  lines: CartItem<DiscoverItem>[]; payment: Payment | null; error: string | null; busy: boolean;
  merchantName?: string | null;
  onPay: () => void; onCheck: () => void; onOrders: () => void; onBack: () => void;
  onHome?: () => void;
  network?: MobileMoneyNetwork | null; phone?: string;
  onNetwork?: (network: MobileMoneyNetwork) => void; onPhone?: (phone: string) => void;
}) {
  const showDevPaymentHelpers = typeof __DEV__ !== "undefined" && __DEV__;
  const paymentUiState = resolvePaymentUiState(payment, busy, error != null);
  useEffect(() => {
    if (__DEV__ && paymentUiState === "verifying" && payment?.id) {
      console.log("PAYMENT VERIFY UI OPEN", { payment_id: payment.id });
    }
  }, [payment?.id, paymentUiState]);
  const confirmedItemCount = (payment?.items ?? []).reduce((sum, item) => sum + item.quantity, 0);
  const merchantName = merchantNameSource
    ? clientDisplayName(merchantNameSource)
    : lines.length ? clientDisplayName(lines[0].item.cook_display_name) : null;
  if (paymentUiState === "approved" && payment) return <View style={styles.page}>
    <Text accessibilityRole="header" style={styles.title}>{t("clientExperience.confirmed")}</Text>
    {!!merchantName && <Text style={styles.text}>{t("clientExperience.received", { name: merchantName })}</Text>}
    {!!merchantName && <Text style={styles.name}>{merchantName}</Text>}
    <Text style={styles.text}>{t(confirmedItemCount === 1 ? "cart.itemsCountSingular" : "cart.itemsCountPlural", { count: confirmedItemCount })}</Text>
    <Text style={styles.name}>{formatMoney((payment.amount_in_cents / 100).toFixed(2), payment.currency)}</Text>
    <Pressable accessibilityRole="button" style={styles.confirmAction} onPress={onOrders}>
      <Text style={styles.confirmText}>{t("orders.title")}</Text>
    </Pressable>
    {onHome && <Pressable accessibilityRole="button" style={styles.back} onPress={onHome}><Text style={styles.link}>{t("clientExperience.home")}</Text></Pressable>}
  </View>;
  return <View style={styles.page}>
    <Text accessibilityRole="header" style={styles.title}>{t("checkout.summary")}</Text>
    {!!lines.length && <Text style={styles.name}>{clientDisplayName(lines[0].item.cook_display_name)}</Text>}
    {lines.map((line) => {
      const { item, quantity } = line;
      const total = formatMoney(orderTotal(item.price, quantity), item.currency);
      return <View key={cartItemId(item)} style={styles.card}>
        {item.photo_url && <Image source={{ uri: mediaUrl(item.photo_url) }} accessibilityLabel={t("dish.photoA11y", { dish: item.dish_name })} resizeMode="cover" style={styles.image} />}
        <Text style={styles.name}>{item.dish_name}</Text>
        <Text style={styles.text}>{t("order.quantity")}: {quantity}</Text>
        <Text style={styles.text}>{t("order.unitPrice")}: {formatMoney(item.price, item.currency)}</Text>
        <Text style={styles.name}>{t("order.subtotal")}: {total}</Text>

      </View>;
    })}
    {lines.length > 0 && <Text style={styles.name}>{t("cart.total")}: {formatMoney(cartTotal(lines), lines[0].item.currency)}</Text>}
    {lines[0]?.item.currency === "XOF" && (paymentUiState === "idle" || paymentUiState === "failed") && <View style={styles.card}>
      <Text style={styles.name}>{t("checkout.mobileMoneyMethod")}</Text>
      {(["WAVE", "ORANGEMONEY"] as const).map((option) => <Pressable key={option}
        accessibilityRole="radio" accessibilityState={{ checked: network === option, disabled: busy }}
        disabled={busy} onPress={() => onNetwork?.(option)} style={styles.back}>
        <Text style={network === option ? styles.link : styles.text}>
          {t(option === "WAVE" ? "checkout.wave" : "checkout.orangeMoney")}
          {network === option ? ` · ${t("checkout.methodSelected")}` : ""}
        </Text>
      </Pressable>)}
      <Text style={styles.text}>{t(showDevPaymentHelpers ? "checkout.testPhone" : "checkout.phone")}</Text>
      <TextInput value={phone ?? ""} onChangeText={onPhone} keyboardType="phone-pad"
        editable={!busy} maxLength={16} accessibilityLabel={t(showDevPaymentHelpers ? "checkout.testPhone" : "checkout.phone")}
        placeholder={t(showDevPaymentHelpers ? "checkout.testPhone" : "checkout.phone")} placeholderTextColor={colors.cocoaMuted}
        autoCorrect={false} textContentType="telephoneNumber"
        style={styles.phoneInput} />
      {showDevPaymentHelpers && <Text style={styles.text}>{t("checkout.flutterwaveTest")}</Text>}
    </View>}
    {lines.length > 0 && <PaymentActions payment={payment} uiState={paymentUiState} paymentError={error} paymentBusy={busy} onPay={onPay} onCheckPayment={onCheck} payTotal={formatMoney(cartTotal(lines), lines[0].item.currency)} />}
    <Pressable accessibilityRole="button" onPress={onBack} style={styles.back}><Text style={styles.link}>{t("cart.editCart")}</Text></Pressable>
  </View>;
}
const styles = StyleSheet.create({
  confirmAction: { minHeight: 48, alignItems: "center", justifyContent: "center", padding: spacing.sm, borderRadius: radius.md, backgroundColor: colors.brandGreen },
  confirmText: { color: colors.warmCream, fontFamily: fonts.bold, fontSize: 16 },
  page: { gap: spacing.sm }, card: { gap: spacing.xs, padding: spacing.sm, borderRadius: radius.lg, backgroundColor: colors.surface },
  title: { color: colors.darkCocoa, fontFamily: fonts.editorialSemiBold, fontSize: 28 },
  name: { color: colors.darkCocoa, fontFamily: fonts.bold, fontSize: 16 }, text: { color: colors.cocoaMuted, fontFamily: fonts.regular, fontSize: 14 },
  image: { width: 64, height: 64, borderRadius: radius.sm }, back: { minHeight: 44, justifyContent: "center" }, link: { color: colors.brandGreen, fontFamily: fonts.bold, fontSize: 14 },
  phoneInput: { minHeight: 48, paddingHorizontal: spacing.sm, paddingVertical: spacing.xs,
    borderWidth: 1, borderColor: colors.line, borderRadius: radius.sm,
    backgroundColor: colors.warmCream, color: colors.darkCocoa, fontFamily: fonts.regular, fontSize: 16 },
});
