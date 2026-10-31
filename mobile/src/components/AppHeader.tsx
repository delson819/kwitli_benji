import { Pressable, StyleSheet, Text, View } from "react-native";
import Ionicons from "@expo/vector-icons/Ionicons";

import { t } from "../i18n";
import { colors } from "../theme/colors";
import { controlSizes, iconSizes } from "../theme/layout";
import { radius } from "../theme/radius";
import { spacing } from "../theme/spacing";
import { fonts } from "../theme/typography";
import { BrandWordmark } from "./BrandWordmark";

type Props = {
  firstName: string;
  locationLabel: string;
  locationIsManual?: boolean;
  onLocationPress: () => void;
  onProfilePress: () => void;
};

// En-tete de la maquette : zone en haut, logo, puis le titre de l'ecran (affiche par l'accueil).
export function AppHeader({ locationLabel, locationIsManual = false, onLocationPress, onProfilePress }: Props) {
  return (
    <View style={styles.header}>
      <View style={styles.topRow}>
        <Pressable
          accessibilityLabel={`${t(locationIsManual ? "location.searchZoneTitle" : "home.locationLabel")} : ${locationLabel}. ${t("location.chooseTitle")}`}
          accessibilityRole="button"
          hitSlop={6}
          onPress={onLocationPress}
          style={({ pressed }) => [styles.locationRow, pressed && styles.pressed]}
        >
          <Ionicons color={colors.ink} name="location" size={iconSizes.medium} />
          <Text numberOfLines={1} style={styles.locationValue}>{locationLabel}</Text>
          <Ionicons color={colors.ink} name="chevron-down" size={iconSizes.small} />
        </Pressable>
        <Pressable
          accessibilityLabel={t("nav.profile")}
          accessibilityRole="button"
          hitSlop={6}
          onPress={onProfilePress}
          style={({ pressed }) => [styles.iconButton, pressed && styles.pressed]}
        >
          <Ionicons color={colors.ink} name="person-circle-outline" size={iconSizes.large} />
        </Pressable>
      </View>
      <BrandWordmark size={36} />
    </View>
  );
}

const styles = StyleSheet.create({
  header: { gap: spacing.xs },
  topRow: { minHeight: controlSizes.minimumTouch, flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.sm },
  locationRow: { minHeight: controlSizes.minimumTouch, flexShrink: 1, flexDirection: "row", alignItems: "center", gap: spacing.xxs + 2 },
  locationValue: { flexShrink: 1, color: colors.ink, fontFamily: fonts.semiBold, fontSize: 15 },
  iconButton: { width: controlSizes.minimumTouch, height: controlSizes.minimumTouch, alignItems: "center", justifyContent: "center", borderRadius: radius.pill },
  pressed: { opacity: 0.6 },
});
