import type { ComponentProps } from "react";
import { Pressable, StyleSheet, Text } from "react-native";
import Ionicons from "@expo/vector-icons/Ionicons";

import { colors } from "../theme/colors";
import { radius } from "../theme/radius";
import { spacing } from "../theme/spacing";
import { fonts } from "../theme/typography";

type Props = {
  label: string;
  selected?: boolean;
  disabled?: boolean;
  icon?: ComponentProps<typeof Ionicons>["name"];
  onPress?: () => void;
};

// Puce de la maquette : gris clair, noire quand elle est choisie.
export function FilterChip({ label, selected = false, disabled = false, icon, onPress }: Props) {
  return (
    <Pressable
      accessibilityLabel={label}
      accessibilityRole="button"
      accessibilityState={{ selected, disabled }}
      disabled={disabled}
      hitSlop={4}
      onPress={onPress}
      style={({ pressed }) => [
        styles.chip,
        selected && styles.selected,
        disabled && styles.disabled,
        pressed && !disabled && styles.pressed,
      ]}
    >
      {icon && <Ionicons color={selected ? colors.surface : colors.ink} name={icon} size={16} />}
      <Text numberOfLines={1} style={[styles.label, selected && styles.selectedLabel]}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  chip: {
    height: 44,
    flexShrink: 0,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.xxs + 2,
    borderRadius: radius.pill,
    backgroundColor: colors.creamDeep,
    paddingHorizontal: spacing.sm,
  },
  selected: { backgroundColor: colors.ink },
  label: { color: colors.ink, fontFamily: fonts.semiBold, fontSize: 14, lineHeight: 18 },
  selectedLabel: { color: colors.surface },
  disabled: { opacity: 0.46 },
  pressed: { opacity: 0.75, transform: [{ scale: 0.98 }] },
});
