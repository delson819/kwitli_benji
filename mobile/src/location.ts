export type Coordinates = { latitude: number; longitude: number };
export type LocationSource = "gps" | "simulated" | "manual";
export type LocationChoice = Coordinates & { id: string; label: string };
export type ServiceArea = LocationChoice & {
  code: string;
  country_code: string;
  country: string;
  city: string;
  radius_km: number;
  timezone: string;
  active: boolean;
};

export type GpsFix = Coordinates & { accuracy: number | null; timestamp: number };
export type DetectedDevicePosition = Coordinates & {
  source: "gps" | "simulated";
  accuracyMeters: number;
  timestamp: number;
};
export type LocationFailureReason = "gps_unavailable" | "permission_denied" | "permission_blocked"
  | "services_disabled" | "gps_timeout" | "gps_error" | "invalid_coordinates"
  | "stale_fix" | "missing_accuracy" | "low_accuracy" | "outside_active_areas"
  | "no_active_service_areas";
export type LocationResolution = {
  choice: LocationChoice | null;
  source: LocationSource | null;
  reason: "manual_preference" | "gps_current" | LocationFailureReason;
  accuracyMeters: number | null;
  detectedPosition: DetectedDevicePosition | null;
};

export const LOCATION_PREFERENCE_KEY = "kwitli.location.manual.v1";
export const LOCATION_MAX_AGE_MS = 2 * 60_000;
export const LOCATION_MAX_ACCURACY_METERS = 250;

type LocationPreferenceStorage = {
  getItem(key: string): Promise<string | null>;
  setItem(key: string, value: string): Promise<void>;
  removeItem(key: string): Promise<void>;
};

let locationPreferenceQueue: Promise<unknown> = Promise.resolve();

function serializeLocationPreferenceOperation<T>(operation: () => Promise<T>): Promise<T> {
  const result = locationPreferenceQueue.then(operation, operation);
  locationPreferenceQueue = result.then(() => undefined, () => undefined);
  return result;
}

export async function restoreManualLocationChoice(
  storage: Pick<LocationPreferenceStorage, "getItem">,
  serviceAreas: ServiceArea[],
): Promise<{ hasStoredChoice: boolean; choice: LocationChoice | null }> {
  const rawChoice = await storage.getItem(LOCATION_PREFERENCE_KEY);
  if (!rawChoice) return { hasStoredChoice: false, choice: null };
  let parsed: unknown;
  try {
    parsed = JSON.parse(rawChoice);
  } catch {
    return { hasStoredChoice: true, choice: null };
  }
  const saved = parseLocationChoice(parsed);
  if (!saved) return { hasStoredChoice: true, choice: null };
  return {
    hasStoredChoice: true,
    choice: serviceAreas.find((area) => area.active && area.id === saved.id) ?? null,
  };
}

export function saveManualLocationChoice(
  storage: Pick<LocationPreferenceStorage, "setItem">,
  choice: LocationChoice,
): Promise<void> {
  const canonical = parseLocationChoice(choice);
  if (!canonical) return Promise.reject(new Error("Invalid service-area choice"));
  return serializeLocationPreferenceOperation(() => storage.setItem(
    LOCATION_PREFERENCE_KEY,
    JSON.stringify(canonical),
  ));
}

export function clearManualLocationChoice(
  storage: Pick<LocationPreferenceStorage, "removeItem">,
): Promise<void> {
  return serializeLocationPreferenceOperation(() => storage.removeItem(LOCATION_PREFERENCE_KEY));
}

export function locationHomeMessageKind(
  reason: LocationResolution["reason"],
): "outside_service_area" | "gps_unavailable" | null {
  if (reason === "outside_active_areas") return "outside_service_area";
  if (reason === "no_active_service_areas") return null;
  if (reason === "manual_preference" || reason === "gps_current") return null;
  return "gps_unavailable";
}

export function shouldAcceptSimulatedPosition(isDevelopmentBuild: boolean): boolean {
  return isDevelopmentBuild;
}

export function shouldRequestForegroundPermission(permission: {
  granted: boolean;
  canAskAgain: boolean;
}): boolean {
  return !permission.granted && permission.canAskAgain;
}

export function shouldRefreshLocationAfterResume(
  wasBackgrounded: boolean,
  source: LocationSource | null,
): boolean {
  return wasBackgrounded && (source === "gps" || source === "simulated");
}

export function isValidCoordinates(value: unknown): value is Coordinates {
  if (!value || typeof value !== "object") return false;
  const coordinates = value as Coordinates;
  return Number.isFinite(coordinates.latitude) && Number.isFinite(coordinates.longitude)
    && coordinates.latitude >= -90 && coordinates.latitude <= 90
    && coordinates.longitude >= -180 && coordinates.longitude <= 180;
}

export function parseLocationChoice(value: unknown): LocationChoice | null {
  if (!isValidCoordinates(value)) return null;
  const choice = value as Partial<LocationChoice>;
  if (typeof choice.id !== "string" || !choice.id.trim()
      || typeof choice.label !== "string" || !choice.label.trim()) return null;
  return {
    id: choice.id.trim().slice(0, 80),
    label: choice.label.trim().slice(0, 100),
    latitude: (value as Coordinates).latitude,
    longitude: (value as Coordinates).longitude,
  };
}

function distanceKm(a: Coordinates, b: Coordinates): number {
  const radians = (degrees: number) => degrees * Math.PI / 180;
  const deltaLatitude = radians(b.latitude - a.latitude);
  const deltaLongitude = radians(b.longitude - a.longitude);
  const haversine = Math.sin(deltaLatitude / 2) ** 2
    + Math.cos(radians(a.latitude)) * Math.cos(radians(b.latitude)) * Math.sin(deltaLongitude / 2) ** 2;
  return 6_371 * 2 * Math.atan2(Math.sqrt(haversine), Math.sqrt(1 - haversine));
}

export function isInsideActiveServiceArea(
  coordinates: Coordinates,
  serviceAreas: ServiceArea[],
): boolean {
  return serviceAreas.some((area) => area.active
    && distanceKm(coordinates, area) <= area.radius_km);
}

export function activeServiceAreaLabels(serviceAreas: ServiceArea[]): string[] {
  return Array.from(new Set(serviceAreas.filter((area) => area.active)
    .map((area) => area.city || area.label).filter(Boolean)));
}

export function resolveLocation(input: {
  manualChoice?: LocationChoice | null;
  gpsFix?: GpsFix | null;
  isSimulated?: boolean;
  serviceAreas?: ServiceArea[];
  unavailableReason?: LocationFailureReason;
  now?: number;
  maxAgeMs?: number;
  maxAccuracyMeters?: number;
}): LocationResolution {
  const manualChoice = parseLocationChoice(input.manualChoice);
  const serviceAreas = input.serviceAreas ?? [];
  if (manualChoice) {
    const canonicalArea = serviceAreas.find((area) => area.active && area.id === manualChoice.id);
    if (canonicalArea) {
      return {
        choice: canonicalArea ?? manualChoice,
        source: "manual",
        reason: "manual_preference",
        accuracyMeters: null,
        detectedPosition: null,
      };
    }
  }

  const fix = input.gpsFix;
  if (!fix) return noGpsResolution(input.unavailableReason ?? "gps_unavailable");
  if (!isValidCoordinates(fix)) return noGpsResolution("invalid_coordinates");
  const now = input.now ?? Date.now();
  if (!Number.isFinite(fix.timestamp) || fix.timestamp > now + 30_000
      || now - fix.timestamp > (input.maxAgeMs ?? LOCATION_MAX_AGE_MS)) {
    return noGpsResolution("stale_fix");
  }
  if (fix.accuracy === null || !Number.isFinite(fix.accuracy) || fix.accuracy < 0) {
    return noGpsResolution("missing_accuracy");
  }
  if (fix.accuracy > (input.maxAccuracyMeters ?? LOCATION_MAX_ACCURACY_METERS)) {
    return noGpsResolution("low_accuracy");
  }
  const detectedPosition: DetectedDevicePosition = {
    latitude: fix.latitude,
    longitude: fix.longitude,
    source: input.isSimulated ? "simulated" : "gps",
    accuracyMeters: fix.accuracy,
    timestamp: fix.timestamp,
  };
  if (!serviceAreas.some((area) => area.active)) {
    return {
      choice: null,
      source: null,
      reason: "no_active_service_areas",
      accuracyMeters: fix.accuracy,
      detectedPosition,
    };
  }
  if (!isInsideActiveServiceArea(fix, serviceAreas)) {
    return {
      choice: null,
      source: null,
      reason: "outside_active_areas",
      accuracyMeters: fix.accuracy,
      detectedPosition,
    };
  }
  return {
    choice: {
      id: "current-gps",
      label: "Position GPS",
      latitude: fix.latitude,
      longitude: fix.longitude,
    },
    source: input.isSimulated ? "simulated" : "gps",
    reason: "gps_current",
    accuracyMeters: fix.accuracy,
    detectedPosition,
  };
}

function noGpsResolution(
  reason: LocationFailureReason,
): LocationResolution {
  return { choice: null, source: null, reason, accuracyMeters: null, detectedPosition: null };
}
