import { useRef, useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";
import Ionicons from "@expo/vector-icons/Ionicons";

import { EXPLORE_RADIUS_OPTIONS } from "../discovery";
import { t } from "../i18n";
import { getDiscover, type DiscoverItem } from "../services/api";
import { colors } from "../theme/colors";
import { controlSizes, iconSizes } from "../theme/layout";
import { radius } from "../theme/radius";
import { spacing } from "../theme/spacing";
import { fontSizes, fonts, lineHeights } from "../theme/typography";
import { DishCard } from "./DishCard";
import { PrimaryButton } from "./PrimaryButton";

type RadiusOption = (typeof EXPLORE_RADIUS_OPTIONS)[number];
type SearchState = "idle" | "loading" | "results" | "noResults" | "error";
type Coordinates = { latitude: number; longitude: number };

type Props = {
  coordinates: Coordinates | null;
  locationLabel: string;
  onBack: () => void;
  onOpenDish: (dish: DiscoverItem) => void;
};

function nextRadius(radiusKm: RadiusOption): RadiusOption | null {
  const index = EXPLORE_RADIUS_OPTIONS.indexOf(radiusKm);
  return EXPLORE_RADIUS_OPTIONS[index + 1] ?? null;
}

export function ExploreFartherScreen({ coordinates, locationLabel, onBack, onOpenDish }: Props) {
  const [selectedRadius, setSelectedRadius] = useState<RadiusOption>(10);
  const [searchState, setSearchState] = useState<SearchState>("idle");
  const [results, setResults] = useState<DiscoverItem[]>([]);
  const requestId = useRef(0);

  function selectRadius(radiusKm: RadiusOption) {
    requestId.current += 1;
    setSelectedRadius(radiusKm);
    setResults([]);
    setSearchState("idle");
  }

  async function search(radiusKm = selectedRadius) {
    if (!coordinates) return;

    const currentRequest = ++requestId.current;
    setSelectedRadius(radiusKm);
    setSearchState("loading");
    try {
      const dishes = await getDiscover({ ...coordinates, radiusKm });
      if (requestId.current !== currentRequest) return;
      setResults(dishes);
      setSearchState(dishes.length > 0 ? "results" : "noResults");
    } catch {
      if (requestId.current !== currentRequest) return;
      setResults([]);
      setSearchState("error");
    }
  }

  const widerRadius = nextRadius(selectedRadius);

  return (
    <View style={styles.screen}>
      <View style={styles.header}>
        <Pressable
          accessibilityLabel={t("exploreFarther.backA11y")}
          accessibilityRole="button"
          hitSlop={8}
          onPress={onBack}
          style={({ pressed }) => [styles.backButton, pressed && styles.pressed]}
        >
          <Ionicons color={colors.brandGreen} name="arrow-back" size={iconSizes.medium} />
        </Pressable>
        <Text accessibilityRole="header" style={styles.title}>{t("exploreFarther.title")}</Text>
      </View>

      <Text style={styles.subtitle}>{t("exploreFarther.subtitle")}</Text>

      <View style={styles.locationCard}>
        <View style={styles.locationIcon}>
          <Ionicons color={colors.mangoOrange} name="navigate" size={iconSizes.medium} />
        </View>
        <View style={styles.locationCopy}>
          <Text style={styles.eyebrow}>{t("exploreFarther.currentLocation")}</Text>
          <Text numberOfLines={2} style={styles.locationValue}>
            {coordinates ? locationLabel : t("exploreFarther.locationUnavailable")}
          </Text>
        </View>
      </View>

      <View style={styles.radiusSection}>
        <Text style={styles.sectionTitle}>{t("exploreFarther.radiusQuestion")}</Text>
        <View style={styles.radiusGrid}>
          {EXPLORE_RADIUS_OPTIONS.map((radiusKm) => {
            const selected = radiusKm === selectedRadius;
            return (
              <Pressable
                accessibilityRole="button"
                accessibilityState={{ selected }}
                key={radiusKm}
                onPress={() => selectRadius(radiusKm)}
                style={({ pressed }) => [
                  styles.radiusOption,
                  selected && styles.radiusOptionSelected,
                  pressed && styles.pressed,
                ]}
              >
                <Text style={[styles.radiusLabel, selected && styles.radiusLabelSelected]}>
                  {t("exploreFarther.radiusOption", { radius: radiusKm })}
                </Text>
              </Pressable>
            );
          })}
        </View>
      </View>

      <View style={styles.resultsSection}>
        <Text style={styles.sectionTitle}>{t("exploreFarther.resultsTitle")}</Text>

        {searchState === "idle" ? (
          <View style={styles.statusCard}>
            <Ionicons color={colors.mutedSage} name="compass-outline" size={iconSizes.hero} />
            <Text style={styles.statusBody}>
              {coordinates ? t("exploreFarther.idleBody") : t("exploreFarther.locationUnavailable")}
            </Text>
          </View>
        ) : null}

        {searchState === "loading" ? (
          <View accessibilityLiveRegion="polite" style={styles.statusCard}>
            <ActivityIndicator color={colors.brandGreen} />
            <Text style={styles.statusBody}>{t("exploreFarther.loading")}</Text>
          </View>
        ) : null}

        {searchState === "noResults" ? (
          <View style={styles.statusCard}>
            <View style={styles.statusIcon}>
              <Ionicons color={colors.brandGreen} name="restaurant-outline" size={iconSizes.large} />
            </View>
            <Text style={styles.statusTitle}>{t("exploreFarther.noResultsTitle")}</Text>
            <Text style={styles.statusBody}>{t("exploreFarther.noResultsBody")}</Text>
            {widerRadius ? (
              <Pressable
                accessibilityRole="button"
                onPress={() => void search(widerRadius)}
                style={({ pressed }) => [styles.secondaryAction, pressed && styles.pressed]}
              >
                <Text style={styles.secondaryActionText}>
                  {t("exploreFarther.expandRadius", { radius: widerRadius })}
                </Text>
                <Ionicons color={colors.brandGreen} name="arrow-forward" size={iconSizes.small} />
              </Pressable>
            ) : null}
          </View>
        ) : null}

        {searchState === "error" ? (
          <View accessibilityLiveRegion="polite" style={styles.statusCard}>
            <View style={[styles.statusIcon, styles.errorIcon]}>
              <Ionicons color={colors.error} name="cloud-offline-outline" size={iconSizes.large} />
            </View>
            <Text style={styles.statusTitle}>{t("exploreFarther.errorTitle")}</Text>
            <Text style={styles.statusBody}>{t("exploreFarther.errorBody")}</Text>
            <Pressable
              accessibilityRole="button"
              onPress={() => void search()}
              style={({ pressed }) => [styles.secondaryAction, pressed && styles.pressed]}
            >
              <Text style={styles.secondaryActionText}>{t("exploreFarther.retry")}</Text>
              <Ionicons color={colors.brandGreen} name="refresh" size={iconSizes.small} />
            </Pressable>
          </View>
        ) : null}

        {searchState === "results" ? (
          <View style={styles.resultList}>
            {results.map((dish, index) => (
              <DishCard
                dish={dish}
                index={index}
                key={dish.availability_id}
                onPress={() => onOpenDish(dish)}
              />
            ))}
          </View>
        ) : null}
      </View>

      <PrimaryButton
        disabled={!coordinates}
        icon="search"
        label={t("exploreFarther.search")}
        loading={searchState === "loading"}
        onPress={() => void search()}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { gap: spacing.md },
  header: { minHeight: controlSizes.minimumTouch, flexDirection: "row", alignItems: "center", gap: spacing.xs },
  backButton: {
    width: controlSizes.minimumTouch,
    height: controlSizes.minimumTouch,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: radius.pill,
    backgroundColor: colors.surface,
  },
  title: { flex: 1, color: colors.darkCocoa, fontFamily: fonts.editorialSemiBold, fontSize: fontSizes.title, lineHeight: lineHeights.title },
  subtitle: { maxWidth: 340, color: colors.cocoaMuted, fontFamily: fonts.regular, fontSize: fontSizes.body, lineHeight: lineHeights.body },
  locationCard: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: radius.lg,
    backgroundColor: colors.surface,
    padding: spacing.sm,
  },
  locationIcon: {
    width: controlSizes.minimumTouch,
    height: controlSizes.minimumTouch,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: radius.pill,
    backgroundColor: colors.cornYellow,
  },
  locationCopy: { minWidth: 0, flex: 1, gap: spacing.xxs },
  eyebrow: { color: colors.brandGreen, fontFamily: fonts.bold, fontSize: fontSizes.caption, lineHeight: lineHeights.caption },
  locationValue: { color: colors.darkCocoa, fontFamily: fonts.semiBold, fontSize: fontSizes.body, lineHeight: lineHeights.body },
  radiusSection: { gap: spacing.sm },
  sectionTitle: { color: colors.darkCocoa, fontFamily: fonts.editorialSemiBold, fontSize: fontSizes.sectionTitle, lineHeight: lineHeights.subtitle },
  radiusGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs },
  radiusOption: {
    minHeight: controlSizes.minimumTouch,
    minWidth: "47%",
    flexGrow: 1,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    paddingHorizontal: spacing.sm,
  },
  radiusOptionSelected: { borderColor: colors.brandGreen, backgroundColor: colors.brandGreen },
  radiusLabel: { color: colors.darkCocoa, fontFamily: fonts.bold, fontSize: fontSizes.bodySmall },
  radiusLabelSelected: { color: colors.warmCream },
  resultsSection: { gap: spacing.sm },
  resultList: { gap: spacing.sm },
  statusCard: {
    minHeight: 140,
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.xs,
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: radius.lg,
    backgroundColor: colors.warmSurface,
    padding: spacing.md,
  },
  statusIcon: {
    width: spacing.xl,
    height: spacing.xl,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: radius.pill,
    backgroundColor: colors.cornYellow,
  },
  errorIcon: { backgroundColor: colors.creamDeep },
  statusTitle: { color: colors.darkCocoa, fontFamily: fonts.editorialSemiBold, fontSize: fontSizes.subtitle, lineHeight: lineHeights.subtitle, textAlign: "center" },
  statusBody: { maxWidth: 320, color: colors.cocoaMuted, fontFamily: fonts.regular, fontSize: fontSizes.bodySmall, lineHeight: lineHeights.bodySmall, textAlign: "center" },
  secondaryAction: {
    minHeight: controlSizes.minimumTouch,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.xs,
    borderWidth: 1,
    borderColor: colors.brandGreen,
    borderRadius: radius.md,
    paddingHorizontal: spacing.sm,
  },
  secondaryActionText: { color: colors.brandGreen, fontFamily: fonts.bold, fontSize: fontSizes.bodySmall },
  pressed: { opacity: 0.7 },
});
