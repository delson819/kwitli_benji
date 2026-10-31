import { ACTIVE_LOCALE, type Locale } from "./language";
import { ACTIVE_MARKET, ACTIVE_MARKET_TIMEZONE, resolveTimezone } from "./market";

export function formatMoney(
  value: string | number,
  currency = ACTIVE_MARKET.currency,
  locale: Locale = ACTIVE_LOCALE,
): string {
  // L'espace fine insecable (U+202F) du francais est presque invisible a l'ecran :
  // « 3 000 » s'affichait « 3000 ». Une espace insecable normale reste lisible.
  return Number(value).toLocaleString(locale, {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).replace(/ /g, " ");
}

export function formatRating(value: string | number, locale: Locale = ACTIVE_LOCALE): string {
  return Number(value).toLocaleString(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}

export function formatReviewDate(
  value: string | null | undefined,
  locale: Locale = ACTIVE_LOCALE,
  businessTimezone?: string,
): string {
  if (!value) return "";
  const date = new Date(/[zZ]|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleDateString(locale, {
    day: "numeric", month: "long", year: "numeric",
    timeZone: resolveTimezone(businessTimezone, ACTIVE_MARKET_TIMEZONE),
  });
}

export function formatTime(value: string | null | undefined, locale: Locale = ACTIVE_LOCALE): string {
  if (!value) return "";
  const [hours, minutes] = value.split(":").map(Number);
  const time = new Date(Date.UTC(2000, 0, 1, hours, minutes));
  if (Number.isNaN(time.getTime())) return value;
  return new Intl.DateTimeFormat(locale, {
    hour: "numeric",
    minute: "2-digit",
    timeZone: "UTC",
  }).format(time);
}

export function formatDistance(
  valueInKilometers: number,
  measurementSystem = ACTIVE_MARKET.measurementSystem,
  locale: Locale = ACTIVE_LOCALE,
): string {
  const value = measurementSystem === "metric" ? valueInKilometers : valueInKilometers * 0.621371;
  const unit = measurementSystem === "metric" ? "km" : "mi";
  const formattedValue = new Intl.NumberFormat(locale, {
    maximumFractionDigits: 1,
    minimumFractionDigits: value < 1 ? 1 : 0,
  }).format(value);
  return `${formattedValue} ${unit}`;
}

export function formatDate(
  value: string | null | undefined,
  locale: Locale = ACTIVE_LOCALE,
  timezone = ACTIVE_MARKET_TIMEZONE,
): string {
  if (typeof value !== "string" || value.trim() === "") return "";
  const [year, month, day] = value.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day, 12));
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(locale, {
    weekday: "short",
    day: "numeric",
    month: "short",
    timeZone: resolveTimezone(undefined, timezone),
  }).format(date);
}
