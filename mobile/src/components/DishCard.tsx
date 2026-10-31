import { useEffect, useRef, useState } from "react";
import { Animated, Image, Pressable, StyleSheet, Text, useWindowDimensions, View } from "react-native";
import Ionicons from "@expo/vector-icons/Ionicons";

import { clientDisplayName } from "../client-content";
import { mediaUrl } from "../config";
import { formatDistance, formatMoney, formatRating } from "../format";
import { t } from "../i18n";
import type { DiscoverItem } from "../services/api";
import { useReducedMotion } from "../hooks/useReducedMotion";
import { colors } from "../theme/colors";
import { breakpoints, controlSizes, iconSizes } from "../theme/layout";
import { radius } from "../theme/radius";
import { spacing } from "../theme/spacing";
import { fontSizes, fonts, lineHeights } from "../theme/typography";

type Props = {
  dish: DiscoverItem;
  index?: number;
  onPress: () => void;
};

export function DishCard({ dish, index = 0, onPress }: Props) {
  const { width } = useWindowDimensions();
  const compact = width < breakpoints.compactPhone;
  const reducedMotion = useReducedMotion();
  const entrance = useRef(new Animated.Value(0)).current;
  const [imageFailed, setImageFailed] = useState(false);
  const [establishmentImageFailed, setEstablishmentImageFailed] = useState(false);
  const hasRating = dish.review_count > 0 && dish.rating_average !== null && Number(dish.rating_average) > 0;
  const establishmentName = clientDisplayName(dish.cook_display_name);
  const initial = establishmentName.charAt(0).toLocaleUpperCase();

  useEffect(() => {
    if (reducedMotion) {
      entrance.setValue(1);
      return undefined;
    }

    entrance.setValue(0);
    const animation = Animated.timing(entrance, {
      delay: Math.min(index * 60, 240),
      duration: 280,
      toValue: 1,
      useNativeDriver: true,
    });
    animation.start();
    return () => animation.stop();
  }, [entrance, index, reducedMotion]);

  useEffect(() => {
    setImageFailed(false);
  }, [dish.photo_url]);

  useEffect(() => {
    setEstablishmentImageFailed(false);
  }, [dish.profile_photo_url]);

  return (
    <Animated.View
      style={[
        styles.entrance,
        {
          opacity: entrance,
          transform: [{ translateY: entrance.interpolate({ inputRange: [0, 1], outputRange: [spacing.sm, 0] }) }],
        },
      ]}
    >
      <Pressable
        accessibilityLabel={t("dish.openA11y", { dish: dish.dish_name })}
        accessibilityRole="button"
        onPress={onPress}
        style={({ pressed }) => [styles.card, compact && styles.cardCompact, pressed && styles.pressed]}
      >
        <View style={[styles.imageWrap, compact && styles.imageWrapCompact]}>
          {dish.photo_url && !imageFailed ? (
            <Image
              accessibilityLabel={t("dish.photoA11y", { dish: dish.dish_name })}
              onError={() => setImageFailed(true)}
              resizeMode="cover"
              source={{ uri: mediaUrl(dish.photo_url) }}
              style={styles.image}
            />
          ) : (
            <View style={[styles.image, styles.imageFallback]}>
              <View style={styles.fallbackIcon}>
                <Ionicons color={colors.brandGreen} name="restaurant-outline" size={iconSizes.large} />
              </View>
              <Text style={styles.fallbackTitle}>{t("clientExperience.photoTitle")}</Text>
            </View>
          )}
        </View>

        <View style={styles.body}>
          <Text numberOfLines={2} style={styles.title}>{dish.dish_name}</Text>

          <View style={styles.cookRow}>
            {dish.profile_photo_url && !establishmentImageFailed ? (
              <Image
                accessibilityLabel={establishmentName}
                onError={() => setEstablishmentImageFailed(true)}
                resizeMode="cover"
                source={{ uri: mediaUrl(dish.profile_photo_url) }}
                style={styles.avatar}
              />
            ) : (
              <View style={styles.avatar}><Text style={styles.avatarText}>{initial}</Text></View>
            )}
            <View style={styles.cookCopy}>
              <Text numberOfLines={1} style={styles.cookName}>{establishmentName}</Text>
              <View style={styles.ratingRow}>
                {hasRating ? (
                  <>
                    <Ionicons color={colors.mangoOrange} name="star" size={iconSizes.compact} />
                    <Text style={styles.rating}>{formatRating(dish.rating_average!)} ({dish.review_count})</Text>
                  </>
                ) : (
                  <Text style={styles.newCook}>{t("cookProfile.new")}</Text>
                )}
              </View>
            </View>
          </View>

          {dish.distance_km !== null ? (
            <View style={styles.metaRow}>
              <Ionicons color={colors.brandGreen} name="navigate-outline" size={iconSizes.compact} />
              <Text numberOfLines={1} style={styles.distanceText}>
                {t("dish.distance", { distance: formatDistance(dish.distance_km) })}
              </Text>
            </View>
          ) : null}

          <View style={styles.commerceRow}>
            <Text style={styles.price}>{formatMoney(dish.price, dish.currency)}</Text>
          </View>
        </View>
      </Pressable>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  entrance: { width: "100%" },
  card: {
    height: 176,
    flexDirection: "row",
    overflow: "hidden",
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: radius.xl,
    backgroundColor: colors.surface,
    shadowColor: colors.darkCocoa,
    shadowOffset: { width: 0, height: 5 },
    shadowOpacity: 0.07,
    shadowRadius: 12,
    elevation: 2,
  },
  cardCompact: { height: 166 },
  pressed: { opacity: 0.9, transform: [{ scale: 0.99 }] },
  imageWrap: { height: "100%", aspectRatio: 0.78, flexShrink: 0, overflow: "hidden", backgroundColor: colors.creamDeep },
  imageWrapCompact: { aspectRatio: 0.72 },
  image: { ...StyleSheet.absoluteFillObject },
  imageFallback: { alignItems: "center", justifyContent: "center", gap: spacing.xs, backgroundColor: colors.creamDeep },
  fallbackIcon: { width: controlSizes.minimumTouch, height: controlSizes.minimumTouch, alignItems: "center", justifyContent: "center", borderRadius: radius.pill, backgroundColor: colors.cornYellow },
  fallbackTitle: { color: colors.cocoaMuted, fontFamily: fonts.editorialSemiBold, fontSize: fontSizes.bodySmall, textAlign: "center" },
  body: { minWidth: 0, flex: 1, justifyContent: "space-between", padding: spacing.sm },
  title: { color: colors.darkCocoa, fontFamily: fonts.editorialSemiBold, fontSize: fontSizes.subtitle, lineHeight: lineHeights.subtitle },
  cookRow: { minHeight: spacing.lg, flexDirection: "row", alignItems: "center", gap: spacing.xs },
  avatar: { width: 30, height: 30, alignItems: "center", justifyContent: "center", borderRadius: radius.pill, backgroundColor: colors.mutedSage },
  avatarText: { color: colors.brandGreen, fontFamily: fonts.extraBold, fontSize: fontSizes.caption },
  cookCopy: { flex: 1 },
  cookName: { color: colors.darkCocoa, fontFamily: fonts.bold, fontSize: fontSizes.bodySmall, lineHeight: lineHeights.bodySmall },
  ratingRow: { flexDirection: "row", alignItems: "center", gap: spacing.xxs },
  rating: { color: colors.cocoaMuted, fontFamily: fonts.semiBold, fontSize: fontSizes.caption },
  newCook: { color: colors.cocoaMuted, fontFamily: fonts.medium, fontSize: fontSizes.caption },
  metaRow: { minWidth: 0, flexDirection: "row", alignItems: "center", gap: 5 },
  distanceText: { color: colors.brandGreen, fontFamily: fonts.bold, fontSize: fontSizes.caption },
  commerceRow: { flexDirection: "row", alignItems: "flex-end", justifyContent: "space-between", gap: spacing.xs },
  price: { color: colors.darkCocoa, fontFamily: fonts.extraBold, fontSize: fontSizes.subtitle },
});
