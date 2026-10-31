import type { ComponentProps } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import Ionicons from "@expo/vector-icons/Ionicons";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { t, type TranslationKey } from "../i18n";
import { colors } from "../theme/colors";
import { controlSizes, iconSizes } from "../theme/layout";
import { radius } from "../theme/radius";
import { spacing } from "../theme/spacing";
import { fonts } from "../theme/typography";

export type ClientTab = "home" | "orders" | "cook" | "favorites" | "profile";
type IconName = ComponentProps<typeof Ionicons>["name"];

// Ordre de la maquette : Explorer, Favoris, Commandes, (Commerce), Profil.
const items: { id: ClientTab; label: TranslationKey; icon: IconName; activeIcon: IconName }[] = [
  { id: "home", label: "nav.home", icon: "home-outline", activeIcon: "home" },
  { id: "favorites", label: "nav.favorites", icon: "heart-outline", activeIcon: "heart" },
  { id: "orders", label: "nav.orders", icon: "bag-handle-outline", activeIcon: "bag-handle" },
  { id: "cook", label: "nav.cook", icon: "storefront-outline", activeIcon: "storefront" },
  { id: "profile", label: "nav.profile", icon: "person-outline", activeIcon: "person" },
];

type Props = {
  active: ClientTab;
  onSelect: (tab: ClientTab) => void;
};

export function BottomNavigation({ active, onSelect }: Props) {
  const insets = useSafeAreaInsets();

  return (
    <View style={[styles.navigation, { paddingBottom: Math.max(insets.bottom, spacing.xxs) }]}>
      {items.map((item) => {
        const selected = item.id === active;
        return (
          <Pressable
            key={item.id}
            accessibilityLabel={t(item.label)}
            accessibilityRole="button"
            accessibilityState={{ selected }}
            onPress={() => onSelect(item.id)}
            style={({ pressed }) => [styles.item, pressed && styles.pressed]}
          >
            <View style={styles.iconWrap}>
              <Ionicons
                color={selected ? colors.accent : colors.ink}
                name={selected ? item.activeIcon : item.icon}
                size={iconSizes.navigation + 2}
              />
            </View>
            <Text
              adjustsFontSizeToFit
              maxFontSizeMultiplier={1.1}
              minimumFontScale={0.85}
              numberOfLines={1}
              style={[styles.label, selected && styles.activeLabel]}
            >
              {t(item.label)}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  navigation: {
    flexDirection: "row",
    alignItems: "center",
    borderTopWidth: 1,
    borderTopColor: colors.line,
    backgroundColor: colors.surface,
    paddingHorizontal: spacing.xxs,
    paddingTop: spacing.xxs,
  },
  item: { flex: 1, minHeight: controlSizes.navigationBar, alignItems: "center", justifyContent: "center", gap: 3 },
  iconWrap: { width: controlSizes.navigationIcon, height: 26, alignItems: "center", justifyContent: "center", borderRadius: radius.pill },
  label: {
    width: "100%",
    color: colors.ink,
    fontFamily: fonts.medium,
    fontSize: 11,
    lineHeight: 14,
    textAlign: "center",
  },
  activeLabel: { color: colors.ink, fontFamily: fonts.bold },
  pressed: { opacity: 0.65 },
});
