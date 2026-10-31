import { Image, Pressable, StyleSheet, Text, View } from "react-native";
import Ionicons from "@expo/vector-icons/Ionicons";
import { clientDisplayName } from "../client-content";
import { mediaUrl } from "../config";
import { formatDistance, formatMoney, formatRating } from "../format";
import { t } from "../i18n";
import type { DiscoverItem } from "../services/api";
import { colors } from "../theme/colors";
import { fonts } from "../theme/typography";
import { radius } from "../theme/radius";
import { spacing } from "../theme/spacing";

// Carte « À deux pas » : grande photo, nom, note, distance et prix de depart.
export function BusinessDiscoveryCard({ items, onPress }: { items: DiscoverItem[]; onPress: () => void }) {
  const first = items[0];
  if (!first) return null;
  const name = clientDisplayName(first.cook_display_name);
  const photo = first.profile_photo_url ?? items.find((item) => item.photo_url)?.photo_url ?? null;
  const prices = items.map((item) => Number(item.price)).filter((value) => Number.isFinite(value) && value > 0);
  const fromPrice = prices.length ? Math.min(...prices) : null;
  const rated = first.rating_average != null && Number(first.review_count) > 0;

  return <Pressable accessibilityRole="button" accessibilityLabel={t("clientExperience.openBusiness", { name })}
    onPress={onPress} style={({ pressed }) => [styles.card, pressed && styles.pressed]}>
    {photo ? <Image source={{ uri: mediaUrl(photo) }} resizeMode="cover" accessibilityLabel={name} style={styles.image} />
      : <View style={[styles.image, styles.fallback]}>
        <Ionicons color={colors.cocoaMuted} name="restaurant-outline" size={34} />
      </View>}
    {!first.is_open && <View style={styles.closedBadge}>
      <Text style={styles.closedBadgeText}>{t("clientExperience.businessClosed")}</Text>
    </View>}
    <View style={styles.titleRow}>
      <Text numberOfLines={1} style={styles.name}>{name}</Text>
      {fromPrice !== null && <Text style={styles.fromPrice}>{t("clientExperience.fromPrice", { price: formatMoney(fromPrice, first.currency) })}</Text>}
    </View>
    <View style={styles.metaRow}>
      {rated && <>
        <Ionicons color={colors.accent} name="star" size={14} />
        <Text style={styles.metaStrong}>{formatRating(first.rating_average as string)}</Text>
      </>}
      {first.distance_km !== null && <>
        {rated && <Text style={styles.meta}>·</Text>}
        <Text style={styles.meta}>{t("dish.distance", { distance: formatDistance(first.distance_km) })}</Text>
      </>}
      <View style={styles.spacer} />
      <Text style={styles.action}>{t("clientExperience.openMenu")}</Text>
      <Ionicons color={colors.ink} name="chevron-forward" size={14} />
    </View>
  </Pressable>;
}

const styles = StyleSheet.create({
  card: { gap: spacing.xxs + 2 },
  image: { width: "100%", aspectRatio: 1.7, borderRadius: radius.lg, backgroundColor: colors.creamDeep },
  fallback: { alignItems: "center", justifyContent: "center" },
  closedBadge: { position: "absolute", top: spacing.xs + 4, left: spacing.xs + 4, paddingHorizontal: spacing.xs + 2, paddingVertical: spacing.xxs, borderRadius: radius.pill, backgroundColor: colors.ink },
  closedBadgeText: { color: colors.surface, fontFamily: fonts.bold, fontSize: 12 },
  titleRow: { flexDirection: "row", alignItems: "baseline", justifyContent: "space-between", gap: spacing.xs, paddingTop: spacing.xxs },
  name: { flex: 1, color: colors.ink, fontFamily: fonts.extraBold, fontSize: 20, letterSpacing: -0.3 },
  fromPrice: { color: colors.ink, fontFamily: fonts.bold, fontSize: 14 },
  metaRow: { flexDirection: "row", alignItems: "center", gap: spacing.xxs },
  metaStrong: { color: colors.ink, fontFamily: fonts.semiBold, fontSize: 14 },
  meta: { color: colors.cocoaMuted, fontFamily: fonts.regular, fontSize: 14 },
  spacer: { flex: 1 },
  action: { color: colors.ink, fontFamily: fonts.semiBold, fontSize: 13 },
  pressed: { opacity: 0.85 },
});
