import { Text, View, StyleSheet } from "react-native";
import { t } from "../i18n";
import { colors } from "../theme/colors";
import { fonts } from "../theme/typography";
import { spacing } from "../theme/spacing";
import { radius } from "../theme/radius";
import { BrandWordmark } from "./BrandWordmark";
import { PrimaryButton } from "./PrimaryButton";

// Accueil de la maquette : logo au point orange, slogan, puis les trois etapes numerotees.
export function ClientWelcome({ onContinue }: { onContinue: () => void }) {
  return <View style={styles.page}>
    <View style={styles.brandBlock}>
      <BrandWordmark size={44} />
      <Text style={styles.tagline}>{t("brand.tagline")}</Text>
    </View>
    {([1, 2, 3] as const).map((step) => <View key={step} style={styles.step}>
      <View style={styles.stepNumber}>
        <Text style={styles.stepNumberText}>{step}</Text>
      </View>
      <View style={styles.stepCopy}>
        <Text accessibilityRole="header" style={styles.title}>{t(`clientExperience.onboardingTitle${step}`)}</Text>
        <Text style={styles.body}>{t(`clientExperience.onboardingBody${step}`)}</Text>
      </View>
    </View>)}
    <PrimaryButton label={t("clientExperience.discover")} onPress={onContinue} />
  </View>;
}
const styles = StyleSheet.create({
  page: { gap: spacing.md, paddingTop: spacing.sm },
  brandBlock: { gap: spacing.xs, paddingBottom: spacing.xs },
  tagline: { fontFamily: fonts.bold, fontSize: 18, color: colors.ink },
  step: { flexDirection: "row", alignItems: "flex-start", gap: spacing.sm, padding: spacing.md, borderRadius: radius.lg, backgroundColor: colors.warmSurface },
  stepNumber: { width: 36, height: 36, alignItems: "center", justifyContent: "center", borderRadius: 18, backgroundColor: colors.accent },
  stepNumberText: { fontFamily: fonts.extraBold, fontSize: 16, color: colors.ink },
  stepCopy: { flex: 1, gap: spacing.xxs },
  title: { fontFamily: fonts.extraBold, fontSize: 20, lineHeight: 26, letterSpacing: -0.4, color: colors.ink },
  body: { fontFamily: fonts.regular, fontSize: 15, lineHeight: 23, color: colors.cocoaMuted },
});
