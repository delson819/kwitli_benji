export type ParsedAppUrl = {
  hostname?: string | null;
  path: string | null;
  queryParams?: Record<string, unknown> | null;
};

export function passwordResetTokenFromUrl(parsed: ParsedAppUrl): string | null {
  const path = parsed.path?.replace(/^\/+/, "");
  const hostname = parsed.hostname?.replace(/^\/+/, "");
  const token = parsed.queryParams?.token;
  if ((path ?? hostname) !== "reset-password" || typeof token !== "string" || !/^[A-Za-z0-9_-]{32,256}$/.test(token)) {
    return null;
  }
  return token;
}
