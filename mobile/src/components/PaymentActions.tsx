import { StyleSheet, Text, View } from "react-native";
import { t } from "../i18n";
import { colors } from "../theme/colors";
import { fonts } from "../theme/typography";
import { spacing } from "../theme/spacing";
import type { Payment } from "../services/api";
import type { PaymentUiState } from "../payment-ui-state";
import { PrimaryButton } from "./PrimaryButton";

export type PaymentActionProps = {
  payment: Payment | null;
  uiState: PaymentUiState;
  paymentError: string | null;
  paymentBusy: boolean;
  onPay: () => void;
  onCheckPayment: () => void;
  payTotal: string;
};
export function PaymentActions({ payment, uiState, paymentError, paymentBusy, onPay, onCheckPayment, payTotal }: PaymentActionProps) {
  const showDevPaymentHelpers = typeof __DEV__ !== "undefined" && __DEV__;
  const resolutionMessage = payment?.status === "paid_stock_conflict"
    ? t("checkout.paidStockConflict")
    : payment?.status === "reconcile_required"
      ? t("checkout.reconcileRequired")
      : t("checkout.paymentResolutionRequired");
  return <View style={styles.actions}>
    {showDevPaymentHelpers && payment?.provider === "paydunya" && <Text style={styles.message}>{t("checkout.sandboxTest")}</Text>}
    {showDevPaymentHelpers && payment?.provider === "paytech" && <Text style={styles.message}>{t("checkout.paytechWarning")}</Text>}
    {uiState === "verifying" ? <>
      <Text accessibilityLiveRegion="polite" style={styles.message}>{t("clientExperience.verification")}</Text>
      <Text style={styles.secondaryMessage}>{t("clientExperience.verificationBody")}</Text>
      <PrimaryButton label={t("checkout.checkPayment")} loading={paymentBusy} onPress={onCheckPayment} />
    </> : uiState === "redirecting" ? <>
      <Text style={styles.message}>{t("clientExperience.redirect")}</Text>
      <PrimaryButton label={t("checkout.pay", { total: payTotal })} loading onPress={onPay} />
    </> : uiState === "failed" ? <>
      <Text accessibilityLiveRegion="polite" style={styles.error}>{paymentError ?? t("checkout.paymentFailed")}</Text>
      <PrimaryButton label={t("checkout.retryPayment", { total: payTotal })} onPress={onPay} />
    </> : uiState === "resolution_required" ? <Text accessibilityLiveRegion="polite" style={styles.error}>{resolutionMessage}</Text>
    : uiState === "idle" ? <>
      <Text style={styles.message}>{t("clientExperience.redirect")}</Text>
      <PrimaryButton label={t("checkout.pay", { total: payTotal })} onPress={onPay} />
    </> : null}
  </View>;
}
const styles = StyleSheet.create({
  actions: { gap: spacing.sm },
  error: { color: colors.error, fontFamily: fonts.medium, fontSize: 14 },
  message: { color: colors.brandGreen, fontFamily: fonts.medium, fontSize: 14 },
  secondaryMessage: { color: colors.cocoaMuted, fontFamily: fonts.regular, fontSize: 13 },
});
