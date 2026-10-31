import { Image, Pressable, StyleSheet, Text, View } from "react-native";
import Ionicons from "@expo/vector-icons/Ionicons";
import { clientDisplayName } from "../client-content";
import { mediaUrl } from "../config";
import { formatMoney } from "../format";
import { t } from "../i18n";
import { cartItemId, cartTotal, type CartItem } from "../order-actions";
import { orderTotal } from "../payment-flow";
import type { DiscoverItem } from "../services/api";
import { colors } from "../theme/colors";
import { fonts } from "../theme/typography";
import { spacing } from "../theme/spacing";
import { radius } from "../theme/radius";
import { PrimaryButton } from "./PrimaryButton";

type Props = {
  cart: CartItem<DiscoverItem>[];
  onBack: () => void;
  onContinueShopping: () => void;
  onQuantity: (id: string, quantity: number) => void;
  onRemove: (id: string) => void;
  onContinue: () => void;
};
export function CartScreen({ cart, onBack, onContinueShopping, onQuantity, onRemove, onContinue }: Props) {
  const businessClosed = cart.some(({ item }) => !item.is_open);
  return (
    <View style={styles.page}>
      <Pressable accessibilityRole="button" onPress={onBack} style={styles.back}><Text style={styles.link}>{t("common.back")}</Text></Pressable>
      <Text accessibilityRole="header" style={styles.title}>{t("cart.title")}</Text>
      {!cart.length ? <Text style={styles.text}>{t("cart.empty")}</Text> : <>
        <Text style={styles.text}>{clientDisplayName(cart[0].item.cook_display_name)}</Text>
        {cart.map(({ item, quantity }) => (
          <View key={cartItemId(item)} style={styles.card}>
            <View style={styles.row}>
              {item.photo_url ? <Image source={{ uri: mediaUrl(item.photo_url) }} accessibilityLabel={t("dish.photoA11y", { dish: item.dish_name })} resizeMode="cover" style={styles.photo} /> : <View style={[styles.photo, styles.placeholder]}><Ionicons name="restaurant-outline" size={24} color={colors.brandGreen} /></View>}
              <View style={styles.copy}>
                <Text style={styles.name}>{item.dish_name}</Text>
                <Text style={styles.text}>{t("order.unitPrice")}: {formatMoney(item.price, item.currency)}</Text>
              </View>
            </View>
            <View style={styles.row}>
              <Pressable accessibilityRole="button" accessibilityLabel={t("detail.decreaseQuantity")} disabled={quantity <= 1} onPress={() => onQuantity(cartItemId(item), quantity - 1)} style={[styles.step, quantity <= 1 && styles.disabled]}><Ionicons name="remove" size={20} color={colors.brandGreen} /></Pressable>
              <Text style={styles.name}>{quantity}</Text>
              <Pressable accessibilityRole="button" accessibilityLabel={t("detail.increaseQuantity")} disabled={quantity >= 50} onPress={() => onQuantity(cartItemId(item), quantity + 1)} style={[styles.step, quantity >= 50 && styles.disabled]}><Ionicons name="add" size={20} color={colors.brandGreen} /></Pressable>
              <Pressable accessibilityRole="button" accessibilityLabel={t("cart.remove", { item: item.dish_name })} onPress={() => onRemove(cartItemId(item))} style={styles.step}><Ionicons name="trash-outline" size={20} color={colors.error} /></Pressable>
            </View>
            <Text style={styles.name}>{t("order.subtotal")}: {formatMoney(orderTotal(item.price, quantity), item.currency)}</Text>
          </View>
        ))}
        <Text style={styles.name}>{t("cart.total")}: {formatMoney(cartTotal(cart), cart[0].item.currency)}</Text>
        {businessClosed && <Text accessibilityRole="alert" style={styles.closed}>{t("clientExperience.businessClosedMessage")}</Text>}
        <PrimaryButton disabled={businessClosed} label={t("cart.continue")} onPress={onContinue} />
      </>}
      <Pressable accessibilityRole="button" onPress={onContinueShopping} style={styles.back}><Text style={styles.link}>{t("cart.continueShopping")}</Text></Pressable>
    </View>
  );
}
const styles = StyleSheet.create({
  page: { gap: spacing.sm }, back: { minHeight: 44, justifyContent: "center" },
  title: { color: colors.darkCocoa, fontFamily: fonts.editorialSemiBold, fontSize: 28 },
  link: { color: colors.brandGreen, fontFamily: fonts.bold, fontSize: 14 },
  text: { color: colors.cocoaMuted, fontFamily: fonts.regular, fontSize: 13 },
  closed: { color: colors.error, fontFamily: fonts.semiBold, fontSize: 14 },
  name: { color: colors.darkCocoa, fontFamily: fonts.bold, fontSize: 15 },
  card: { backgroundColor: colors.surface, padding: spacing.sm, borderRadius: radius.lg, gap: spacing.sm },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.xs }, copy: { flex: 1, gap: spacing.xs },
  photo: { width: 64, height: 64, borderRadius: radius.sm, backgroundColor: colors.creamDeep }, placeholder: { alignItems: "center", justifyContent: "center" },
  step: { minWidth: 44, minHeight: 44, alignItems: "center", justifyContent: "center", borderRadius: radius.sm, backgroundColor: colors.warmCream }, disabled: { opacity: 0.4 },
});
