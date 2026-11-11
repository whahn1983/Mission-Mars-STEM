import { describe, expect, it } from "vitest";
import type { Criteria } from "../api/types";
import { categoryOptions, measuredCategory, numberPrediction, predictionVerdict, rangeOptions } from "./predict";

const criteria: Criteria = {
  success_max_peak_g: 8,
  mass_budget_kg: 0.35,
  require_payload_retained: true,
  require_stable_landing: true,
  gentle_max_g: 4,
  medium_max_g: 8,
};

describe("prediction helpers", () => {
  it("builds grade 1–4 categories from the classroom criteria", () => {
    const opts = categoryOptions(criteria);
    expect(opts.map((o) => o.label)).toEqual(["Gentle", "Medium", "Hard"]);
    expect(opts[1].payload).toMatchObject({ kind: "category", low_g: 4, high_g: 8 });
    expect(opts[2].payload.high_g).toBeNull();
  });

  it("adds an open-ended top option for grades 5–8", () => {
    const opts = rangeOptions([
      [0, 2],
      [2, 4],
    ]);
    expect(opts).toHaveLength(3);
    expect(opts[2].payload).toMatchObject({ low_g: 4, high_g: null });
  });

  it("judges range predictions with an exclusive upper bound", () => {
    const p = { kind: "range" as const, label: "4–6 g", low_g: 4, high_g: 6 };
    expect(predictionVerdict(p, 5, "58")?.good).toBe(true);
    expect(predictionVerdict(p, 6, "58")?.good).toBe(false);
    expect(predictionVerdict(p, 3, "58")?.text).toMatch(/gentler/);
  });

  it("reports numeric error for grades 9–12", () => {
    const v = predictionVerdict(numberPrediction(6), 8, "912");
    expect(v?.text).toContain("2.0 g");
    expect(v?.good).toBe(false);
    expect(predictionVerdict(numberPrediction(6), 6.4, "912")?.good).toBe(true);
  });

  it("returns no verdict without a valid measurement", () => {
    expect(predictionVerdict(numberPrediction(6), null, "912")).toBeNull();
  });

  it("maps measured peaks to categories", () => {
    expect(measuredCategory(3.9, criteria)).toBe("Gentle");
    expect(measuredCategory(4.0, criteria)).toBe("Medium");
    expect(measuredCategory(8.0, criteria)).toBe("Hard");
  });
});
