import {
  buildDiscoverPath,
  BUSINESS_VERTICALS,
  EXPLORE_RADIUS_OPTIONS,
  VISIBLE_CLIENT_VERTICALS,
  homeDiscoveryRadius,
  shouldShowHomeCauldron,
} from "./discovery.ts";

function expect(condition: boolean): void {
  if (!condition) throw new Error("Client discovery assertion failed.");
}

expect(EXPLORE_RADIUS_OPTIONS.join(",") === "5,10,20,30");
expect(BUSINESS_VERTICALS.join(",") === "food_service,bakery_dessert,local_shop");
expect(VISIBLE_CLIENT_VERTICALS.join(",") === "food_service");
expect(homeDiscoveryRadius("nearby", 1, 5) === 1);
expect(homeDiscoveryRadius("fresh", 1, 5) === 5);
expect(homeDiscoveryRadius("low_stock", 1, 5) === 5);
expect(homeDiscoveryRadius("new", 1, 5) === 5);
expect(shouldShowHomeCauldron("nearby", 0));
expect(!shouldShowHomeCauldron("nearby", 1));
expect(!shouldShowHomeCauldron("fresh", 0));
expect(
  buildDiscoverPath({ latitude: 4.65, longitude: -74.06, radiusKm: 30 })
    === "/api/v1/discover?latitude=4.65&longitude=-74.06&radius_km=30",
);
expect(
  buildDiscoverPath({ latitude: 4.65, longitude: -74.06, radiusKm: 1, filter: "nearby" })
    === "/api/v1/discover?latitude=4.65&longitude=-74.06&radius_km=1&filter=nearby",
);
expect(
  buildDiscoverPath({ latitude: 4.65, longitude: -74.06, radiusKm: 1, filter: "nearby", vertical: "bakery_dessert" })
    === "/api/v1/discover?latitude=4.65&longitude=-74.06&radius_km=1&filter=nearby&vertical=bakery_dessert",
);
expect(
  buildDiscoverPath({ latitude: 4.65, longitude: -74.06, radiusKm: 1, filter: "nearby", vertical: VISIBLE_CLIENT_VERTICALS[0] })
    === "/api/v1/discover?latitude=4.65&longitude=-74.06&radius_km=1&filter=nearby&vertical=food_service",
);

const currentDevicePosition = { latitude: 45.405123, longitude: -71.893456 };
expect(
  buildDiscoverPath({ ...currentDevicePosition, radiusKm: 1, filter: "nearby" })
    === "/api/v1/discover?latitude=45.405123&longitude=-71.893456&radius_km=1&filter=nearby",
);
