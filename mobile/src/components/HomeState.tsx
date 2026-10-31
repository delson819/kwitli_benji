import type { ComponentProps } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import Ionicons from "@expo/vector-icons/Ionicons";

import { colors } from "../theme/colors";
import { controlSizes, iconSizes } from "../theme/layout";
import { radius } from "../theme/radius";
import { spacing } from "../theme/spacing";
import { fontSizes, fonts, lineHeights } from "../theme/typography";
import { AnimatedCauldron } from "./AnimatedCauldron";
import { PrimaryButton } from "./PrimaryButton";

type IconName = ComponentProps<typeof Ionicons>["name"];

type Props = {
  title: string;
  body?: string;
  icon: IconName;
  tone?: "brand" | "error";
  variant?: "default" | "empty";
  actionLabel?: string;
  actionIcon?: IconName;
  onAction?: () => void;
  secondaryActionLabel?: string;
  onSecondaryAction?: () => void;
};

export function HomeState({
  title,
  body,
  icon,
  tone = "brand",
  variant = "default",
  actionLabel,
  actionIcon = "refresh",
  onAction,
  secondaryActionLabel,
  onSecondaryAction,
}: Props) {
  const iconColor = tone === "error" ? colors.error : colors.brandGreen;

  if (variant === "empty") {
    return (
      <View style={styles.emptyCard}>
        <View style={styles.emptyLead}>
          <AnimatedCauldron />
          <View style={styles.emptyCopy}>
            <Text style={styles.emptyTitle}>{title}</Text>
            {body ? <Text style={styles.body}>{body}</Text> : null}
          </View>
        </View>
        {actionLabel && onAction ? (
          <PrimaryButton icon={actionIcon} label={actionLabel} onPress={onAction} />
        ) : null}
        {secondaryActionLabel && onSecondaryAction ? (
          <Pressable
            accessibilityRole="button"
            onPress={onSecondaryAction}
            style={({ pressed }) => [styles.secondaryAction, pressed && styles.pressed]}
          >
            <Text style={styles.secondaryActionText}>{secondaryActionLabel}</Text>
          </Pressable>
        ) : null}
      </View>
    );
  }

  return (
    <View style={styles.state}>
      <View style={[styles.icon, tone === "error" && styles.errorIcon]}>
        <Ionicons color={iconColor} name={icon} size={iconSizes.large} />
      </View>
      <View style={styles.copy}>
        <Text style={styles.title}>{title}</Text>
        {body ? <Text style={styles.body}>{body}</Text> : null}
      </View>
      {actionLabel && onAction ? (
        <PrimaryButton compact icon={actionIcon} label={actionLabel} onPress={onAction} />
      ) : null}
      {secondaryActionLabel && onSecondaryAction ? (
        <Pressable
          accessibilityRole="button"
          onPress={onSecondaryAction}
          style={({ pressed }) => [styles.secondaryAction, pressed && styles.pressed]}
        >
          <Text style={styles.secondaryActionText}>{secondaryActionLabel}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  state: {
    alignItems: "center",
    gap: spacing.xs,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.md,
  },
  emptyCard: {
    position: "relative",
    overflow: "hidden",
    alignItems: "center",
    gap: spacing.xs,
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: radius.xl,
    backgroundColor: colors.warmSurface,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    shadowColor: colors.darkCocoa,
    shadowOffset: { width: 0, height: 5 },
    shadowOpacity: 0.05,
    shadowRadius: 14,
    elevation: 2,
  },
  emptyLead: { zIndex: 1, alignItems: "center", gap: spacing.xxs },
  emptyCopy: { maxWidth: 300, alignItems: "center", gap: spacing.xxs },
  emptyTitle: { color: colors.darkCocoa, fontFamily: fonts.editorialSemiBold, fontSize: fontSizes.subtitle, lineHeight: 25, textAlign: "center" },
  icon: {
    width: spacing.xl,
    height: spacing.xl,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: radius.pill,
    backgroundColor: colors.cornYellow,
  },
  errorIcon: { backgroundColor: colors.creamDeep },
  copy: { maxWidth: 340, gap: spacing.xxs },
  title: {
    color: colors.darkCocoa,
    fontFamily: fonts.editorialSemiBold,
    fontSize: fontSizes.subtitle,
    lineHeight: 24,
    textAlign: "center",
  },
  body: {
    color: colors.cocoaMuted,
    fontFamily: fonts.regular,
    fontSize: fontSizes.bodySmall,
    lineHeight: lineHeights.bodySmall,
    textAlign: "center",
  },
  secondaryAction: { zIndex: 1, minHeight: controlSizes.minimumTouch, justifyContent: "center", marginTop: -spacing.xxs, paddingHorizontal: spacing.sm },
  secondaryActionText: { color: colors.brandGreen, fontFamily: fonts.bold, fontSize: 14 },
  pressed: { opacity: 0.68 },
});
