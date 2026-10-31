export type DiscoverFilter = "nearby" | "fresh" | "low_stock" | "new";
export type BusinessVertical = "food_service" | "bakery_dessert" | "local_shop";

export const DEFAULT_BUSINESS_VERTICAL: BusinessVertical = "food_service";
export const BUSINESS_VERTICALS: BusinessVertical[] = ["food_service", "bakery_dessert", "local_shop"];
export const VISIBLE_CLIENT_VERTICALS: BusinessVertical[] = ["food_service"];

export const EXPLORE_RADIUS_OPTIONS = [5, 10, 20, 30] as const;

export function homeDiscoveryRadius(
  filter: DiscoverFilter,
  nearbyRadiusKm: number,
  defaultRadiusKm: number,
): number {
  return filter === "nearby" ? nearbyRadiusKm : defaultRadiusKm;
}

export function shouldShowHomeCauldron(filter: DiscoverFilter, resultCount: number): boolean {
  return filter === "nearby" && resultCount === 0;
}

export function buildDiscoverPath(location: {
  latitude: number;
  longitude: number;
  radiusKm: number;
  filter?: DiscoverFilter;
  vertical?: BusinessVertical;
}): string {
  const filterQuery = location.filter ? `&filter=${encodeURIComponent(location.filter)}` : "";
  const verticalQuery = location.vertical ? `&vertical=${encodeURIComponent(location.vertical)}` : "";
  return `/api/v1/discover?latitude=${location.latitude}&longitude=${location.longitude}&radius_km=${location.radiusKm}${filterQuery}${verticalQuery}`;
}
