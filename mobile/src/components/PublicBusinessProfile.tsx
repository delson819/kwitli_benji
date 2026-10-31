import Ionicons from "@expo/vector-icons/Ionicons";
import { Image, Pressable, StyleSheet, Text, View } from "react-native";

import { clientDescription, clientDisplayName } from "../client-content";
import { mediaUrl } from "../config";
import { formatMoney, formatRating, formatReviewDate } from "../format";
import { t } from "../i18n";
import type { PublicCookProfile } from "../services/api";
import { colors } from "../theme/colors";
import { radius } from "../theme/radius";
import { spacing } from "../theme/spacing";
import { fonts } from "../theme/typography";

export function PublicBusinessProfile({ profile, favorite, onFavorite, onBack, onOpen, busy }: {
  profile: PublicCookProfile;
  favorite: boolean;
  onFavorite: () => void;
  onBack: () => void;
  onOpen: (dishId: string) => void;
  busy: boolean;
}) {
  const displayName = clientDisplayName(profile.display_name);
  const initial = displayName.charAt(0).toLocaleUpperCase();
  const businessDescription = clientDescription(profile.bio);
  const availableDishes = Array.isArray(profile.available_dishes) ? profile.available_dishes : [];
  const recentReviews = Array.isArray(profile.recent_reviews) ? profile.recent_reviews : [];

  return <View style={styles.page}>
    <View style={styles.hero}>
      {profile.profile_photo_url ? <Image source={{ uri: mediaUrl(profile.profile_photo_url) }}
        resizeMode="cover" style={styles.banner} accessibilityLabel={displayName} />
        : <View style={[styles.banner, styles.bannerFallback]}>
          <Text style={styles.bannerInitial}>{initial}</Text>
          <Text style={styles.bannerFallbackText}>{t("clientExperience.localEstablishment")}</Text>
        </View>}
      <Pressable accessibilityLabel={t("common.back")} accessibilityRole="button" onPress={onBack}
        style={({ pressed }) => [styles.heroControl, styles.back, pressed && styles.pressed]}>
        <Ionicons color={colors.brandGreen} name="arrow-back" size={21} />
      </Pressable>
      <Pressable accessibilityLabel={t(favorite ? "favorites.remove" : "clientExperience.favorite")}
        accessibilityRole="button" onPress={onFavorite}
        style={({ pressed }) => [styles.heroControl, styles.favorite, pressed && styles.pressed]}>
        <Ionicons color={favorite ? colors.mangoOrange : colors.brandGreen}
          name={favorite ? "heart" : "heart-outline"} size={21} />
      </Pressable>
    </View>

    <View style={styles.intro}>
      <Text accessibilityRole="header" style={styles.title}>{displayName}</Text>
      {/* Sous-titre de la maquette : la description du commerce, sinon « Établissement local ». */}
      <View style={styles.eyebrowRow}>
        <Text numberOfLines={2} style={styles.eyebrow}>{businessDescription || t("clientExperience.localEstablishment")}</Text>
        {profile.is_verified && <View style={styles.verified}>
          <Ionicons color={colors.ink} name="checkmark-circle" size={15} />
          <Text style={styles.verifiedText}>{t("cookProfile.verified")}</Text>
        </View>}
      </View>
      <View style={styles.statusRow}>
        <View style={[styles.statusDot, !profile.is_open && styles.statusDotClosed]} />
        <Text style={[styles.businessStatus, !profile.is_open && styles.closedStatus]}>
          {t(profile.is_open ? "clientExperience.businessOpen" : "clientExperience.businessClosed")}
        </Text>
        {profile.rating_count > 0 && profile.rating_average !== null && <View style={styles.ratingInline}>
          <Text style={styles.metaSeparator}>·</Text>
          <Ionicons color={colors.accent} name="star" size={14} />
          <Text style={styles.metaText}>{formatRating(profile.rating_average)} · {t(profile.rating_count === 1 ? "reviews.countSingular" : "reviews.countPlural", { count: profile.rating_count })}</Text>
        </View>}
      </View>
    </View>

    <View style={styles.sectionHeader}>
      <Text accessibilityRole="header" style={styles.sectionTitle}>{t("clientExperience.menu")}</Text>
      <View style={styles.tabUnderline} />
    </View>

    {!availableDishes.length && <View style={styles.empty}>
      <Ionicons color={colors.brandGreen} name="restaurant-outline" size={25} />
      <Text style={styles.muted}>{t("clientExperience.menuEmpty")}</Text>
    </View>}

    <View style={styles.menuList}>{availableDishes.map((dish) => {
      const description = clientDescription(dish.description);
      return <Pressable
      key={dish.dish_id}
      accessibilityRole="button"
      accessibilityLabel={t("clientExperience.menuOpen", { name: dish.name })}
      accessibilityState={{ disabled: busy }}
      disabled={busy}
      onPress={() => onOpen(dish.dish_id)}
      style={({ pressed }) => [styles.menuCard, pressed && styles.pressed, busy && styles.disabled]}
    >
      {dish.photo_url ? <Image source={{ uri: mediaUrl(dish.photo_url) }} resizeMode="cover"
        style={styles.photo} accessibilityLabel={dish.name} />
        : <View style={[styles.photo, styles.photoFallback]}>
          <Ionicons color={colors.brandGreen} name="restaurant-outline" size={25} />
        </View>}
      <View style={styles.menuCopy}>
        <Text numberOfLines={2} style={styles.itemName}>{dish.name}</Text>
        {!!description && <Text numberOfLines={2} style={styles.itemDescription}>{description}</Text>}
        <View style={styles.itemFooter}>
          <Text style={styles.price}>{formatMoney(dish.price, dish.currency)}</Text>
          {/* Le « + » ouvre la fiche : le client y choisit la quantite avant l'ajout. */}
          <View style={styles.addButton}>
            <Ionicons color={colors.ink} name="add" size={22} />
          </View>
        </View>
      </View>
    </Pressable>;
    })}</View>

    {(profile.rating_count > 0 || recentReviews.length > 0) && <View style={styles.reviews}>
      <Text accessibilityRole="header" style={styles.sectionTitle}>{t("reviews.clientsTitle")}</Text>
      {recentReviews.map((review) => {
        const date = formatReviewDate(review.created_at);
        return <View key={review.id} style={styles.reviewCard}>
          <View style={styles.reviewRating}>
            <Ionicons color={colors.mangoOrange} name="star" size={16} />
            <Text style={styles.price}>{review.rating}/5</Text>
          </View>
          {!!review.comment && <Text style={styles.itemDescription}>{review.comment}</Text>}
          {!!date && <Text style={styles.itemDescription}>{date}</Text>}
        </View>;
      })}
    </View>}
  </View>;
}

const styles = StyleSheet.create({
  page: { gap: spacing.md },
  hero: { position: "relative", overflow: "hidden", borderRadius: radius.xl, backgroundColor: colors.creamDeep },
  banner: { width: "100%", aspectRatio: 1.25 },
  bannerFallback: { alignItems: "center", justifyContent: "center", gap: spacing.xs, backgroundColor: colors.creamDeep },
  bannerInitial: { color: colors.ink, fontFamily: fonts.extraBold, fontSize: 54 },
  bannerFallbackText: { color: colors.cocoaMuted, fontFamily: fonts.semiBold, fontSize: 13 },
  heroControl: { position: "absolute", top: spacing.sm, width: 46, height: 46, alignItems: "center", justifyContent: "center", borderRadius: radius.pill, backgroundColor: colors.surface,
    shadowColor: "#000", shadowOpacity: 0.12, shadowRadius: 8, shadowOffset: { width: 0, height: 2 }, elevation: 3 },
  back: { left: spacing.sm },
  favorite: { right: spacing.sm },
  intro: { gap: spacing.xxs + 2 },
  eyebrowRow: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: spacing.xs },
  eyebrow: { color: colors.cocoaMuted, fontFamily: fonts.medium, fontSize: 17 },
  verified: { flexDirection: "row", alignItems: "center", gap: spacing.xxs },
  verifiedText: { color: colors.ink, fontFamily: fonts.semiBold, fontSize: 12 },
  title: { color: colors.ink, fontFamily: fonts.extraBold, fontSize: 34, lineHeight: 40, letterSpacing: -1 },
  description: { color: colors.cocoaMuted, fontFamily: fonts.regular, fontSize: 15, lineHeight: 23 },
  statusRow: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: spacing.xxs + 2, paddingTop: spacing.xxs },
  statusDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: colors.open },
  statusDotClosed: { backgroundColor: colors.cocoaMuted },
  businessStatus: { color: colors.open, fontFamily: fonts.bold, fontSize: 15 },
  closedStatus: { color: colors.cocoaMuted },
  ratingInline: { flexDirection: "row", alignItems: "center", gap: spacing.xxs },
  metaSeparator: { color: colors.cocoaMuted, fontFamily: fonts.regular, fontSize: 15 },
  metaText: { color: colors.cocoaMuted, fontFamily: fonts.medium, fontSize: 14 },
  sectionHeader: { alignSelf: "flex-start", gap: spacing.xxs + 2, paddingTop: spacing.xs },
  sectionTitle: { color: colors.ink, fontFamily: fonts.extraBold, fontSize: 18 },
  tabUnderline: { height: 3, borderRadius: 2, backgroundColor: colors.accent },
  empty: { minHeight: 110, alignItems: "center", justifyContent: "center", gap: spacing.xs, padding: spacing.md, borderRadius: radius.lg, backgroundColor: colors.warmSurface },
  muted: { color: colors.cocoaMuted, fontFamily: fonts.regular, fontSize: 14, lineHeight: 21, textAlign: "center" },
  menuList: { borderTopWidth: 1, borderTopColor: colors.line },
  menuCard: { minHeight: 132, flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingVertical: spacing.sm, borderBottomWidth: 1, borderBottomColor: colors.line, backgroundColor: colors.surface },
  photo: { width: 104, height: 104, flexShrink: 0, borderRadius: radius.md, backgroundColor: colors.creamDeep },
  photoFallback: { alignItems: "center", justifyContent: "center" },
  menuCopy: { minWidth: 0, flex: 1, gap: spacing.xxs },
  itemName: { color: colors.ink, fontFamily: fonts.extraBold, fontSize: 17, lineHeight: 22 },
  itemDescription: { color: colors.cocoaMuted, fontFamily: fonts.regular, fontSize: 13, lineHeight: 19 },
  itemFooter: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.xs, paddingTop: spacing.xxs },
  price: { color: colors.ink, fontFamily: fonts.extraBold, fontSize: 16 },
  addButton: { width: 40, height: 40, alignItems: "center", justifyContent: "center", borderRadius: 20, backgroundColor: colors.accent },
  reviews: { gap: spacing.sm, paddingTop: spacing.xs },
  reviewCard: { gap: spacing.xs, padding: spacing.sm, borderRadius: radius.lg, backgroundColor: colors.surface },
  reviewRating: { flexDirection: "row", alignItems: "center", gap: spacing.xxs },
  pressed: { opacity: 0.78 },
  disabled: { opacity: 0.55 },
});
