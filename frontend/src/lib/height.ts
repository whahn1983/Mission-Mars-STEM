import type { PublicSettings } from "../api/types";

export const DEFAULT_HEIGHTS_M = [0.1, 0.2, 0.3];

/** Drop heights the student can choose from (the operator's list), sorted. */
export function heightOptions(settings: PublicSettings | null | undefined): number[] {
  const list = settings?.drop_height_options_m?.length ? settings.drop_height_options_m : DEFAULT_HEIGHTS_M;
  return [...new Set(list)].sort((a, b) => a - b);
}

const same = (a: number, b: number) => Math.abs(a - b) < 1e-6;

/**
 * The drop height for this mission: the student's choice if it is still one
 * of the options, otherwise the station default if listed, otherwise the
 * lowest option (the gentlest drop).
 */
export function effectiveHeight(settings: PublicSettings | null | undefined, chosen: number | null): number {
  const opts = heightOptions(settings);
  if (chosen !== null && opts.some((h) => same(h, chosen))) return chosen;
  const def = settings?.drop_height_m;
  if (def != null && opts.some((h) => same(h, def))) return def;
  return opts[0];
}

export const isSameHeight = same;
