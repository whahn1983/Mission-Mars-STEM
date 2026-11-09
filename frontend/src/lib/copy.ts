import type { GradeBand } from "../api/types";

export const GRADE_BANDS: { id: GradeBand; label: string; title: string; icon: string }[] = [
  { id: "k4", label: "Grades 1–4", title: "Cadet", icon: "🚀" },
  { id: "58", label: "Grades 5–8", title: "Engineer", icon: "🛠️" },
  { id: "912", label: "Grades 9–12", title: "Flight Director", icon: "📡" },
];

export const BRIEFING = {
  k4: {
    lead: "Help our lander touch down softly on Mars!",
    body: "Inside the lander is a special science sensor. Your job is to build legs that keep it safe.",
    reqs: [
      { title: "Keep it safe", body: "Protect the science sensor inside." },
      { title: "Land softly", body: "A gentle bump is better than a big crash." },
      { title: "Not too heavy", body: "Rockets can only carry so much." },
    ],
  },
  "58": {
    lead: "Your mission is to design a lander that protects its scientific payload during touchdown.",
    body: "Choose landing gear, predict the impact, then test it with a real accelerometer inside the lander.",
    reqs: [
      { title: "Protect the payload", body: "The sensor package must survive the landing." },
      { title: "Minimize landing shock", body: "Lower peak acceleration (g) means a gentler landing." },
      { title: "Stay within the mass budget", body: "Every gram costs fuel on the way to Mars." },
    ],
  },
  "912": {
    lead: "Your mission is to design a lander that protects its scientific payload during touchdown.",
    body: "Trade off energy absorption, rebound and mass. A 3-axis accelerometer (±16 g) measures the landing; you analyze peak specific force, pulse width and data quality.",
    reqs: [
      { title: "Protect the payload", body: "Keep the instrument mounted and intact through impact." },
      { title: "Minimize landing shock", body: "Minimize peak specific force measured at the payload." },
      { title: "Stay within the mass budget", body: "Landing-gear mass trades directly against payload mass." },
    ],
  },
} as const;

export const TRAIT_LABELS: Record<string, string> = {
  cushioning: "Cushioning",
  rebound: "Bounce",
  lightness: "Lightness",
  reusability: "Reusable",
};
