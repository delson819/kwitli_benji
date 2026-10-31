import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { t } from "../i18n";
import { colors } from "../theme/colors";
import { fonts } from "../theme/typography";
import { spacing } from "../theme/spacing";
import { radius } from "../theme/radius";
import { PrimaryButton } from "./PrimaryButton";

export function ClientReviewForm({ rating, comment, busy, error, onRating, onComment, onSubmit, onCancel }: {
  rating: number; comment: string; busy: boolean; onRating: (rating: number) => void;
  error?: string | null; onComment: (comment: string) => void; onSubmit: () => void; onCancel: () => void;
}) {
  return <View style={styles.card}>
    <Text accessibilityRole="header" style={styles.title}>{t("reviews.title")}</Text>
    <View style={styles.stars}>{[1, 2, 3, 4, 5].map((value) => <Pressable key={value}
      accessibilityRole="radio" accessibilityLabel={t("clientExperience.rating", { rating: value })}
      accessibilityState={{ checked: value === rating, disabled: busy }} disabled={busy}
      onPress={() => onRating(value)} style={styles.star}>
      <Text style={styles.starText}>{value <= rating ? "★" : "☆"}</Text>
    </Pressable>)}</View>
    <Text style={styles.text}>{t("reviews.comment")}</Text>
    <TextInput accessibilityLabel={t("reviews.comment")} value={comment} onChangeText={onComment}
      editable={!busy} multiline textAlignVertical="top" style={styles.input} />
    {!!error && <Text accessibilityRole="alert" style={styles.error}>{error}</Text>}
    <PrimaryButton label={t("reviews.send")} disabled={rating < 1} loading={busy} onPress={onSubmit} />
    <Pressable accessibilityRole="button" disabled={busy} onPress={onCancel} style={styles.cancel}>
      <Text style={styles.text}>{t("clientExperience.close")}</Text>
    </Pressable>
  </View>;
}
const styles = StyleSheet.create({
  card: { gap: spacing.sm, padding: spacing.md, borderRadius: radius.lg, backgroundColor: colors.surface },
  title: { fontFamily: fonts.editorialSemiBold, fontSize: 23, color: colors.darkCocoa },
  text: { fontFamily: fonts.medium, fontSize: 14, color: colors.brandGreen },
  stars: { flexDirection: "row", flexWrap: "wrap" },
  star: { minWidth: 44, minHeight: 44, alignItems: "center", justifyContent: "center" },
  starText: { color: colors.brandGreen, fontSize: 28 },
  input: { minHeight: 96, borderWidth: 1, borderColor: colors.line, borderRadius: radius.md, padding: spacing.sm, color: colors.darkCocoa, fontFamily: fonts.regular },
  error: { color: colors.error, fontFamily: fonts.regular, fontSize: 14 },
  cancel: { minHeight: 44, justifyContent: "center", alignItems: "center" },
});
