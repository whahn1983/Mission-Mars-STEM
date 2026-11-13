import type { GradeBand } from "../api/types";

export const GRADE_BANDS: { id: GradeBand; label: string; title: string; icon: string }[] = [
  { id: "k4", label: "Grades 1–4", title: "Cadet", icon: "🚀" },
  { id: "58", label: "Grades 5–8", title: "Engineer", icon: "🛠️" },
  { id: "912", label: "Grades 9–12", title: "Flight Director", icon: "📡" },
];

/**
 * Scale used to turn a test-stand drop into the matching drop for a real
 * lander. NASA's Phoenix lander stood about 2.2 m (7.2 ft) tall to the top of
 * its weather mast (Phoenix landing press kit). The station's test lander is
 * 4–6 in (10–15 cm) tall, so it is roughly a 1:20 model: a 10 cm drop on the
 * stand matches a 2 m drop for the real lander. That is the cut-off height
 * ESA's Schiaparelli lander was designed for (hover at about 2 m, thrusters
 * off, free fall onto a crushable structure).
 *
 * This scales length only. The impact speed on the stand is still √(2gh) for
 * the real centimetre drop.
 */
export const MODEL_SCALE = 20;
export const REFERENCE_LANDER = { name: "NASA's Phoenix lander", height: "2.2 m (7 ft)" };

/** Real-lander drop height for a test-stand drop, e.g. 0.1 m → "2 m". */
export const fmtScaledHeight = (modelHeightM: number) => {
  const real = Math.round(modelHeightM * MODEL_SCALE * 10) / 10;
  return `${Number.isInteger(real) ? real : real.toFixed(1)} m`;
};

const NUMBER_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"];
export const numberWord = (n: number) => NUMBER_WORDS[n] ?? String(n);

export const BRIEFING = {
  k4: {
    lead: "Help our lander touch down softly on Mars!",
    body: "Inside the lander is a special science sensor. Your job is to build legs that keep it safe.",
    story:
      "Rocket engines blow up lots of dust, and they can even dig a hole in the ground! So our lander hovers, turns its engine off a little above the ground, and drops the rest of the way. Its legs have to catch it gently.",
    scale: `Our test lander is a tiny model, about 20 times smaller than ${REFERENCE_LANDER.name}. On the real lander, our drops would be this high:`,
    reqs: [
      { title: "Keep it safe", body: "Protect the science sensor inside." },
      { title: "Land softly", body: "A gentle bump is better than a big crash." },
      { title: "Not too heavy", body: "Rockets can only carry so much." },
    ],
  },
  "58": {
    lead: "Your mission is to design a lander that protects its scientific payload during touchdown.",
    body: "Choose landing gear, predict the impact, then test it with a real accelerometer inside the lander.",
    story:
      "Firing a rocket engine close to the ground blasts Martian dust everywhere. The dust can coat solar panels and instruments, and the exhaust can dig a crater under the lander. So the plan is to hover, cut off the main engine early, and free-fall the last few metres. The landing legs have to absorb that impact.",
    scale: `Our 4–6 inch test lander is about a 1:20 scale model of ${REFERENCE_LANDER.name} (${REFERENCE_LANDER.height} tall). Scaled up, each test drop matches a real cut-off height:`,
    reqs: [
      { title: "Protect the payload", body: "The sensor package must survive the landing." },
      { title: "Minimize landing shock", body: "Lower peak acceleration (g) means a gentler landing." },
      { title: "Stay within the mass budget", body: "Every gram costs fuel on the way to Mars." },
    ],
  },
  "912": {
    lead: "Your mission is to design a lander that protects its scientific payload during touchdown.",
    body: "Trade off energy absorption, rebound and mass. A 3-axis accelerometer measures the landing; you analyze peak specific force, pulse width and data quality.",
    story:
      "Engine exhaust near the surface blasts regolith into a dust cloud that coats solar arrays and instruments, and can dig a crater under the lander (plume–surface interaction). So the descent ends with a hover, an early main-engine cut-off and a short free fall that the landing gear absorbs. ESA's Schiaparelli was designed to cut its thrusters about 2 m up.",
    scale: `The 4–6 in test lander is a ~1:20 model of ${REFERENCE_LANDER.name}, ${REFERENCE_LANDER.height} tall. Scaled by length only, the drops match these cut-off heights:`,
    reqs: [
      { title: "Protect the payload", body: "Keep the instrument mounted and intact through impact." },
      { title: "Minimize landing shock", body: "Minimize peak specific force measured at the payload." },
      { title: "Stay within the mass budget", body: "Landing-gear mass trades directly against payload mass." },
    ],
  },
} as const;

/** Steps of the briefing's descent animation, in order. */
export const DESCENT_STEPS = [
  { id: "descent", label: "Descent" },
  { id: "hover", label: "Hover" },
  { id: "cutoff", label: "Engine cut-off", young: "Engine off" },
  { id: "freefall", label: "Free fall" },
  { id: "touchdown", label: "Touchdown" },
] as const;

export const TRAIT_LABELS: Record<string, string> = {
  cushioning: "Cushioning",
  rebound: "Bounce",
  lightness: "Lightness",
  reusability: "Reusable",
};
