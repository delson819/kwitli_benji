import { useEffect, useRef } from "react";
import { Animated, Easing, StyleSheet, View } from "react-native";

import { useReducedMotion } from "../hooks/useReducedMotion";
import { colors } from "../theme/colors";
import { controlSizes } from "../theme/layout";
import { radius } from "../theme/radius";
import { spacing } from "../theme/spacing";

type Props = {
  accessibilityLabel: string;
};

export function HomeSkeleton({ accessibilityLabel }: Props) {
  const reducedMotion = useReducedMotion();
  const pulse = useRef(new Animated.Value(0.58)).current;

  useEffect(() => {
    if (reducedMotion) {
      pulse.setValue(0.72);
      return undefined;
    }

    const animation = Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, {
          duration: 900,
          easing: Easing.inOut(Easing.sin),
          toValue: 0.9,
          useNativeDriver: true,
        }),
        Animated.timing(pulse, {
          duration: 900,
          easing: Easing.inOut(Easing.sin),
          toValue: 0.58,
          useNativeDriver: true,
        }),
      ]),
    );
    animation.start();
    return () => animation.stop();
  }, [pulse, reducedMotion]);

  return (
    <Animated.View
      accessibilityLabel={accessibilityLabel}
      accessibilityRole="progressbar"
      style={[styles.screen, { opacity: pulse }]}
    >
      <View style={styles.header}>
        <View style={styles.brandRow}>
          <View style={styles.brandCopy}>
            <View style={[styles.block, styles.brand]} />
            <View style={[styles.block, styles.tagline]} />
          </View>
          <View style={[styles.block, styles.avatar]} />
        </View>
        <View style={[styles.block, styles.location]} />
      </View>

      <View style={styles.hero}>
        <View style={[styles.block, styles.greeting]} />
        <View style={[styles.block, styles.heroLine]} />
        <View style={[styles.block, styles.heroLineShort]} />
        <View style={[styles.block, styles.heroBody]} />
      </View>

      <View style={styles.chips}>
        <View style={[styles.block, styles.chipWide]} />
        <View style={[styles.block, styles.chip]} />
        <View style={[styles.block, styles.chipWide]} />
      </View>

      <View style={styles.sectionHeading}>
        <View style={[styles.block, styles.sectionTitle]} />
        <View style={[styles.block, styles.refresh]} />
      </View>

      <View style={styles.list}>
        {[0, 1].map((item) => (
          <View key={item} style={styles.card}>
            <View style={[styles.block, styles.image]} />
            <View style={styles.body}>
              <View style={[styles.block, styles.title]} />
              <View style={[styles.block, styles.copy]} />
              <View style={[styles.block, styles.meta]} />
              <View style={styles.row}>
                <View style={[styles.block, styles.price]} />
                <View style={[styles.block, styles.portions]} />
              </View>
            </View>
          </View>
        ))}
      </View>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  screen: { gap: spacing.sm },
  header: { gap: spacing.xs, paddingTop: spacing.xxs },
  brandRow: { flexDirection: "row", alignItems: "flex-start", justifyContent: "space-between" },
  brandCopy: { gap: spacing.xxs },
  hero: { gap: spacing.xxs, paddingTop: spacing.xs },
  chips: { flexDirection: "row", gap: spacing.xs, overflow: "hidden" },
  sectionHeading: { minHeight: controlSizes.minimumTouch, flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  list: { gap: spacing.sm },
  card: {
    minHeight: 188,
    flexDirection: "row",
    overflow: "hidden",
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: radius.xl,
    backgroundColor: colors.surface,
  },
  block: { backgroundColor: colors.creamDeep },
  brand: { width: 96, height: spacing.lg, borderRadius: radius.sm },
  tagline: { width: 144, height: 12, borderRadius: radius.sm },
  avatar: { width: controlSizes.minimumTouch, height: controlSizes.minimumTouch, borderRadius: radius.pill },
  location: { width: "72%", height: controlSizes.minimumTouch, borderRadius: radius.pill },
  greeting: { width: 116, height: spacing.sm, borderRadius: radius.sm },
  heroLine: { width: "76%", height: 31, borderRadius: radius.sm },
  heroLineShort: { width: "70%", height: 31, borderRadius: radius.sm },
  heroBody: { width: "82%", height: spacing.sm, marginTop: spacing.xxs, borderRadius: radius.sm },
  chip: { width: 130, height: controlSizes.minimumTouch, borderRadius: radius.pill },
  chipWide: { width: 116, height: controlSizes.minimumTouch, borderRadius: radius.pill },
  sectionTitle: { width: 190, height: spacing.md, borderRadius: radius.sm },
  refresh: { width: controlSizes.minimumTouch, height: controlSizes.minimumTouch, borderRadius: radius.pill },
  image: { width: 138, alignSelf: "stretch" },
  body: { flex: 1, justifyContent: "space-between", gap: spacing.xs, padding: 12 },
  title: { width: "82%", height: spacing.md, borderRadius: radius.sm },
  copy: { width: "70%", height: spacing.sm, borderRadius: radius.sm },
  meta: { width: "88%", height: 12, borderRadius: radius.sm },
  row: { flexDirection: "row", justifyContent: "space-between", gap: spacing.sm },
  price: { width: "38%", height: spacing.md, borderRadius: radius.sm },
  portions: { width: "42%", height: spacing.sm, borderRadius: radius.sm },
});
