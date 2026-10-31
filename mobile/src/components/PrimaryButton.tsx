import type { ComponentProps } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";
import Ionicons from "@expo/vector-icons/Ionicons";

import { colors } from "../theme/colors";
import { controlSizes } from "../theme/layout";
import { radius } from "../theme/radius";
import { spacing } from "../theme/spacing";
import { fonts } from "../theme/typography";

type IconName = ComponentProps<typeof Ionicons>["name"];

type Props = {
  label: string;
  onPress: () => void;
  disabled?: boolean;
  loading?: boolean;
  icon?: IconName;
  compact?: boolean;
  accessibilityLabel?: string;
};

export function PrimaryButton({
  label,
  onPress,
  disabled = false,
  loading = false,
  icon = "arrow-forward",
  compact = false,
  accessibilityLabel,
}: Props) {
  const unavailable = disabled || loading;
  return (
    <Pressable
      accessibilityLabel={accessibilityLabel ?? label}
      accessibilityRole="button"
      accessibilityState={{ disabled: unavailable, busy: loading }}
      disabled={unavailable}
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        compact && styles.compact,
        unavailable && styles.disabled,
        pressed && !unavailable && styles.pressed,
      ]}
    >
      {loading ? (
        <ActivityIndicator color={colors.warmCream} />
      ) : (
        <View style={styles.content}>
          <Text style={styles.label}>{label}</Text>
          <Ionicons color={colors.accent} name={icon} size={20} />
        </View>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: {
    minHeight: 56,
    width: "100%",
    justifyContent: "center",
    backgroundColor: colors.ink,
    borderRadius: radius.lg,
    paddingHorizontal: spacing.md,
    paddingVertical: 14,
  },
  compact: { alignSelf: "center", minHeight: controlSizes.minimumTouch, width: "auto", paddingVertical: spacing.xs },
  content: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.xs },
  label: { flexShrink: 1, color: colors.surface, fontFamily: fonts.bold, fontSize: 16, textAlign: "center" },
  disabled: { opacity: 0.5 },
  pressed: { opacity: 0.86, transform: [{ scale: 0.99 }] },
});
