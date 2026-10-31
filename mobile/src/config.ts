import { Platform } from "react-native";
import { resolveConfiguredApiUrl } from "./api-url";

// Origine uniquement; les services ajoutent explicitement le prefixe /api/v1.
export const API_URL = resolveConfiguredApiUrl(Platform.OS, __DEV__, {
  EXPO_PUBLIC_KWITLI_ENV: process.env.EXPO_PUBLIC_KWITLI_ENV,
  EXPO_PUBLIC_STAGING_API_URL: process.env.EXPO_PUBLIC_STAGING_API_URL,
  EXPO_PUBLIC_API_URL: process.env.EXPO_PUBLIC_API_URL,
});

export function isApiConfigured(): boolean {
  return API_URL.length > 0;
}

export function mediaUrl(photoUrl: string): string {
  return photoUrl.startsWith("http") ? photoUrl : `${API_URL}${photoUrl}`;
}
