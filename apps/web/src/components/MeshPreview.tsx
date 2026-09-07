"use client";

import { useEffect, useRef } from "react";
import * as THREE from "three";

/**
 * Renders the uploaded mesh so the customer can confirm they sent the right file at the right
 * scale. This single check catches the most common ordering mistake there is — a model drawn
 * in inches and exported as millimetres.
 */
export function MeshPreview({ file, className }: { file: File | null; className?: string }) {
  const mount = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = mount.current;
    if (!container || !file) return;

    let disposed = false;
    let frame = 0;
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 10000);

    const resize = () => {
      const { clientWidth: w, clientHeight: h } = container;
      if (w === 0 || h === 0) return;
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      // updateStyle must stay on: without it the canvas keeps its intrinsic size and spills
      // out of the container, over the rest of the page.
      renderer.setSize(w, h, true);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };

    // Belt and braces against the same overflow, whatever the renderer does with styles.
    renderer.domElement.style.display = "block";
    renderer.domElement.style.width = "100%";
    renderer.domElement.style.height = "100%";
    container.appendChild(renderer.domElement);
    resize();
    scene.add(new THREE.HemisphereLight(0xffffff, 0x556070, 2.2));
    const key = new THREE.DirectionalLight(0xffffff, 1.4);
    key.position.set(1, 1.4, 1);
    scene.add(key);

    let group: THREE.Group | null = null;

    (async () => {
      // STLLoader lives in three's examples bundle; load it lazily so it stays out of the
      // initial page weight.
      const { STLLoader } = await import("three/examples/jsm/loaders/STLLoader.js");
      const buffer = await file.arrayBuffer();
      if (disposed) return;

      let geometry: THREE.BufferGeometry;
      try {
        geometry = new STLLoader().parse(buffer);
      } catch {
        return; // Non-STL formats simply don't preview; the server still analyses them.
      }
      geometry.computeVertexNormals();
      geometry.center();

      const mesh = new THREE.Mesh(
        geometry,
        new THREE.MeshStandardMaterial({ color: 0xb4530a, roughness: 0.65, metalness: 0.05 }),
      );
      group = new THREE.Group();
      group.add(mesh);
      scene.add(group);

      geometry.computeBoundingSphere();
      const radius = geometry.boundingSphere?.radius ?? 50;
      camera.position.set(radius * 1.8, radius * 1.4, radius * 2.1);
      camera.lookAt(0, 0, 0);
      resize();
    })();

    const animate = () => {
      if (group) group.rotation.z += 0.005;
      renderer.render(scene, camera);
      frame = requestAnimationFrame(animate);
    };
    animate();

    const observer = new ResizeObserver(resize);
    observer.observe(container);

    return () => {
      disposed = true;
      cancelAnimationFrame(frame);
      observer.disconnect();
      renderer.dispose();
      scene.traverse((object) => {
        if (object instanceof THREE.Mesh) {
          object.geometry.dispose();
          (object.material as THREE.Material).dispose();
        }
      });
      container.removeChild(renderer.domElement);
    };
  }, [file]);

  if (!file) return null;
  return (
    <div
      ref={mount}
      className={`overflow-hidden ${className ?? "h-64 w-full rounded-md bg-rule/30"}`}
    />
  );
}
