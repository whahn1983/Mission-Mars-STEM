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

export function Lander({
  geometry,
  accent = "#22d3ee",
  xray = false,
  mode = "inspect",
}: {
  geometry?: Geometry;
  accent?: string;
  xray?: boolean;
  mode?: LanderMode;
}) {
  const g = geometry ?? DEFAULT_GEOMETRY;
  const root = useRef<THREE.Group>(null);
  const flame = useRef<THREE.Mesh>(null);
  const legs = useRef<THREE.Group>(null);
  const changedAt = useRef(0);
  const key = `${g.foot_shape}-${g.spring}-${g.foot_color}`;
  const lastKey = useRef(key);

  useFrame(({ clock }) => {
    const t = clock.elapsedTime;
    if (lastKey.current !== key) {
      lastKey.current = key;
      changedAt.current = t;
    }
    if (!root.current) return;
    if (mode === "descent") {
      const cycle = 7.0;
      const p = (t % cycle) / cycle;
      let y = 0;
      let thrust = 0;
      if (p < 0.62) {
        const q = p / 0.62;
        y = 5.5 * (1 - q) ** 2;
        thrust = 0.6 + 0.4 * (1 - q);
      } else if (p < 0.7) {
        const q = (p - 0.62) / 0.08;
        y = Math.max(0, Math.sin(q * Math.PI) * 0.12);
      }
      root.current.position.y = y;
      root.current.rotation.y = t * 0.15;
      if (flame.current) {
        flame.current.visible = thrust > 0;
        flame.current.scale.set(1, thrust * (0.85 + Math.random() * 0.3), 1);
      }
    } else {
      root.current.position.y = 0.04 + Math.sin(t * 1.2) * 0.02;
      if (flame.current) flame.current.visible = false;
    }
    if (legs.current) {
      const since = t - changedAt.current;
      const s = since < 0.6 ? 1 - 0.18 * Math.sin((since / 0.6) * Math.PI) : 1;
      legs.current.scale.set(1, s, 1);
    }
  });

  return (
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
    </group>
  );
}
