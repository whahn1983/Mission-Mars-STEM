import { ContactShadows, OrbitControls, Stars } from "@react-three/drei";
import { Canvas } from "@react-three/fiber";
import { Component, Suspense, useMemo, type ReactNode } from "react";
import * as THREE from "three";
import type { Geometry } from "../api/types";
import { Lander, type LanderMode } from "./Lander";

function MarsGround() {
  const rocks = useMemo(() => {
    // Deterministic pseudo-random rocks.
    let seed = 7;
    const rnd = () => {
      seed = (seed * 16807) % 2147483647;
      return (seed - 1) / 2147483646;
    };
    return Array.from({ length: 34 }, () => {
      const r = 2.2 + rnd() * 7;
      const a = rnd() * Math.PI * 2;
      return { pos: [Math.cos(a) * r, -0.1, Math.sin(a) * r] as [number, number, number], s: 0.06 + rnd() * 0.22, rot: rnd() * 3 };
    });
  }, []);
  const tex = useMemo(() => {
    const c = document.createElement("canvas");
    c.width = c.height = 256;
    const ctx = c.getContext("2d")!;
    const grd = ctx.createRadialGradient(128, 128, 10, 128, 128, 128);
    grd.addColorStop(0, "#b4532a");
    grd.addColorStop(0.7, "#7c2d12");
    grd.addColorStop(1, "#1c0a05");
    ctx.fillStyle = grd;
    ctx.fillRect(0, 0, 256, 256);
    let s = 3;
    for (let i = 0; i < 2500; i++) {
      s = (s * 16807) % 2147483647;
      const x = s % 256;
      s = (s * 16807) % 2147483647;
      const y = s % 256;
      ctx.fillStyle = `rgba(${s % 2 ? 60 : 210},${s % 2 ? 20 : 110},${s % 2 ? 8 : 60},0.18)`;
      ctx.fillRect(x, y, 2, 2);
    }
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    return t;
  }, []);
  return (
    <group>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.12, 0]} receiveShadow>
        <circleGeometry args={[12, 64]} />
        <meshStandardMaterial map={tex} roughness={1} metalness={0} />
      </mesh>
      {rocks.map((r, i) => (
        <mesh key={i} position={r.pos} rotation={[r.rot, r.rot * 2, 0]} scale={r.s} castShadow>
          <dodecahedronGeometry args={[1, 0]} />
          <meshStandardMaterial color="#5b2410" roughness={1} flatShading />
        </mesh>
      ))}
    </group>
  );
}

class GLBoundary extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

function Fallback() {
  return (
    <div className="flex h-full w-full items-center justify-center text-center text-slate-400">
      <div>
        <div className="text-6xl">🛰️</div>
        <div className="mt-2 text-sm">3D view unavailable on this display (WebGL disabled).</div>
      </div>
    </div>
  );
}

export function LanderScene({
  geometry,
  accent,
  xray = false,
  mode = "inspect",
  interactive = true,
  autoRotate = true,
  cameraDistance = 1,
}: {
  geometry?: Geometry;
  accent?: string;
  xray?: boolean;
  mode?: LanderMode;
  interactive?: boolean;
  autoRotate?: boolean;
  cameraDistance?: number;
}) {
  const d = cameraDistance;
  return (
    <GLBoundary fallback={<Fallback />}>
      <Canvas
        shadows
        dpr={[1, 2]}
        camera={{ position: [3.4 * d, 2.3 * d, 3.8 * d], fov: 40 }}
        gl={{ antialias: true, powerPreference: "high-performance" }}
        style={{ touchAction: "none" }}
      >
        <color attach="background" args={["#040916"]} />
        <fog attach="fog" args={["#040916", 9, 22]} />
        <hemisphereLight args={["#9ecbff", "#3b1406", 0.55]} />
        <directionalLight position={[5, 8, 4]} intensity={2.2} castShadow shadow-mapSize={[1024, 1024]} />
        <pointLight position={[-4, 2, -3]} intensity={18} color="#22d3ee" distance={12} />
        <pointLight position={[3, 1, -4]} intensity={10} color="#f97316" distance={10} />
        <Stars radius={60} depth={40} count={2500} factor={3} saturation={0} fade speed={0.6} />
        <Suspense fallback={null}>
          <Lander geometry={geometry} accent={accent} xray={xray} mode={mode} />
          <MarsGround />
          <ContactShadows position={[0, -0.11, 0]} opacity={0.6} scale={6} blur={2.4} far={3} />
        </Suspense>
        <OrbitControls
          enabled={interactive}
          enablePan={false}
          minDistance={2.6}
          maxDistance={9}
          minPolarAngle={0.25}
          maxPolarAngle={Math.PI / 2.05}
          target={[0, mode === "descent" ? 1.2 : 0.9, 0]}
          autoRotate={autoRotate}
          autoRotateSpeed={0.7}
        />
      </Canvas>
    </GLBoundary>
  );
}
