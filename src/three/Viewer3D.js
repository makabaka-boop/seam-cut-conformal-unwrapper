import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

export class Viewer3D {
  constructor(container, onPick) {
    this.container = container;
    this.onPick = onPick;
    this.faceMesh = null;
    this.selectionMesh = null;
    this.checkerTexture = null;
    this.seamMeshes = [];
    this.anchorMeshes = [];
    this.mode = "face";

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x101418);

    const rect = container.getBoundingClientRect();
    this.camera = new THREE.PerspectiveCamera(45, rect.width / Math.max(1, rect.height), 0.01, 100);
    this.camera.position.set(3.2, 2.7, 4.2);

    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setSize(rect.width, rect.height);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    container.appendChild(this.renderer.domElement);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;

    this.scene.add(new THREE.HemisphereLight(0xddeeff, 0x202020, 1.6));
    const key = new THREE.DirectionalLight(0xffffff, 1.8);
    key.position.set(3, 5, 4);
    this.scene.add(key);

    this.group = new THREE.Group();
    this.seamGroup = new THREE.Group();
    this.anchorGroup = new THREE.Group();
    this.scene.add(this.group, this.seamGroup, this.anchorGroup);

    this.raycaster = new THREE.Raycaster();
    this.pointer = new THREE.Vector2();
    this.renderer.domElement.addEventListener("pointerdown", this.handlePointerDown);
    this.renderer.domElement.addEventListener("pointermove", this.handlePointerMove);
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(container);
    this.animate();
  }

  setMode(mode) {
    this.mode = mode;
    this.updateCursor(undefined);
  }

  setMesh(mesh, fit = true) {
    this.disposeGroup(this.group);
    this.disposeGroup(this.seamGroup);
    this.seamMeshes = [];

    const positions = [];
    for (const face of mesh.faces) {
      for (const vid of face) positions.push(...mesh.positions[vid]);
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
    geometry.computeVertexNormals();
    geometry.computeBoundingSphere();

    const material = new THREE.MeshStandardMaterial({
      color: 0xb8c7d6,
      roughness: 0.72,
      metalness: 0.02,
      side: THREE.DoubleSide,
      vertexColors: false,
    });
    this.faceMesh = new THREE.Mesh(geometry, material);
    this.faceMesh.userData.faceIds = mesh.faces.map((_, i) => i);
    this.group.add(this.faceMesh);

    const edges = new THREE.LineSegments(
      new THREE.EdgesGeometry(geometry, 20),
      new THREE.LineBasicMaterial({ color: 0x1a1f26, transparent: true, opacity: 0.85 })
    );
    this.group.add(edges);
    this.setSeamEdges(mesh.seam_edges || [], mesh.positions);
    if (fit) {
      this.controls.target.copy(geometry.boundingSphere.center);
      this.fitCamera(geometry.boundingSphere);
    }
  }

  setSeamEdges(seamEdges, positions) {
    this.disposeGroup(this.seamGroup);
    this.seamMeshes = [];
    for (const [a, b] of seamEdges) {
      const pa = new THREE.Vector3(...positions[a]);
      const pb = new THREE.Vector3(...positions[b]);
      const direction = new THREE.Vector3().subVectors(pb, pa);
      const length = direction.length();
      const visibleGeometry = new THREE.CylinderGeometry(0.018, 0.018, length, 10, 1, true);
      const hitGeometry = new THREE.CylinderGeometry(0.06, 0.06, length, 8, 1, true);
      const material = new THREE.MeshBasicMaterial({
        color: 0xff4a4a,
        transparent: true,
        opacity: 0.95,
        depthTest: true,
      });
      const hitMaterial = new THREE.MeshBasicMaterial({
        color: 0xff4a4a,
        transparent: true,
        opacity: 0.0,
        depthWrite: false,
      });
      const cylinder = new THREE.Mesh(visibleGeometry, material);
      const hitCylinder = new THREE.Mesh(hitGeometry, hitMaterial);
      hitCylinder.userData.edge = [a, b];
      hitCylinder.userData.kind = "seam";
      cylinder.add(hitCylinder);
      cylinder.position.copy(pa).add(pb).multiplyScalar(0.5);
      cylinder.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction.normalize());
      this.seamGroup.add(cylinder);
      this.seamMeshes.push(hitCylinder);
    }
  }

  setPreparation(preparation) {
    this.disposeGroup(this.anchorGroup);
    this.anchorMeshes = [];
    for (const vertex of preparation.chart_vertices) {
      if (!vertex.boundary) continue;
      const geometry = new THREE.SphereGeometry(0.045, 16, 10);
      const material = new THREE.MeshBasicMaterial({ color: 0x58d5ff });
      const sphere = new THREE.Mesh(geometry, material);
      sphere.position.set(...vertex.position);
      sphere.userData.kind = "anchor";
      sphere.userData.chartVertex = vertex.id;
      sphere.userData.originalVertex = vertex.original_vertex;
      this.anchorGroup.add(sphere);
      this.anchorMeshes.push(sphere);
    }
    this.anchorGroup.visible = false;
  }

  setAnchorPickMode(enabled) {
    this.anchorGroup.visible = enabled;
    this.setMode(enabled ? "anchor" : "face");
  }

  setAnchors(anchors, preparation) {
    const map = new Map(anchors.map((a) => [a.vertex, a.uv]));
    for (const sphere of this.anchorMeshes) {
      const id = sphere.userData.chartVertex;
      if (!map.has(id)) {
        sphere.material.color.set(0x58d5ff);
        sphere.scale.setScalar(1);
      } else {
        const uv = map.get(id);
        sphere.material.color.set(uv[0] === 0 && uv[1] === 0 ? 0x3dff7e : 0xffd34a);
        sphere.scale.setScalar(1.45);
      }
    }
    void preparation;
  }

  setSolution(result, mesh) {
    if (!result?.face_corner_uv) return;
    this.checkerTexture = createCheckerTexture();
    const uvByCorner = new Map(
      result.face_corner_uv.map((corner) => [corner.face_id * 3 + corner.corner, corner.uv])
    );
    const positions = [];
    const uvs = [];
    for (const corners of result.preparation.face_corners) {
      for (const corner of corners) {
        const original = corner.original_vertex;
        positions.push(...mesh.positions[original]);
        const uv = uvByCorner.get(corner.corner_id);
        uvs.push(uv[0], uv[1]);
      }
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
    geometry.setAttribute("uv", new THREE.Float32BufferAttribute(uvs, 2));
    geometry.computeVertexNormals();
    geometry.computeBoundingSphere();
    const material = new THREE.MeshStandardMaterial({
      map: this.checkerTexture,
      roughness: 0.75,
      side: THREE.DoubleSide,
    });
    this.disposeGroup(this.group);
    this.faceMesh = new THREE.Mesh(geometry, material);
    this.group.add(this.faceMesh);
    this.group.add(new THREE.LineSegments(
      new THREE.EdgesGeometry(geometry, 20),
      new THREE.LineBasicMaterial({ color: 0x07090b, transparent: true, opacity: 0.75 })
    ));
    this.setSelectedFace(this.selectedFace);
  }

  setSelectedFace(faceId) {
    this.selectedFace = faceId;
    if (this.selectionMesh) {
      this.group.remove(this.selectionMesh);
      this.selectionMesh.geometry.dispose();
      this.selectionMesh.material.dispose();
      this.selectionMesh = null;
    }
    if (faceId == null || !this.faceMesh) return;
    const geometry = this.faceMesh.geometry;
    const start = faceId * 3;
    const pa = new THREE.Vector3().fromBufferAttribute(geometry.attributes.position, start);
    const pb = new THREE.Vector3().fromBufferAttribute(geometry.attributes.position, start + 1);
    const pc = new THREE.Vector3().fromBufferAttribute(geometry.attributes.position, start + 2);
    const highlight = new THREE.BufferGeometry();
    highlight.setAttribute(
      "position",
      new THREE.Float32BufferAttribute([...pa.toArray(), ...pb.toArray(), ...pc.toArray()], 3)
    );
    this.selectionMesh = new THREE.Mesh(
      highlight,
      new THREE.MeshBasicMaterial({ color: 0xffea00, transparent: true, opacity: 0.42, side: THREE.DoubleSide })
    );
    this.group.add(this.selectionMesh);
  }

  handlePointerDown = (event) => {
    const hit = this.pick(event);
    if (!hit) return;
    const object = hit.object;
    if (event.shiftKey && object.userData.kind === "seam") {
      this.onPick?.({ type: "seam", edge: object.userData.edge });
      event.stopPropagation();
      return;
    }
    if (this.mode === "anchor" && object.userData.kind === "anchor") {
      this.onPick?.({ type: "anchor", chartVertex: object.userData.chartVertex, originalVertex: object.userData.originalVertex });
      event.stopPropagation();
      return;
    }
    if (object === this.faceMesh) {
      const faceId = Math.floor(hit.faceIndex);
      this.onPick?.({ type: "face", faceId });
    }
  };

  handlePointerMove = (event) => {
    const hit = this.pick(event);
    if (!hit) {
      this.updateCursor("default");
      return;
    }
    if (this.mode === "anchor" && hit.object.userData.kind === "anchor") this.updateCursor("crosshair");
    else if (event.shiftKey && hit.object.userData.kind === "seam") this.updateCursor("crosshair");
    else if (hit.object === this.faceMesh) this.updateCursor("pointer");
    else this.updateCursor("default");
  };

  pick(event) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    this.pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const objects = [this.faceMesh, ...this.seamMeshes, ...this.anchorMeshes].filter(Boolean);
    const hits = this.raycaster.intersectObjects(objects, true);
    return hits[0] || null;
  }

  updateCursor(cursor) {
    this.renderer.domElement.style.cursor = cursor || "default";
  }

  fitCamera(sphere) {
    const radius = sphere.radius || 1.5;
    const direction = new THREE.Vector3(1, 0.75, 1.15).normalize();
    this.controls.target.copy(sphere.center);
    this.camera.position.copy(sphere.center).add(direction.multiplyScalar(radius * 2.9));
    this.camera.near = Math.max(radius / 100, 0.001);
    this.camera.far = radius * 100;
    this.camera.updateProjectionMatrix();
  }

  disposeGroup(group) {
    group.traverse((object) => {
      if (object.geometry) object.geometry.dispose();
      if (object.material) {
        if (Array.isArray(object.material)) object.material.forEach((m) => m.dispose());
        else object.material.dispose();
      }
    });
    group.clear();
  }

  resize() {
    const rect = this.container.getBoundingClientRect();
    this.camera.aspect = rect.width / Math.max(1, rect.height);
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(rect.width, rect.height);
  }

  animate = () => {
    requestAnimationFrame(this.animate);
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  };
}

function createCheckerTexture() {
  const size = 256;
  const cells = 8;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d");
  const cell = size / cells;
  for (let y = 0; y < cells; y += 1) {
    for (let x = 0; x < cells; x += 1) {
      ctx.fillStyle = (x + y) % 2 ? "#f2f2e8" : "#20242b";
      ctx.fillRect(x * cell, y * cell, cell, cell);
    }
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.wrapS = texture.wrapT = THREE.ClampToEdgeWrapping;
  texture.magFilter = THREE.NearestFilter;
  texture.minFilter = THREE.NearestFilter;
  return texture;
}
