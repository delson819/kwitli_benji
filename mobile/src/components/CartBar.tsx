import { Pressable, StyleSheet, Text, View } from "react-native";
import Ionicons from "@expo/vector-icons/Ionicons";
import { t } from "../i18n";
import { formatMoney } from "../format";
import { cartItemCount, cartTotal, type CartItem } from "../order-actions";
import type { DiscoverItem } from "../services/api";
import { colors } from "../theme/colors";
import { fonts } from "../theme/typography";
import { radius } from "../theme/radius";
import { spacing } from "../theme/spacing";

export function CartBar({ cart, onPress }: { cart: CartItem<DiscoverItem>[]; onPress: () => void }) {
  if (!cart.length) return null;
  const itemCount = cartItemCount(cart);
  return (
    <View style={styles.slot}>
      <Pressable accessibilityRole="button" onPress={onPress} style={({ pressed }) => [styles.bar, pressed && styles.pressed]}>
        <Ionicons name="bag-handle-outline" size={22} color={colors.surface} />
        <View style={styles.copy}>
          <Text style={styles.title}>{t("cart.view")}</Text>
          <Text style={styles.count}>{t(itemCount === 1 ? "cart.itemsCountSingular" : "cart.itemsCountPlural", { count: itemCount })}</Text>
        </View>
        <Text style={styles.total}>{formatMoney(cartTotal(cart), cart[0].item.currency)}</Text>
      </Pressable>
    </View>
  );
}
const styles = StyleSheet.create({
  slot: { flexShrink: 0, paddingHorizontal: spacing.sm, paddingVertical: spacing.xs, backgroundColor: colors.surface },
  bar: { minHeight: 58, paddingHorizontal: spacing.sm + 4, flexDirection: "row", alignItems: "center", gap: spacing.sm, borderRadius: radius.lg, backgroundColor: colors.ink },
  copy: { flex: 1 },
  title: { color: colors.surface, fontFamily: fonts.bold, fontSize: 16 },
  count: { color: "#CFCFCF", fontFamily: fonts.regular, fontSize: 12 },
  total: { color: colors.surface, fontFamily: fonts.extraBold, fontSize: 16 },
  pressed: { opacity: 0.85 },
});
