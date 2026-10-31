import fr from "../locales/fr.json";
import esCO from "../locales/es-CO.json";
import { ACTIVE_LOCALE, type Locale } from "./language";

export type { Locale } from "./language";
export type TranslationKey = keyof typeof fr;
type TranslationParams = Record<string, string | number>;
type TranslationCatalog = Record<TranslationKey, string>;

const frenchCatalog: TranslationCatalog = fr;
const spanishColombiaCatalog: TranslationCatalog = esCO;
const catalogs: Partial<Record<Locale, TranslationCatalog>> = {
  fr: frenchCatalog,
  "es-CO": spanishColombiaCatalog,
};

export function t(
  key: TranslationKey,
  params: TranslationParams = {},
  locale: Locale = ACTIVE_LOCALE,
): string {
  const template = catalogs[locale]?.[key] ?? frenchCatalog[key] ?? key;
  return template.replace(/\{([a-zA-Z0-9_]+)\}/g, (match, name: string) => (
    Object.prototype.hasOwnProperty.call(params, name) ? String(params[name]) : match
  ));
}
