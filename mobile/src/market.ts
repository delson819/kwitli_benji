import type { Locale } from "./language";

export type MarketConfig = {
  countryCode: string;
  defaultLocale: Locale;
  currency: string;
  timezone: string;
  paymentProvider: "payu" | "flutterwave";
  measurementSystem: "metric" | "imperial";
  nearbyRadiusKm: number;
  defaultRadiusKm: number;
};

export const MARKETS = {
  SN: {
    countryCode: "SN",
    defaultLocale: "fr",
    currency: "XOF",
    timezone: "Africa/Dakar",
    paymentProvider: "flutterwave",
    measurementSystem: "metric",
    nearbyRadiusKm: 1,
    defaultRadiusKm: 5,
  },
  CO: {
    countryCode: "CO",
    defaultLocale: "es-CO",
    currency: "COP",
    timezone: "America/Bogota",
    paymentProvider: "payu",
    measurementSystem: "metric",
    nearbyRadiusKm: 1,
    defaultRadiusKm: 5,
  },
} as const satisfies Record<string, MarketConfig>;

export type MarketCode = keyof typeof MARKETS;

export const MARKET_TIMEZONES: Record<string, string> = {
  SN: "Africa/Dakar",
  CI: "Africa/Abidjan",
  BJ: "Africa/Porto-Novo",
  TG: "Africa/Lome",
  CM: "Africa/Douala",
  GN: "Africa/Conakry",
  CA: "America/Toronto",
  CO: "America/Bogota",
};

export function isMarketCode(value: string): value is MarketCode {
  return Object.prototype.hasOwnProperty.call(MARKETS, value.toUpperCase());
}

export function resolveTimezone(
  businessTimezone: string | undefined,
  marketTimezone: string,
  configuredFallback = "UTC",
): string {
  for (const candidate of [businessTimezone, marketTimezone, configuredFallback, "UTC"]) {
    if (!candidate) continue;
    try {
      new Intl.DateTimeFormat("en", { timeZone: candidate });
      return candidate;
    } catch {
      // Try the next configured source.
    }
  }
  return "UTC";
}

const configuredCode = process.env.EXPO_PUBLIC_MARKET_CODE?.toUpperCase();
export const ACTIVE_MARKET_CODE: MarketCode =
  configuredCode && isMarketCode(configuredCode) ? configuredCode : "SN";
const selectedMarket = MARKETS[ACTIVE_MARKET_CODE];
const timezoneMarketCode = process.env.EXPO_PUBLIC_TIMEZONE_MARKET_CODE?.toUpperCase();
const configuredTimezone = timezoneMarketCode ? MARKET_TIMEZONES[timezoneMarketCode] : undefined;
export const ACTIVE_MARKET_TIMEZONE = resolveTimezone(
  undefined,
  configuredTimezone ?? selectedMarket.timezone,
  process.env.EXPO_PUBLIC_MARKET_TIMEZONE,
);
export const ACTIVE_MARKET: MarketConfig = {
  ...selectedMarket,
  timezone: ACTIVE_MARKET_TIMEZONE,
};
