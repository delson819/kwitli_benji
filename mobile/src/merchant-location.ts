import { isInsideActiveServiceArea, isValidCoordinates, type Coordinates, type ServiceArea } from "./location";

export type MerchantGpsFix = Coordinates & {
  accuracy: number | null;
  timestamp: number;
  mocked?: boolean;
};

export type MerchantGpsFailure = "simulated" | "invalid_coordinates" | "stale" | "missing_accuracy" | "low_accuracy";

export type MerchantGpsValidation =
  | { coordinates: Coordinates; accuracyMeters: number; timestamp: number }
  | { error: MerchantGpsFailure };

export type MerchantServiceAreaAssessment =
  | { status: "unknown"; areaLabel: null }
  | { status: "inside"; areaLabel: string }
  | { status: "outside"; areaLabel: null };

export function validateMerchantGpsFix(
  fix: MerchantGpsFix,
  options: { now?: number; maxAgeMs?: number; maxAccuracyMeters?: number; simulated?: boolean } = {},
): MerchantGpsValidation {
  if (options.simulated || fix.mocked) return { error: "simulated" };
  if (!isValidCoordinates(fix)) return { error: "invalid_coordinates" };
  const now = options.now ?? Date.now();
  if (!Number.isFinite(fix.timestamp) || fix.timestamp > now + 30_000
      || now - fix.timestamp > (options.maxAgeMs ?? 2 * 60_000)) return { error: "stale" };
  if (fix.accuracy === null || !Number.isFinite(fix.accuracy) || fix.accuracy < 0) {
    return { error: "missing_accuracy" };
  }
  if (fix.accuracy > (options.maxAccuracyMeters ?? 250)) return { error: "low_accuracy" };
  return {
    coordinates: { latitude: fix.latitude, longitude: fix.longitude },
    accuracyMeters: fix.accuracy,
    timestamp: fix.timestamp,
  };
}

export function assessMerchantServiceArea(
  coordinates: Coordinates | null,
  activeAreas: ServiceArea[],
): MerchantServiceAreaAssessment {
  const usableAreas = activeAreas.filter((area) => area.active);
  if (!coordinates || usableAreas.length === 0) return { status: "unknown", areaLabel: null };
  if (!isInsideActiveServiceArea(coordinates, usableAreas)) return { status: "outside", areaLabel: null };
  const area = usableAreas.find((candidate) => isInsideActiveServiceArea(coordinates, [candidate]));
  return { status: "inside", areaLabel: area?.label ?? area?.city ?? "" };
}
