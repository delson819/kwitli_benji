import { useEffect, useRef, useState } from "react";
import {
  AccessibilityInfo,
  Animated,
  Easing,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from "react-native";
import { StatusBar } from "expo-status-bar";

import { t } from "../i18n";
import { colors } from "../theme/colors";
import { spacing } from "../theme/spacing";
import { fontSizes, fonts, lineHeights } from "../theme/typography";
import { BrandWordmark } from "./BrandWordmark";

const ENTER_DURATION_MS = 650;
const EXIT_DURATION_MS = 200;
const REDUCED_MOTION_EXIT_DURATION_MS = 140;

type Props = {
  leaving: boolean;
  onHidden: () => void;
};

export function BrandSplash({ leaving, onHidden }: Props) {
  const { width } = useWindowDimensions();
  const opacity = useRef(new Animated.Value(0)).current;
  const scale = useRef(new Animated.Value(0.96)).current;
  const onHiddenRef = useRef(onHidden);
  const hidden = useRef(false);
  const [reducedMotion, setReducedMotion] = useState(false);
  onHiddenRef.current = onHidden;

  useEffect(() => {
    let mounted = true;
    void AccessibilityInfo.isReduceMotionEnabled()
      .then((enabled) => {
        if (mounted) setReducedMotion(enabled);
      })
      .catch(() => {
        if (mounted) setReducedMotion(false);
      });
    const subscription = AccessibilityInfo.addEventListener("reduceMotionChanged", setReducedMotion);
    return () => {
      mounted = false;
      subscription.remove();
    };
  }, []);

  useEffect(() => {
    if (leaving) {
      const exit = Animated.timing(opacity, {
        duration: reducedMotion ? REDUCED_MOTION_EXIT_DURATION_MS : EXIT_DURATION_MS,
        easing: Easing.in(Easing.quad),
        toValue: 0,
        useNativeDriver: true,
      });
      exit.start(({ finished }) => {
        if (finished && !hidden.current) {
          hidden.current = true;
          onHiddenRef.current();
        }
      });
      return () => exit.stop();
    }

    if (reducedMotion) {
      opacity.setValue(1);
      scale.setValue(1);
      return undefined;
    }

    const enter = Animated.parallel([
      Animated.timing(opacity, {
        duration: ENTER_DURATION_MS,
        easing: Easing.out(Easing.cubic),
        toValue: 1,
        useNativeDriver: true,
      }),
      Animated.timing(scale, {
        duration: ENTER_DURATION_MS,
        easing: Easing.out(Easing.cubic),
        toValue: 1,
        useNativeDriver: true,
      }),
    ]);
    enter.start();
    return () => enter.stop();
  }, [leaving, opacity, reducedMotion, scale]);

  const logoWidth = Math.min(width * 0.62, 280);

  return (
    <View style={styles.screen}>
      <StatusBar style="dark" />
      <Animated.View
        accessible
        accessibilityLabel={`${t("brand.name")}. ${t("brand.tagline")}`}
        style={[styles.brand, { opacity, transform: [{ scale }] }]}
      >
        <View accessible={false} importantForAccessibility="no-hide-descendants" style={[styles.logo, { width: logoWidth }]}>
          <BrandWordmark size={Math.round(logoWidth / 4.2)} />
        </View>
        <Text style={styles.tagline}>{t("brand.tagline")}</Text>
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.warmCream,
    paddingHorizontal: spacing.lg,
  },
  brand: {
    alignItems: "center",
    gap: spacing.sm,
  },
  logo: {
    maxWidth: "100%",
    alignItems: "center",
  },
  tagline: {
    maxWidth: 300,
    color: colors.cocoaMuted,
    fontFamily: fonts.medium,
    fontSize: fontSizes.bodySmall,
    lineHeight: lineHeights.bodySmall,
    textAlign: "center",
  },
});
