// Palette officielle : noir, orange, blanc (maquette 2026-10).
// Les anciens noms de jetons sont conserves pour que tous les ecrans suivent
// le nouveau design sans renommer chaque style.
const ink = "#1A1A1A";
const orange = "#F7891F";

export const colors = {
  // Jetons de la nouvelle charte.
  ink,
  accent: orange,
  // Fond peche du code de retrait.
  accentSoft: "#FDEBDA",
  // Vert lisible sur blanc (contraste AA) pour « Ouvert ».
  open: "#23863F",

  // Jetons historiques, remappes sur la nouvelle charte.
  brandGreen: ink,
  warmCream: "#FFFFFF",
  mangoOrange: orange,
  cornYellow: orange,
  darkCocoa: ink,
  mutedSage: "#E6E6E6",
  surface: "#FFFFFF",
  warmSurface: "#F7F7F7",
  creamDeep: "#F2F2F2",
  cocoaMuted: "#6B6B6B",
  line: "#EBEBEB",
  error: "#C0392B",
  success: "#23863F",
  transparent: "transparent",
} as const;
