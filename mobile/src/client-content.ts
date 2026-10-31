const INTERNAL_DESCRIPTION = /(?:\bdev\b|\bsandbox\b|\bpaydunya\b|\bflutterwave\b|\bpaytech\b)/i;

export function clientDescription(description: string | null | undefined): string | null {
  const value = description?.trim();
  return value && !INTERNAL_DESCRIPTION.test(value) ? value : null;
}

export function clientDisplayName(name: string): string {
  return name.replace(/\bDEV\b/gi, "").replace(/\s{2,}/g, " ").trim();
}

export function groupDiscoverItemsByBusiness<T extends { cook_id: string }>(items: T[]): T[][] {
  const groups = new Map<string, T[]>();
  for (const item of items) {
    const group = groups.get(item.cook_id);
    if (group) group.push(item);
    else groups.set(item.cook_id, [item]);
  }
  return Array.from(groups.values());
}
