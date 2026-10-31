import { StyleSheet, Text, View } from "react-native";

import { t } from "../i18n";
import { colors } from "../theme/colors";
import { spacing } from "../theme/spacing";
import { fonts } from "../theme/typography";

type Props = {
  remaining: number;
  total?: number;
  compact?: boolean;
};

export function PortionIndicator({ remaining, total, compact = false }: Props) {
  const lowStock = remaining <= 2;
  const hasKnownTotal = typeof total === "number" && total > 0;
  const segmentTotal = hasKnownTotal ? Math.min(total, 8) : 0;
  const filledSegments = hasKnownTotal && total > 8
    ? Math.round((remaining / total) * segmentTotal)
    : Math.min(remaining, segmentTotal);
  const label = lowStock
    ? t(remaining === 1 ? "portions.lowCountSingular" : "portions.lowCount", { remaining })
    : compact
      ? t("portions.shortCount", { remaining })
      : hasKnownTotal
        ? t("portions.ofTotal", { remaining, total })
        : t("portions.availableCount", { remaining });

  return (
    <View accessibilityLabel={label} style={styles.wrapper}>
      {hasKnownTotal ? (
        <View style={styles.segments}>
          {Array.from({ length: segmentTotal }, (_, index) => (
            <View
              key={index}
              style={[
                styles.segment,
                index < filledSegments && (lowStock ? styles.segmentLow : styles.segmentFilled),
              ]}
            />
          ))}
        </View>
      ) : null}
      <Text style={[styles.label, lowStock && styles.lowLabel]}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: { flexShrink: 1, gap: spacing.xs },
  segments: { flexDirection: "row", gap: 5 },
  segment: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.creamDeep },
  segmentFilled: { backgroundColor: colors.brandGreen },
  segmentLow: { backgroundColor: colors.mangoOrange },
  label: { color: colors.cocoaMuted, fontFamily: fonts.semiBold, fontSize: 13 },
  lowLabel: { color: colors.mangoOrange },
});
