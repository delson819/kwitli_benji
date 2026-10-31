from datetime import timedelta
from typing import Literal

DiscoveryFilter = Literal["nearby", "fresh", "low_stock", "new"]
BusinessVertical = Literal["food_service", "bakery_dessert", "local_shop"]
DEFAULT_BUSINESS_VERTICAL = "food_service"
BUSINESS_VERTICALS = frozenset({"food_service", "bakery_dessert", "local_shop"})

NEARBY_RADIUS_KM = 1.0
DISTANCE_COMPARISON_EPSILON_KM = 1e-9
FRESH_MAX_AGE = timedelta(minutes=30)
NEW_DISH_MAX_AGE = timedelta(days=7)
FEATURED_DISCOVERY_TYPES = frozenset({"new", "dish_of_month", "discovery", "discount"})
