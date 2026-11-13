import { describe, expect, it } from "vitest";
import type { PublicSettings } from "../api/types";
import { effectiveHeight, heightOptions } from "./height";

const settings = (drop_height_m: number, drop_height_options_m: number[]) => ({ drop_height_m, drop_height_options_m }) as PublicSettings;

describe("drop height helpers", () => {
  it("lists the operator's heights sorted, without duplicates", () => {
    expect(heightOptions(settings(0.2, [0.3, 0.1, 0.3]))).toEqual([0.1, 0.3]);
    expect(heightOptions(null)).toEqual([0.1, 0.2, 0.3]);
  });

  it("uses the student's choice while it is still offered", () => {
    expect(effectiveHeight(settings(0.2, [0.1, 0.2, 0.3]), 0.3)).toBe(0.3);
  });

  it("falls back to the station default, then to the lowest height", () => {
    expect(effectiveHeight(settings(0.2, [0.1, 0.2, 0.3]), null)).toBe(0.2);
    expect(effectiveHeight(settings(0.2, [0.1, 0.2, 0.3]), 0.5)).toBe(0.2);
    expect(effectiveHeight(settings(0.5, [0.15, 0.1]), null)).toBe(0.1);
  });
});
