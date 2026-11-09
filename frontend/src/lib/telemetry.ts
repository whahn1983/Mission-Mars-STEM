/** Mutable ring buffer for live telemetry. Kept outside React state so the
 * canvas chart can redraw at display rate without re-rendering components. */

export interface TelemetryPoint {
  t: number; // sensor time in ms
  ax: number | null;
  ay: number | null;
  az: number | null;
  mag: number | null;
}

const CAPACITY = 4000;
const buf: TelemetryPoint[] = [];
let origin: string = "simulated";
let lastArrival = 0;

export const telemetry = {
  push(points: [number, number | null, number | null, number | null, number | null][], dataOrigin: string) {
    if (dataOrigin !== origin) {
      buf.length = 0;
      origin = dataOrigin;
    }
    for (const p of points) {
      const last = buf[buf.length - 1];
      // Sensor timestamps can jump (new capture, device restart): start over.
      if (last && (p[0] < last.t - 1 || p[0] - last.t > 10000)) buf.length = 0;
      buf.push({ t: p[0], ax: p[1], ay: p[2], az: p[3], mag: p[4] });
    }
    if (buf.length > CAPACITY) buf.splice(0, buf.length - CAPACITY);
    lastArrival = performance.now();
  },
  points: () => buf,
  origin: () => origin,
  msSinceLast: () => (lastArrival ? performance.now() - lastArrival : Infinity),
  latest: () => buf[buf.length - 1] ?? null,
  clear: () => {
    buf.length = 0;
  },
};
