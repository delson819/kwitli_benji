export const SUPPORTED_LOCALES = [
  "fr",
  "es-CO",
  "es-MX",
  "pt-BR",
  "fr-SN",
  "fr-BJ",
  "fr-CI",
  "en-PH",
  "fil-PH",
  "vi-VN",
  "ar",
  "fa",
  "ja",
  "ko",
] as const;

export type Locale = (typeof SUPPORTED_LOCALES)[number];

export type LanguageConfig = {
  activeLocale: Locale;
  fallbackLocale: Locale;
};

// La langue de travail reste independante du marche actif.
export const LANGUAGE_CONFIG = {
  activeLocale: "fr",
  fallbackLocale: "fr",
} as const satisfies LanguageConfig;

export const ACTIVE_LOCALE: Locale = LANGUAGE_CONFIG.activeLocale;
