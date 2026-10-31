import type { DiscoverItem, PublicCookProfile } from "./services/api";

// Les champs absents du profil public restent inconnus, jamais inventes.
export function menuArticle(profile: PublicCookProfile, dishId: string): DiscoverItem | null {
  const dish = profile.available_dishes.find((item) => item.dish_id === dishId);
  if (!dish) return null;
  return {
    availability_id: null, dish_id: dish.dish_id, dish_name: dish.name,
    cook_id: profile.cook_id, cook_display_name: profile.display_name, profile_photo_url: profile.profile_photo_url,
    business_vertical: profile.business_vertical,
    description: dish.description, cook_rating: profile.rating_average ?? "0",
    rating_average: profile.rating_average, review_count: profile.rating_count,
    photo_url: dish.photo_url, price: dish.price, currency: dish.currency,
    remaining_portions: null,
    available_date: null, start_time: null, end_time: null,
    ready_at: null, featured_type: null, distance_km: null,
    is_open: profile.is_open,
  };
}
