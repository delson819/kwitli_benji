const LOCAL_HOSTS = {
  android: "10.0.2.2",
  other: "127.0.0.1",
} as const;

export type ApiEnvironment = {
  EXPO_PUBLIC_KWITLI_ENV?: string;
  EXPO_PUBLIC_STAGING_API_URL?: string;
  EXPO_PUBLIC_API_URL?: string;
};

export function resolveConfiguredApiUrl(platform: string, development: boolean, environment: ApiEnvironment): string {
  if (environment.EXPO_PUBLIC_KWITLI_ENV === "staging") {
    if (!environment.EXPO_PUBLIC_STAGING_API_URL) return "";
    return resolveApiUrl(platform, development, environment.EXPO_PUBLIC_STAGING_API_URL);
  }
  return resolveApiUrl(platform, development, environment.EXPO_PUBLIC_API_URL);
}

function isSimulatorHost(host: string): boolean {
  const normalized = host.replace(/\.$/, "");
  return normalized === "localhost" || normalized === "127.0.0.1" || normalized === "10.0.2.2";
}

function isPrivateHost(host: string): boolean {
  const normalized = host.replace(/\.$/, "");
  if (isSimulatorHost(normalized) || normalized.endsWith(".localhost") || normalized.endsWith(".local")) return true;
  // En production l'API doit avoir un nom public, jamais une adresse IP brute.
  return normalized.startsWith("[") || /^\d+\.\d+\.\d+\.\d+$/.test(normalized);
}

export function resolveApiUrl(platform: string, development: boolean, configuredUrl?: string): string {
  const configured = configuredUrl?.trim();
  if (!configured && !development) return "";

  let url: URL | null = null;
  if (configured) {
    try {
      url = new URL(configured);
    } catch {
      return "";
    }
    if (!(["http:", "https:"].includes(url.protocol)) || url.username || url.password ||
        url.pathname !== "/" || url.search || url.hash) return "";
  }

  if (development) {
    if (!url || isSimulatorHost(url.hostname)) {
      const host = platform === "android" ? LOCAL_HOSTS.android : LOCAL_HOSTS.other;
      return `http://${host}:${url?.port || "8000"}`;
    }
    return url.origin;
  }

  return url?.protocol === "https:" && !isPrivateHost(url.hostname) ? url.origin : "";
}
