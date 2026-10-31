import { StyleSheet, Text, View } from "react-native";

import { t } from "../i18n";
import { colors } from "../theme/colors";
import { fonts } from "../theme/typography";

// Logo texte de la maquette : minuscules tres grasses, point orange sur le premier « i ».
export function BrandWordmark({ size = 34, color = colors.ink }: { size?: number; color?: string }) {
  const text = { fontFamily: fonts.extraBold, fontSize: size, lineHeight: size * 1.1, letterSpacing: -size * 0.04, color };
  const dot = size * 0.24;
  return <View accessible accessibilityRole="header" accessibilityLabel={t("brand.name")} style={styles.row}>
    <Text style={text}>kw</Text>
    <View style={styles.dottedLetter}>
      <View style={[styles.dot, { width: dot, height: dot, borderRadius: dot / 2, marginBottom: -size * 0.37 }]} />
      {/* « ı » sans point : le point orange le remplace. */}
      <Text style={text}>ı</Text>
    </View>
    <Text style={text}>tli</Text>
  </View>;
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "flex-end", alignSelf: "flex-start" },
  dottedLetter: { alignItems: "center" },
  dot: { backgroundColor: colors.accent },
});
