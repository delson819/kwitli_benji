// Les titres passent d'une serif editoriale a une sans-serif tres grasse,
// comme dans la maquette officielle.
export const fonts = {
  editorialSemiBold: "Manrope_700Bold",
  editorialBold: "Manrope_800ExtraBold",
  regular: "Manrope_400Regular",
  medium: "Manrope_500Medium",
  semiBold: "Manrope_600SemiBold",
  bold: "Manrope_700Bold",
  extraBold: "Manrope_800ExtraBold",
} as const;

export const fontSizes = {
  caption: 12,
  bodySmall: 14,
  body: 16,
  subtitle: 20,
  cardTitle: 24,
  sectionTitle: 22,
  title: 30,
  display: 34,
} as const;

export const lineHeights = {
  caption: 16,
  bodySmall: 20,
  body: 24,
  subtitle: 26,
  title: 35,
  display: 39,
} as const;
