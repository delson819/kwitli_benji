import { Image, Pressable, StyleSheet, Text, View } from "react-native";
import Ionicons from "@expo/vector-icons/Ionicons";

import { clientDescription, clientDisplayName } from "../client-content";
import { mediaUrl } from "../config";
import { formatDistance, formatMoney, formatRating } from "../format";
import { t } from "../i18n";
import { boundedQuantity } from "../order-actions";
import { orderTotal, validQuantity } from "../payment-flow";
import type { DiscoverItem } from "../services/api";
import { colors } from "../theme/colors";
import { radius } from "../theme/radius";
import { spacing } from "../theme/spacing";
import { fontSizes, fonts } from "../theme/typography";
import { PrimaryButton } from "./PrimaryButton";

type Props = {
  dish: DiscoverItem;
  quantity: string;
  cartQuantity: number;
  hasCart: boolean;
  onContinueShopping: () => void;
  replacementPending: boolean;
  onCancelReplacement: () => void;
  onConfirmReplacement: () => void;
  favorite: boolean;
  onBack: () => void;
  onOpenCook: () => void;
  onToggleFavorite: () => void;
  onQuantityChange: (quantity: string) => void;
  onAddToCart: (quantity: number) => void;
};

export function DishDetail({
  dish,
  quantity,
  cartQuantity,
  hasCart,
  onContinueShopping,
  replacementPending,
  onCancelReplacement,
  onConfirmReplacement,
  favorite,
  onBack,
  onOpenCook,
  onToggleFavorite,
  onQuantityChange,
  onAddToCart,
}: Props) {
  const selectedQuantity = validQuantity(quantity);
  const quantityValue = boundedQuantity(selectedQuantity ?? 1);
  const total = orderTotal(dish.price, quantityValue);
  const hasRating = dish.review_count > 0 && dish.rating_average !== null && Number(dish.rating_average) > 0;
  const description = clientDescription(dish.description);
  const establishmentName = clientDisplayName(dish.cook_display_name);

  function updateQuantity(next: number) {
    onQuantityChange(String(boundedQuantity(next)));
  }

  return (
    <View style={styles.detail}>
      <View style={styles.hero}>
        {dish.photo_url ? (
          <Image
            accessibilityLabel={t("dish.photoA11y", { dish: dish.dish_name })}
            resizeMode="cover"
            source={{ uri: mediaUrl(dish.photo_url) }}
            style={styles.heroImage}
          />
        ) : (
          <View style={[styles.heroImage, styles.heroFallback]}>
            <View style={styles.fallbackIcon}>
              <Ionicons color={colors.warmCream} name="restaurant-outline" size={32} />
            </View>
            <Text style={styles.fallbackTitle}>{t("clientExperience.photoTitle")}</Text>
            <Text style={styles.fallbackText}>{t("clientExperience.photoBody")}</Text>
          </View>
        )}
        <Pressable
          accessibilityLabel={t("dish.backA11y")}
          accessibilityRole="button"
          onPress={onBack}
          style={({ pressed }) => [styles.heroButton, styles.backButton, pressed && styles.pressed]}
        >
          <Ionicons color={colors.brandGreen} name="arrow-back" size={22} />
        </Pressable>
        <Pressable
          accessibilityLabel={favorite ? t("favorites.remove") : t("clientExperience.favorite")}
          accessibilityRole="button"
          onPress={onToggleFavorite}
          style={({ pressed }) => [styles.heroButton, styles.favoriteButton, pressed && styles.pressed]}
        >
          <Ionicons color={favorite ? colors.mangoOrange : colors.brandGreen} name={favorite ? "heart" : "heart-outline"} size={22} />
        </Pressable>
      </View>

      <View style={styles.content}>
        <View style={styles.titleBlock}>
          <Text style={styles.title}>{dish.dish_name}</Text>
          <Text style={styles.price}>{formatMoney(dish.price, dish.currency)}</Text>
        </View>
        {!dish.is_open && <Text accessibilityRole="alert" style={styles.closedMessage}>{t("clientExperience.businessClosedMessage")}</Text>}

        <Pressable
          accessibilityLabel={t("dish.cookA11y", { cook: establishmentName })}
          accessibilityRole="button"
          onPress={onOpenCook}
          style={({ pressed }) => [styles.cookCard, pressed && styles.pressed]}
        >
          {dish.profile_photo_url ? (
            <Image
              accessibilityLabel={establishmentName}
              resizeMode="cover"
              source={{ uri: mediaUrl(dish.profile_photo_url) }}
              style={styles.avatar}
            />
          ) : (
            <View style={styles.avatar}>
              <Text style={styles.avatarText}>{establishmentName.charAt(0).toLocaleUpperCase()}</Text>
            </View>
          )}
          <View style={styles.cookCopy}>
            <Text style={styles.cookEyebrow}>{t("clientExperience.establishment")}</Text>
            <Text style={styles.cookName}>{establishmentName}</Text>
          </View>
          {hasRating && (
            <View style={styles.rating}>
              <Ionicons color={colors.cornYellow} name="star" size={15} />
              <Text style={styles.ratingText}>{formatRating(dish.rating_average!)} · {t(dish.review_count === 1 ? "reviews.countSingular" : "reviews.countPlural", { count: dish.review_count })}</Text>
            </View>
          )}
          <Ionicons color={colors.brandGreen} name="chevron-forward" size={18} />
        </Pressable>

        {!!description && <Text style={styles.description}>{description}</Text>}

        <View style={styles.factGrid}>
          {dish.distance_km !== null && (
            <View style={styles.fact}>
              <Ionicons color={colors.brandGreen} name="navigate-outline" size={18} />
              <Text style={styles.factLabel}>{t("label.distance")}</Text>
              <Text style={styles.factValue}>{t("dish.distance", { distance: formatDistance(dish.distance_km) })}</Text>
            </View>
          )}
        </View>

        <>
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>{t("order.quantity")}</Text>
              <View style={styles.quantityControl}>
                <Pressable
                  accessibilityLabel={t("detail.decreaseQuantity")}
                  accessibilityRole="button"
                  accessibilityState={{ disabled: quantityValue <= 1 }}
                  disabled={quantityValue <= 1}
                  onPress={() => updateQuantity(quantityValue - 1)}
                  style={({ pressed }) => [styles.quantityButton, quantityValue <= 1 && styles.disabled, pressed && styles.pressed]}
                >
                  <Ionicons color={colors.brandGreen} name="remove" size={22} />
                </Pressable>
                <Text accessibilityLiveRegion="polite" style={styles.quantity}>{quantityValue}</Text>
                <Pressable
                  accessibilityLabel={t("detail.increaseQuantity")}
                  accessibilityRole="button"
                  accessibilityState={{ disabled: quantityValue >= 50 }}
                  disabled={quantityValue >= 50}
                  onPress={() => updateQuantity(quantityValue + 1)}
                  style={({ pressed }) => [styles.quantityButton, quantityValue >= 50 && styles.disabled, pressed && styles.pressed]}
                >
                  <Ionicons color={colors.brandGreen} name="add" size={22} />
                </Pressable>
              </View>
            </View>

            {cartQuantity > 0 && (
              <View accessibilityLiveRegion="polite" style={styles.cartNotice}>
                <Ionicons color={colors.brandGreen} name="checkmark-circle" size={19} />
                <Text style={styles.cartNoticeText}>{t(cartQuantity === 1 ? "cart.inCartQuantitySingular" : "cart.inCartQuantityPlural", { quantity: cartQuantity })}</Text>
              </View>
            )}

            {replacementPending ? (
              <View accessibilityViewIsModal style={styles.summary}>
                <Text accessibilityRole="header" style={styles.sectionTitle}>{t("cart.replaceTitle")}</Text>
                <Text style={styles.summaryNote}>{t("cart.replaceBody")}</Text>
                <Pressable accessibilityRole="button" onPress={onCancelReplacement} style={styles.secondaryAction}>
                  <Text style={styles.secondaryActionText}>{t("cart.cancel")}</Text>
                </Pressable>
                <PrimaryButton label={t("cart.replace")} onPress={onConfirmReplacement} />
              </View>
            ) : <View style={styles.actions}>
              <PrimaryButton accessibilityLabel={t("cart.add")}
                icon="bag-add-outline"
                disabled={!dish.is_open}
                label={t("cart.addWithTotal", { total: formatMoney(total, dish.currency) })}
                onPress={() => onAddToCart(quantityValue)} />
              {hasCart && <>
                <Pressable accessibilityRole="button" onPress={onContinueShopping} style={styles.secondaryAction}>
                  <Text style={styles.secondaryActionText}>{t("cart.continueShopping")}</Text>
                </Pressable>
              </>}
            </View>}
          </>

      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  detail: { gap: 0 },
  hero: { position: "relative", overflow: "hidden", width: "100%", aspectRatio: 1.05, borderRadius: radius.xl, backgroundColor: colors.creamDeep },
  heroImage: { width: "100%", height: "100%" },
  heroFallback: { alignItems: "center", justifyContent: "center", gap: spacing.xs, backgroundColor: colors.mutedSage },
  fallbackIcon: { width: 56, height: 56, alignItems: "center", justifyContent: "center", borderRadius: radius.pill, backgroundColor: colors.brandGreen },
  fallbackTitle: { color: colors.darkCocoa, fontFamily: fonts.editorialSemiBold, fontSize: 22 },
  fallbackText: { color: colors.darkCocoa, fontFamily: fonts.medium, fontSize: 13 },
  heroButton: { position: "absolute", top: spacing.sm, width: 46, height: 46, alignItems: "center", justifyContent: "center", borderRadius: radius.pill, backgroundColor: colors.surface },
  backButton: { left: spacing.sm },
  favoriteButton: { right: spacing.sm },
  content: { gap: spacing.md, paddingTop: spacing.md },
  titleBlock: { gap: spacing.xs },
  title: { color: colors.darkCocoa, fontFamily: fonts.editorialSemiBold, fontSize: 36, lineHeight: 42 },
  description: { color: colors.cocoaMuted, fontFamily: fonts.regular, fontSize: 16, lineHeight: 25 },
  closedMessage: { color: colors.cocoaMuted, fontFamily: fonts.semiBold, fontSize: 14 },
  cookCard: { flexDirection: "row", alignItems: "center", gap: 11, borderWidth: 1, borderColor: colors.line, borderRadius: radius.lg, backgroundColor: colors.surface, padding: 14 },
  avatar: { width: 46, height: 46, alignItems: "center", justifyContent: "center", borderRadius: radius.pill, backgroundColor: colors.mutedSage },
  avatarText: { color: colors.brandGreen, fontFamily: fonts.extraBold, fontSize: 16 },
  cookCopy: { flex: 1 },
  cookEyebrow: { color: colors.cocoaMuted, fontFamily: fonts.medium, fontSize: 11, textTransform: "uppercase", letterSpacing: 1 },
  cookName: { marginTop: 2, color: colors.darkCocoa, fontFamily: fonts.bold, fontSize: 15 },
  rating: { flexDirection: "row", alignItems: "center", gap: 4 },
  ratingText: { color: colors.darkCocoa, fontFamily: fonts.bold, fontSize: 13 },
  factGrid: { flexDirection: "row", gap: spacing.xs },
  fact: { flex: 1, minHeight: 96, justifyContent: "space-between", borderRadius: radius.lg, backgroundColor: colors.creamDeep, padding: 13 },
  factLabel: { color: colors.cocoaMuted, fontFamily: fonts.medium, fontSize: 11 },
  factValue: { color: colors.darkCocoa, fontFamily: fonts.bold, fontSize: 13 },
  eyebrow: { color: colors.cocoaMuted, fontFamily: fonts.medium, fontSize: 11, textTransform: "uppercase", letterSpacing: 1 },
  price: { color: colors.brandGreen, fontFamily: fonts.extraBold, fontSize: 22 },
  section: { gap: spacing.sm },
  sectionTitle: { color: colors.darkCocoa, fontFamily: fonts.editorialSemiBold, fontSize: fontSizes.cardTitle },
  quantityControl: { alignSelf: "flex-start", flexDirection: "row", alignItems: "center", gap: spacing.md, borderRadius: radius.pill, backgroundColor: colors.surface, padding: 6 },
  quantityButton: { width: 44, height: 44, alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: colors.line, borderRadius: radius.pill, backgroundColor: colors.warmCream },
  quantity: { minWidth: 24, textAlign: "center", color: colors.darkCocoa, fontFamily: fonts.extraBold, fontSize: 18 },
  disabled: { opacity: 0.35 },
  summary: { gap: 12, borderRadius: radius.lg, backgroundColor: colors.surface, padding: spacing.sm },
  summaryHeading: { flex: 1 },
  summaryItem: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  summaryThumbnail: { width: 64, height: 64, borderRadius: radius.sm, backgroundColor: colors.creamDeep },
  summaryPlaceholder: { alignItems: "center", justifyContent: "center" },
  summaryItemCopy: { flex: 1, gap: spacing.xxs },
  summaryItemName: { color: colors.darkCocoa, fontFamily: fonts.bold, fontSize: 15 },
  summaryHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.sm },
  summaryClose: { width: 44, height: 44, alignItems: "center", justifyContent: "center", borderRadius: radius.pill, backgroundColor: colors.warmCream },
  summaryRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.sm },
  summaryLabel: { color: colors.cocoaMuted, fontFamily: fonts.regular, fontSize: 13 },
  summaryValue: { flex: 1, textAlign: "right", color: colors.darkCocoa, fontFamily: fonts.semiBold, fontSize: 13 },
  totalRow: { borderTopWidth: 1, borderTopColor: colors.line, paddingTop: 12 },
  totalLabel: { color: colors.darkCocoa, fontFamily: fonts.bold, fontSize: 15 },
  totalValue: { color: colors.brandGreen, fontFamily: fonts.extraBold, fontSize: 18 },
  actions: { gap: spacing.xs },
  secondaryAction: { minHeight: 48, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.xs, borderWidth: 1, borderColor: colors.brandGreen, borderRadius: radius.md, backgroundColor: colors.surface, paddingHorizontal: spacing.sm },
  secondaryActionText: { color: colors.brandGreen, fontFamily: fonts.bold, fontSize: 15 },
  cartNotice: { flexDirection: "row", alignItems: "center", gap: spacing.xs, borderRadius: radius.md, backgroundColor: colors.accentSoft, padding: 14 },
  cartNoticeText: { flex: 1, color: colors.brandGreen, fontFamily: fonts.semiBold, fontSize: 13 },
  summaryNote: { color: colors.cocoaMuted, fontFamily: fonts.regular, fontSize: 12, lineHeight: 18 },
  pressed: { opacity: 0.72 },
});
