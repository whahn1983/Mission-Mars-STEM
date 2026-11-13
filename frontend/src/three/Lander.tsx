import { RoundedBox } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import type { Geometry } from "../api/types";

const DEFAULT_GEOMETRY: Geometry = {
  leg_style: "strut",
  foot_shape: "pad",
  foot_material: "hard",
  foot_color: "#cbd5e1",
  foot_size: 1,
  spring: false,
};

const LEG_ANGLES = [45, 135, 225, 315].map((d) => (d * Math.PI) / 180);
const ATTACH = { r: 0.74, y: 1.02 };
const FOOT = { r: 1.42, y: 0.16 };

function Strut({ from, to, radius = 0.045, color = "#94a3b8" }: { from: THREE.Vector3; to: THREE.Vector3; radius?: number; color?: string }) {
  const { position, quaternion, length } = useMemo(() => {
    const dir = new THREE.Vector3().subVectors(to, from);
    const len = dir.length();
    const q = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.clone().normalize());
    return { position: new THREE.Vector3().addVectors(from, to).multiplyScalar(0.5), quaternion: q, length: len };
  }, [from, to]);
  return (
    <mesh position={position} quaternion={quaternion} castShadow>
      <cylinderGeometry args={[radius, radius, length, 12]} />
      <meshStandardMaterial color={color} metalness={0.75} roughness={0.3} />
    </mesh>
  );
}

function Coil({ from, to, color = "#f97316", turns = 7, coilRadius = 0.085 }: { from: THREE.Vector3; to: THREE.Vector3; color?: string; turns?: number; coilRadius?: number }) {
  const geom = useMemo(() => {
    const axis = new THREE.Vector3().subVectors(to, from);
    const len = axis.length();
    const dir = axis.clone().normalize();
    const ref = Math.abs(dir.y) < 0.9 ? new THREE.Vector3(0, 1, 0) : new THREE.Vector3(1, 0, 0);
    const u = new THREE.Vector3().crossVectors(dir, ref).normalize();
    const v = new THREE.Vector3().crossVectors(dir, u).normalize();
    const pts: THREE.Vector3[] = [];
    const steps = turns * 24;
    for (let i = 0; i <= steps; i++) {
      const t = i / steps;
      const a = t * turns * Math.PI * 2;
      pts.push(
        from
          .clone()
          .add(dir.clone().multiplyScalar(t * len))
          .add(u.clone().multiplyScalar(Math.cos(a) * coilRadius))
          .add(v.clone().multiplyScalar(Math.sin(a) * coilRadius)),
      );
    }
    return new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), steps, 0.016, 8, false);
  }, [from, to, turns, coilRadius]);
  return (
    <mesh geometry={geom} castShadow>
      <meshStandardMaterial color={color} roughness={0.6} metalness={0.05} emissive={color} emissiveIntensity={0.15} />
    </mesh>
  );
}

function Foot({ g, position }: { g: Geometry; position: THREE.Vector3 }) {
  const s = g.foot_size || 1;
  if (g.foot_shape === "block") {
    return (
      <RoundedBox args={[0.3 * s, 0.24 * s, 0.3 * s]} radius={0.05} smoothness={4} position={[position.x, position.y - 0.02 * s, position.z]} castShadow>
        <meshStandardMaterial color={g.foot_color} roughness={0.95} metalness={0} />
      </RoundedBox>
    );
  }
  if (g.foot_shape === "dome") {
    return (
      <group position={[position.x, position.y - 0.12, position.z]}>
        <mesh castShadow rotation={[Math.PI, 0, 0]}>
          <sphereGeometry args={[0.15 * s, 24, 16, 0, Math.PI * 2, 0, Math.PI / 2]} />
          <meshStandardMaterial color={g.foot_color} roughness={0.75} metalness={0.05} side={THREE.DoubleSide} />
        </mesh>
        <mesh position={[0, 0.005, 0]} castShadow>
          <cylinderGeometry args={[0.15 * s, 0.15 * s, 0.03, 24]} />
          <meshStandardMaterial color="#111827" roughness={0.8} />
        </mesh>
      </group>
    );
  }
  return (
    <mesh position={[position.x, position.y - 0.08, position.z]} castShadow>
      <cylinderGeometry args={[0.15 * s, 0.17 * s, 0.05, 24]} />
      <meshStandardMaterial color={g.foot_color} metalness={0.6} roughness={0.35} />
    </mesh>
  );
}

function Leg({ angle, g }: { angle: number; g: Geometry }) {
  const pts = useMemo(() => {
    const c = Math.cos(angle);
    const s = Math.sin(angle);
    const attach = new THREE.Vector3(ATTACH.r * c, ATTACH.y, ATTACH.r * s);
    const foot = new THREE.Vector3(FOOT.r * c, FOOT.y, FOOT.r * s);
    const braceFrom = new THREE.Vector3(0.45 * c, 0.78, 0.45 * s);
    const mid = attach.clone().lerp(foot, 0.62);
    const coilFrom = attach.clone().lerp(foot, 0.12);
    const coilTo = attach.clone().lerp(foot, 0.55);
    return { attach, foot, braceFrom, mid, coilFrom, coilTo };
  }, [angle]);
  return (
    <group>
      <Strut from={pts.attach} to={pts.foot} radius={0.045} color="#cbd5e1" />
      <Strut from={pts.braceFrom} to={pts.mid} radius={0.028} color="#94a3b8" />
      {g.spring && <Coil from={pts.coilFrom} to={pts.coilTo} />}
      <Foot g={g} position={pts.foot} />
    </group>
  );
}

export function Payload({ highlight }: { highlight: boolean }) {
  const led = useRef<THREE.MeshStandardMaterial>(null);
  useFrame(({ clock }) => {
    if (led.current) led.current.emissiveIntensity = 1.5 + Math.sin(clock.elapsedTime * 5) * 1.2;
  });
  // EVB Lite is 41 × 37 × 19 mm; drawn ~3× scale so students can find it.
  return (
    <group position={[0, 1.27, 0]}>
      <mesh castShadow>
        <boxGeometry args={[0.41, 0.19, 0.37]} />
        <meshStandardMaterial color="#0f172a" metalness={0.3} roughness={0.4} emissive="#22d3ee" emissiveIntensity={highlight ? 0.35 : 0.08} />
      </mesh>
      <mesh position={[0, 0.0951, 0]}>
        <boxGeometry args={[0.33, 0.002, 0.29]} />
        <meshStandardMaterial color="#22d3ee" emissive="#22d3ee" emissiveIntensity={highlight ? 0.9 : 0.25} />
      </mesh>
      <mesh position={[0.15, 0.1, 0.13]}>
        <sphereGeometry args={[0.022, 12, 12]} />
        <meshStandardMaterial ref={led} color="#22c55e" emissive="#22c55e" emissiveIntensity={2} />
      </mesh>
      {/* mounting rails */}
      {[-0.24, 0.24].map((x) => (
        <mesh key={x} position={[x, -0.1, 0]}>
          <boxGeometry args={[0.05, 0.04, 0.6]} />
          <meshStandardMaterial color="#64748b" metalness={0.8} roughness={0.3} />
        </mesh>
      ))}
      {highlight && <pointLight color="#22d3ee" intensity={1.5} distance={1.6} />}
    </group>
  );
}

function Body({ xray, accent }: { xray: boolean; accent: string }) {
  const shell = { transparent: xray, opacity: xray ? 0.14 : 1, depthWrite: !xray };
  return (
    <group>
      {/* main octagonal deck */}
      <mesh position={[0, 1.22, 0]} castShadow receiveShadow>
        <cylinderGeometry args={[0.92, 0.82, 0.5, 8, 1]} />
        <meshStandardMaterial color="#e5e7eb" metalness={0.45} roughness={0.35} {...shell} />
      </mesh>
      {/* gold multi-layer insulation band */}
      <mesh position={[0, 1.06, 0]} castShadow>
        <cylinderGeometry args={[0.84, 0.7, 0.18, 8, 1]} />
        <meshStandardMaterial color="#d4a017" metalness={0.9} roughness={0.28} {...shell} />
      </mesh>
      {/* top deck plate */}
      <mesh position={[0, 1.48, 0]} castShadow>
        <cylinderGeometry args={[0.86, 0.92, 0.04, 8, 1]} />
        <meshStandardMaterial color="#cbd5e1" metalness={0.6} roughness={0.3} {...shell} />
      </mesh>
      {/* accent stripe in the configuration colour */}
      <mesh position={[0, 1.33, 0]}>
        <cylinderGeometry args={[0.925, 0.92, 0.05, 8, 1, true]} />
        <meshStandardMaterial color={accent} emissive={accent} emissiveIntensity={0.25} metalness={0.3} roughness={0.5} side={THREE.DoubleSide} {...shell} />
      </mesh>
      {/* antenna mast + dish */}
      <mesh position={[0.35, 1.75, -0.2]} castShadow>
        <cylinderGeometry args={[0.02, 0.02, 0.5, 8]} />
        <meshStandardMaterial color="#94a3b8" metalness={0.8} roughness={0.3} />
      </mesh>
      <mesh position={[0.35, 2.02, -0.2]} rotation={[-0.6, 0.4, 0]} castShadow>
        <sphereGeometry args={[0.22, 24, 12, 0, Math.PI * 2, 0, Math.PI / 3.2]} />
        <meshStandardMaterial color="#f8fafc" metalness={0.4} roughness={0.35} side={THREE.DoubleSide} />
      </mesh>
      {/* solar panels */}
      {[-1, 1].map((side) => (
        <group key={side} position={[side * 1.35, 1.5, 0]} rotation={[0, 0, side * -0.12]}>
          <mesh castShadow>
            <boxGeometry args={[0.85, 0.03, 0.55]} />
            <meshStandardMaterial color="#1e3a8a" metalness={0.6} roughness={0.25} emissive="#1d4ed8" emissiveIntensity={0.15} />
          </mesh>
          <mesh position={[-side * 0.5, 0, 0]}>
            <boxGeometry args={[0.18, 0.025, 0.06]} />
            <meshStandardMaterial color="#94a3b8" metalness={0.8} roughness={0.3} />
          </mesh>
        </group>
      ))}
      {/* thruster bells */}
      {[0, 1, 2].map((i) => {
        const a = (i / 3) * Math.PI * 2 + 0.5;
        return (
          <mesh key={i} position={[Math.cos(a) * 0.35, 0.88, Math.sin(a) * 0.35]} castShadow>
            <cylinderGeometry args={[0.06, 0.11, 0.14, 16, 1, true]} />
            <meshStandardMaterial color="#475569" metalness={0.85} roughness={0.25} side={THREE.DoubleSide} />
          </mesh>
        );
      })}
    </group>
  );
}

export type LanderMode = "inspect" | "descent";

// ---------------------------------------------------------------------------
// Descent animation (briefing screen)
//
// The scene lander is about 2.2 units tall, the height of NASA's Phoenix
// lander in metres, so 1 scene unit ≈ 1 m at real scale. The animation shows
// the landing plan from the briefing: powered descent, a hover with the
// exhaust kicking up dust, an early main-engine cut-off about 2 m up (the
// 10 cm test drop at 1:20 scale), a free fall in Mars gravity, and the legs
// absorbing the touchdown.
// ---------------------------------------------------------------------------

export type DescentPhase = "descent" | "hover" | "cutoff" | "freefall" | "touchdown";

/** Height of the Mars ground plane in the scene. */
export const GROUND_Y = -0.12;
/** Bottom of the thruster bells, relative to the lander origin. */
const NOZZLE_Y = 0.81;
const G_MARS = 3.71; // m/s², scene units ≈ metres

const DESCENT = {
  cycle: 9.2,
  startY: 6.5,
  poweredS: 3.3,
  hoverS: 1.7,
  /** Feet clearance at cut-off: about 2 m at real scale. */
  cutoffClearance: 2.0,
  /** How long the "cut-off" step stays lit before "free fall". */
  cutoffLabelS: 0.4,
  spinRate: 0.15,
};

/** Lowest point of the feet, relative to the lander origin. */
function footBottom(g: Geometry) {
  const s = g.foot_size || 1;
  if (g.foot_shape === "block") return FOOT.y - 0.02 * s - 0.12 * s;
  if (g.foot_shape === "dome") return FOOT.y - 0.12 - 0.15 * s;
  return FOOT.y - 0.08 - 0.025;
}

type DescentState = {
  phase: DescentPhase;
  y: number;
  /** 0…1 engine thrust (0 = off). */
  thrust: number;
  /** Leg compression in scene units (negative = rebound). */
  squash: number;
  spin: number;
};

function descentAt(t: number, g: Geometry): DescentState {
  const D = DESCENT;
  const landY = GROUND_Y - footBottom(g);
  const hoverY = landY + D.cutoffClearance;
  const fallS = Math.sqrt((2 * D.cutoffClearance) / G_MARS);
  const tCut = D.poweredS + D.hoverS;
  const tLand = tCut + fallS;
  const tau = t % D.cycle;
  const spin = t * D.spinRate;

  if (tau < D.poweredS) {
    // Decelerating powered descent, coming to rest at the hover height.
    const q = tau / D.poweredS;
    return { phase: "descent", y: hoverY + (D.startY - hoverY) * (1 - q) ** 2, thrust: 1, squash: 0, spin };
  }
  if (tau < tCut) {
    const h = tau - D.poweredS;
    return { phase: "hover", y: hoverY + Math.sin(h * 5.5) * 0.025, thrust: 0.85, squash: 0, spin };
  }
  if (tau < tLand) {
    // Engine off: free fall from the hover height.
    const f = tau - tCut;
    return {
      phase: f < D.cutoffLabelS ? "cutoff" : "freefall",
      y: hoverY - 0.5 * G_MARS * f * f,
      thrust: f < 0.12 ? 0.85 * (1 - f / 0.12) : 0,
      squash: 0,
      spin,
    };
  }
  // Touchdown: a damped spring that starts at the impact speed, so the legs
  // compress, spring back a little and settle.
  const s = tau - tLand;
  const omega = 2 * Math.PI * 2.4;
  const impactSpeed = G_MARS * fallS;
  const squash = (impactSpeed / omega) * Math.exp(-5 * s) * Math.sin(omega * s);
  return { phase: "touchdown", y: landY - squash, thrust: 0, squash, spin };
}

/** Soft round sprite texture for dust. */
function useDustTexture() {
  return useMemo(() => {
    const c = document.createElement("canvas");
    c.width = c.height = 64;
    const ctx = c.getContext("2d")!;
    const grd = ctx.createRadialGradient(32, 32, 0, 32, 32, 32);
    grd.addColorStop(0, "rgba(255,255,255,1)");
    grd.addColorStop(0.45, "rgba(255,255,255,0.55)");
    grd.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = grd;
    ctx.fillRect(0, 0, 64, 64);
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    return t;
  }, []);
}

type Particle = {
  alive: boolean;
  age: number;
  life: number;
  pos: THREE.Vector3;
  vel: THREE.Vector3;
  size0: number;
  size1: number;
  alpha: number;
};

const DUST_POOL = 150;
/** Nozzle clearance (scene units) below which the exhaust starts lifting dust. */
const DUST_RANGE = 5.5;
const DUST_RATE = 70; // particles per second at full strength

/**
 * Dust kicked up by the engine exhaust, plus a small puff at each foot on
 * touchdown. Lives in world space (it stays on the ground while the lander
 * moves) and follows the same timeline as the lander.
 */
function DescentDust({ g }: { g: Geometry }) {
  const tex = useDustTexture();
  const sprites = useRef<(THREE.Sprite | null)[]>([]);
  const pool = useRef<Particle[]>(
    Array.from({ length: DUST_POOL }, () => ({
      alive: false,
      age: 0,
      life: 1,
      pos: new THREE.Vector3(),
      vel: new THREE.Vector3(),
      size0: 0.2,
      size1: 1,
      alpha: 0.4,
    })),
  );
  const carry = useRef(0);
  const lastPhase = useRef<DescentPhase | null>(null);

  const spawn = (pos: THREE.Vector3, vel: THREE.Vector3, life: number, size0: number, size1: number, alpha: number) => {
    const p = pool.current.find((x) => !x.alive);
    if (!p) return;
    p.alive = true;
    p.age = 0;
    p.life = life;
    p.pos.copy(pos);
    p.vel.copy(vel);
    p.size0 = size0;
    p.size1 = size1;
    p.alpha = alpha;
  };

  useFrame(({ clock }, delta) => {
    const dt = Math.min(delta, 0.05);
    const st = descentAt(clock.elapsedTime, g);

    // Exhaust dust: more of it the closer the nozzles are to the ground.
    const clearance = st.y + NOZZLE_Y - GROUND_Y;
    const strength = st.thrust * Math.sqrt(Math.max(0, 1 - clearance / DUST_RANGE));
    carry.current += strength * DUST_RATE * dt;
    while (carry.current >= 1) {
      carry.current -= 1;
      const a = Math.random() * Math.PI * 2;
      const r = Math.random() * 0.35;
      const speed = 1.1 + Math.random() * 1.9;
      spawn(
        new THREE.Vector3(Math.cos(a) * r, GROUND_Y + 0.08, Math.sin(a) * r),
        new THREE.Vector3(Math.cos(a) * speed, 0.25 + Math.random() * 0.75, Math.sin(a) * speed),
        1.4 + Math.random() * 1.2,
        0.25 + Math.random() * 0.15,
        1.1 + Math.random() * 0.9,
        0.45 + Math.random() * 0.25,
      );
    }

    // Touchdown puff at each foot.
    if (st.phase === "touchdown" && lastPhase.current === "freefall") {
      for (const base of LEG_ANGLES) {
        // The lander spins about +y, which turns local angle θ to θ − spin.
        const a = base - st.spin;
        const fx = Math.cos(a) * FOOT.r;
        const fz = Math.sin(a) * FOOT.r;
        for (let i = 0; i < 6; i++) {
          const d = a + (Math.random() - 0.5) * 2.2;
          const sp = 0.35 + Math.random() * 0.6;
          spawn(
            new THREE.Vector3(fx, GROUND_Y + 0.04, fz),
            new THREE.Vector3(Math.cos(d) * sp, 0.12 + Math.random() * 0.25, Math.sin(d) * sp),
            0.9 + Math.random() * 0.6,
            0.12,
            0.5 + Math.random() * 0.3,
            0.55,
          );
        }
      }
    }
    lastPhase.current = st.phase;

    pool.current.forEach((p, i) => {
      const sprite = sprites.current[i];
      if (!sprite) return;
      if (p.alive) {
        p.age += dt;
        if (p.age >= p.life) p.alive = false;
      }
      if (!p.alive) {
        sprite.visible = false;
        return;
      }
      const drag = Math.exp(-1.6 * dt);
      p.vel.x *= drag;
      p.vel.z *= drag;
      p.vel.y = p.vel.y * drag - 0.12 * dt;
      p.pos.addScaledVector(p.vel, dt);
      if (p.pos.y < GROUND_Y + 0.03) p.pos.y = GROUND_Y + 0.03;
      const k = p.age / p.life;
      const size = p.size0 + (p.size1 - p.size0) * Math.sqrt(k);
      sprite.visible = true;
      sprite.position.copy(p.pos);
      sprite.scale.set(size, size, size);
      (sprite.material as THREE.SpriteMaterial).opacity = p.alpha * Math.min(1, k / 0.12) * (1 - k) ** 1.5;
    });
  });

  return (
    <group>
      {Array.from({ length: DUST_POOL }, (_, i) => (
        <sprite
          key={i}
          ref={(s) => {
            sprites.current[i] = s;
          }}
          visible={false}
        >
          <spriteMaterial map={tex} color="#e2b48c" transparent opacity={0} depthWrite={false} />
        </sprite>
      ))}
    </group>
  );
}

export function Lander({
  geometry,
  accent = "#22d3ee",
  xray = false,
  mode = "inspect",
  onPhase,
}: {
  geometry?: Geometry;
  accent?: string;
  xray?: boolean;
  mode?: LanderMode;
  /** Descent mode: called when the animation moves to a new step. */
  onPhase?: (phase: DescentPhase) => void;
}) {
  const g = geometry ?? DEFAULT_GEOMETRY;
  const root = useRef<THREE.Group>(null);
  const flame = useRef<THREE.Mesh>(null);
  const plume = useRef<THREE.Mesh>(null);
  const legs = useRef<THREE.Group>(null);
  const changedAt = useRef(0);
  const key = `${g.foot_shape}-${g.spring}-${g.foot_color}`;
  const lastKey = useRef(key);
  const lastPhase = useRef<DescentPhase | null>(null);

  useFrame(({ clock }) => {
    const t = clock.elapsedTime;
    if (lastKey.current !== key) {
      lastKey.current = key;
      changedAt.current = t;
    }
    if (!root.current) return;
    if (mode === "descent") {
      const st = descentAt(t, g);
      root.current.position.y = st.y;
      root.current.rotation.y = st.spin;
      if (flame.current) {
        flame.current.visible = st.thrust > 0;
        flame.current.scale.set(1, st.thrust * (0.85 + Math.random() * 0.3), 1);
      }
      if (plume.current) {
        // Faint exhaust column from the nozzles down to the ground.
        // It only shows once the nozzles are low enough to reach the ground.
        const len = st.y + NOZZLE_Y - GROUND_Y;
        const strength = st.thrust * Math.min(1, Math.max(0, (4.2 - len) / 1.4));
        plume.current.visible = strength > 0.01;
        plume.current.position.y = NOZZLE_Y - len / 2;
        plume.current.scale.set(1, len, 1);
        (plume.current.material as THREE.MeshBasicMaterial).opacity = 0.12 * strength * (0.85 + Math.random() * 0.3);
      }
      if (legs.current) {
        // Compress the legs while the feet stay planted: the leg tops move
        // with the body and the feet move up by the squash (in body space).
        const fb = footBottom(g);
        const sy = 1 - st.squash / (ATTACH.y - fb);
        legs.current.scale.set(1, sy, 1);
        legs.current.position.y = ATTACH.y * (1 - sy);
      }
      if (st.phase !== lastPhase.current) {
        lastPhase.current = st.phase;
        onPhase?.(st.phase);
      }
      return;
    }
    root.current.position.y = 0.04 + Math.sin(t * 1.2) * 0.02;
    if (flame.current) flame.current.visible = false;
    if (plume.current) plume.current.visible = false;
    if (legs.current) {
      const since = t - changedAt.current;
      const s = since < 0.6 ? 1 - 0.18 * Math.sin((since / 0.6) * Math.PI) : 1;
      legs.current.scale.set(1, s, 1);
      legs.current.position.y = 0;
    }
  });

  return (
    <>
      <group ref={root}>
        <Body xray={xray} accent={accent} />
        <Payload highlight={xray} />
        <group ref={legs}>
          {LEG_ANGLES.map((a) => (
            <Leg key={a} angle={a} g={g} />
          ))}
        </group>
        <mesh ref={flame} position={[0, 0.55, 0]} rotation={[Math.PI, 0, 0]} visible={false}>
          <coneGeometry args={[0.22, 0.75, 20, 1, true]} />
          <meshBasicMaterial color="#fb923c" transparent opacity={0.75} />
        </mesh>
        <mesh ref={plume} visible={false}>
          <cylinderGeometry args={[0.16, 0.55, 1, 24, 1, true]} />
          <meshBasicMaterial color="#fdba74" transparent opacity={0} depthWrite={false} blending={THREE.AdditiveBlending} side={THREE.DoubleSide} />
        </mesh>
      </group>
      {mode === "descent" && <DescentDust g={g} />}
    </>
  );
}
