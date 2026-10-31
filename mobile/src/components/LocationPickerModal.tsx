import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { t } from "../i18n";
import type { LocationChoice, LocationSource } from "../location";
import { colors } from "../theme/colors";
import { radius } from "../theme/radius";
import { spacing } from "../theme/spacing";
import { fontSizes, fonts } from "../theme/typography";

type Props = {
  visible: boolean;
  choices: LocationChoice[];
  selectedId: string | null;
  source: LocationSource | null;
  detectedPositionSource: "gps" | "simulated" | null;
  loading: boolean;
  areasLoading: boolean;
  areasError: string | null;
  preferenceError: string | null;
  gpsError: string | null;
  canOpenSettings: boolean;
  onClose: () => void;
  onUseGps: () => void;
  onOpenSettings: () => void;
  onRetryAreas: () => void;
  onSelect: (choice: LocationChoice) => void;
};

export function LocationPickerModal({
  visible,
  choices,
  selectedId,
  source,
  detectedPositionSource,
  loading,
  areasLoading,
  areasError,
  preferenceError,
  gpsError,
  canOpenSettings,
  onClose,
  onUseGps,
  onOpenSettings,
  onRetryAreas,
  onSelect,
}: Props) {
  return (
    <Modal animationType="fade" onRequestClose={onClose} transparent visible={visible}>
      <View style={styles.backdrop}>
        <View style={styles.sheet}>
          <Text style={styles.title}>{t("location.chooseTitle")}</Text>
          <Text style={styles.body}>{t("location.chooseBody")}</Text>
          {source === "gps" && <Text style={styles.sourceNotice}>{t("location.currentGpsLabel")}</Text>}
          {__DEV__ && source === "simulated" && <Text style={styles.sourceNotice}>{t("location.simulated")}</Text>}
          {source === null && detectedPositionSource === "gps" && <Text style={styles.sourceNotice}>{t("location.currentGpsLabel")}</Text>}
          {__DEV__ && source === null && detectedPositionSource === "simulated" && <Text style={styles.sourceNotice}>{t("location.simulated")}</Text>}
          <Pressable accessibilityRole="button" disabled={loading} onPress={onUseGps} style={styles.gpsButton}>
            {loading ? <ActivityIndicator color={colors.warmCream} /> : <Text style={styles.gpsText}>{t("location.useGps")}</Text>}
          </Pressable>
          {gpsError && <View accessibilityLiveRegion="polite" style={styles.errorBox}>
            <Text style={styles.errorText}>{gpsError}</Text>
            {canOpenSettings && <Pressable accessibilityRole="button" onPress={onOpenSettings}>
              <Text style={styles.retryText}>{t("location.openSettings")}</Text>
            </Pressable>}
          </View>}
          {preferenceError && <View accessibilityLiveRegion="polite" style={styles.errorBox}>
            <Text style={styles.errorText}>{preferenceError}</Text>
          </View>}
          {areasLoading && <ActivityIndicator color={colors.brandGreen} />}
          {areasError && <View style={styles.errorBox}>
            <Text style={styles.errorText}>{areasError}</Text>
            <Pressable accessibilityRole="button" onPress={onRetryAreas}>
              <Text style={styles.retryText}>{t("home.retry")}</Text>
            </Pressable>
          </View>}
          {!areasLoading && !areasError && choices.length === 0 && <View style={styles.errorBox}>
            <Text style={styles.errorText}>{t("location.noAreas")}</Text>
            <Pressable accessibilityRole="button" onPress={onRetryAreas}>
              <Text style={styles.retryText}>{t("home.retry")}</Text>
            </Pressable>
          </View>}
          <ScrollView contentContainerStyle={styles.options}>
            {choices.map((choice) => {
              const selected = choice.id === selectedId && source === "manual";
              return (
                <Pressable
                  accessibilityRole="button"
                  accessibilityState={{ selected }}
                  key={choice.id}
                  onPress={() => onSelect(choice)}
                  style={[styles.option, selected && styles.optionSelected]}
                >
                  <Text style={[styles.optionText, selected && styles.optionTextSelected]}>{choice.label}</Text>
                  {selected && <Text style={styles.selectedMark}>{t("location.selected")}</Text>}
                </Pressable>
              );
            })}
          </ScrollView>
          <Pressable accessibilityRole="button" onPress={onClose} style={styles.closeButton}>
            <Text style={styles.closeText}>{t("common.cancel")}</Text>
          </Pressable>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, justifyContent: "center", backgroundColor: "rgba(26,26,26,0.45)", padding: spacing.md },
  sheet: { maxHeight: "80%", gap: spacing.xs, borderRadius: radius.lg, backgroundColor: colors.warmCream, padding: spacing.md },
  title: { color: colors.darkCocoa, fontFamily: fonts.editorialSemiBold, fontSize: 24 },
  body: { color: colors.cocoaMuted, fontFamily: fonts.regular, fontSize: fontSizes.body, lineHeight: 21 },
  sourceNotice: { color: colors.brandGreen, fontFamily: fonts.semiBold, fontSize: fontSizes.caption },
  gpsButton: { minHeight: 48, alignItems: "center", justifyContent: "center", borderRadius: radius.sm, backgroundColor: colors.brandGreen, paddingHorizontal: spacing.sm },
  gpsText: { color: colors.warmCream, fontFamily: fonts.semiBold, fontSize: fontSizes.body },
  options: { gap: spacing.xs, paddingVertical: spacing.xxs },
  option: { minHeight: 48, flexDirection: "row", alignItems: "center", justifyContent: "space-between", borderWidth: 1, borderColor: colors.line, borderRadius: radius.sm, backgroundColor: colors.surface, paddingHorizontal: spacing.sm },
  optionSelected: { borderColor: colors.brandGreen, backgroundColor: colors.creamDeep },
  optionText: { color: colors.darkCocoa, fontFamily: fonts.medium, fontSize: fontSizes.body },
  optionTextSelected: { color: colors.brandGreen, fontFamily: fonts.bold },
  selectedMark: { color: colors.brandGreen, fontFamily: fonts.semiBold, fontSize: fontSizes.caption },
  errorBox: { gap: spacing.xxs, borderRadius: radius.sm, backgroundColor: colors.creamDeep, padding: spacing.xs },
  errorText: { color: colors.error, fontFamily: fonts.medium, fontSize: fontSizes.caption },
  retryText: { color: colors.brandGreen, fontFamily: fonts.semiBold, fontSize: fontSizes.caption },
  closeButton: { minHeight: 44, alignItems: "center", justifyContent: "center" },
  closeText: { color: colors.cocoaMuted, fontFamily: fonts.semiBold, fontSize: fontSizes.body },
});
