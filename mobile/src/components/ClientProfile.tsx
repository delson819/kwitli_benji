import Ionicons from "@expo/vector-icons/Ionicons";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { t } from "../i18n";
import { colors } from "../theme/colors";
import { radius } from "../theme/radius";
import { spacing } from "../theme/spacing";
import { fonts } from "../theme/typography";

type ProfileRowProps = {
  icon: keyof typeof Ionicons.glyphMap;
  label: string;
  value?: string;
  onPress?: () => void;
};

function ProfileRow({ icon, label, value, onPress }: ProfileRowProps) {
  const content = <>
    <View style={styles.iconWrap}><Ionicons color={colors.brandGreen} name={icon} size={19} /></View>
    <View style={styles.rowCopy}>
      <Text style={styles.rowLabel}>{label}</Text>
      {!!value && <Text style={styles.rowValue}>{value}</Text>}
    </View>
    {onPress && <Ionicons color={colors.cocoaMuted} name="chevron-forward" size={18} />}
  </>;

  return onPress ? <Pressable accessibilityRole="button" onPress={onPress}
    style={({ pressed }) => [styles.row, pressed && styles.pressed]}>{content}</Pressable>
    : <View style={styles.row}>{content}</View>;
}

export function ClientProfile({ firstName, lastName, email, onPrivacy, onLogout }: {
  firstName: string;
  lastName: string | null;
  email: string;
  onPrivacy: () => void;
  onLogout: () => void;
}) {
  const name = [firstName, lastName].filter(Boolean).join(" ");
  const initial = firstName.trim().charAt(0).toLocaleUpperCase();

  return <View style={styles.page}>
    <Text accessibilityRole="header" style={styles.title}>{t("profile.title")}</Text>
    <View style={styles.identity}>
      <View style={styles.avatar}><Text style={styles.initial}>{initial}</Text></View>
      <View style={styles.identityCopy}>
        <Text style={styles.name}>{name}</Text>
        <Text style={styles.email}>{email}</Text>
      </View>
    </View>

    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{t("clientProfile.account")}</Text>
      <View style={styles.card}>
        <ProfileRow icon="person-outline" label={t("clientProfile.personalInformation")} value={name} />
        <View style={styles.divider} />
        <ProfileRow icon="language-outline" label={t("clientProfile.language")} value={t("clientExperience.languageName")} />
      </View>
    </View>

    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{t("clientProfile.preferences")}</Text>
      <View style={styles.card}>
        <ProfileRow icon="notifications-outline" label={t("clientProfile.notifications")} value={t("clientProfile.notificationsUnavailable")} />
      </View>
    </View>

    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{t("clientProfile.privacySection")}</Text>
      <View style={styles.card}>
        <ProfileRow icon="shield-checkmark-outline" label={t("clientProfile.privacy")} onPress={onPrivacy} />
      </View>
    </View>

    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{t("clientProfile.session")}</Text>
      <Pressable accessibilityRole="button" onPress={onLogout}
        style={({ pressed }) => [styles.logout, pressed && styles.pressed]}>
        <Ionicons color={colors.brandGreen} name="log-out-outline" size={19} />
        <Text style={styles.logoutText}>{t("auth.logout")}</Text>
      </Pressable>
    </View>
  </View>;
}

const styles = StyleSheet.create({
  page: { gap: spacing.lg },
  title: { color: colors.darkCocoa, fontFamily: fonts.editorialSemiBold, fontSize: 32, lineHeight: 38 },
  identity: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingVertical: spacing.xs },
  avatar: { width: 76, height: 76, alignItems: "center", justifyContent: "center", borderRadius: radius.pill, backgroundColor: colors.mutedSage },
  initial: { color: colors.brandGreen, fontFamily: fonts.editorialBold, fontSize: 30 },
  identityCopy: { minWidth: 0, flex: 1, gap: spacing.xxs },
  name: { color: colors.darkCocoa, fontFamily: fonts.editorialSemiBold, fontSize: 25, lineHeight: 31 },
  email: { color: colors.cocoaMuted, fontFamily: fonts.regular, fontSize: 14, lineHeight: 21 },
  section: { gap: spacing.xs },
  sectionTitle: { paddingHorizontal: spacing.xxs, color: colors.brandGreen, fontFamily: fonts.bold, fontSize: 14 },
  card: { overflow: "hidden", borderWidth: 1, borderColor: colors.line, borderRadius: radius.lg, backgroundColor: colors.surface },
  row: { minHeight: 64, flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingHorizontal: spacing.sm, paddingVertical: spacing.xs },
  iconWrap: { width: 36, height: 36, alignItems: "center", justifyContent: "center", borderRadius: radius.pill, backgroundColor: colors.creamDeep },
  rowCopy: { minWidth: 0, flex: 1, gap: spacing.xxs },
  rowLabel: { color: colors.darkCocoa, fontFamily: fonts.semiBold, fontSize: 15 },
  rowValue: { color: colors.cocoaMuted, fontFamily: fonts.regular, fontSize: 13, lineHeight: 19 },
  divider: { height: StyleSheet.hairlineWidth, marginLeft: 60, backgroundColor: colors.line },
  logout: { minHeight: 52, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.xs, borderWidth: 1, borderColor: colors.line, borderRadius: radius.lg, backgroundColor: colors.surface },
  logoutText: { color: colors.brandGreen, fontFamily: fonts.bold, fontSize: 15 },
  pressed: { opacity: 0.72 },
});
