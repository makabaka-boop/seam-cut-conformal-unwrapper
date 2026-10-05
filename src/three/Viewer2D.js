import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

export class Viewer2D {
  constructor(container, onPickFace) {
    this.container = container;
    this.onPickFace = onPickFace;
    this.selectedFace = null;

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0xf6f7f9);
    const rect = container.getBoundingClientRect();
    const size = Math.max(rect.width, rect.height) || 1;
    this.camera = new THREE.OrthographicCamera(-1, 1, 1, -1, -10, 10);
    this.camera.position.set(0.5, 0.5, 5);

    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setSize(rect.width, rect.height);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    container.appendChild(this.renderer.domElement);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableRotate = false;
    this.controls.enableDamping = true;

    this.grid = new THREE.GridHelper(1, 10, 0x9aa4af, 0xd0d5db);
    this.grid.rotation.x = Math.PI / 2;
    this.grid.position.z = -0.05;
    this.scene.add(this.grid);

    this.group = new THREE.Group();
    this.highlightGroup = new THREE.Group();
    this.scene.add(this.group, this.highlightGroup);

    this.raycaster = new THREE.Raycaster();
    this.pointer = new THREE.Vector2();
    this.renderer.domElement.addEventListener("pointerdown", this.handlePointerDown);
    this.renderer.domElement.addEventListener("pointermove", this.handlePointerMove);
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(container);
    this.animate();
  }

  setResult(result) {
    this.disposeGroup(this.group);
    this.faceMeshes = [];
    if (!result?.face_corner_uv) return;

    const byFace = new Map();
    for (const corner of result.face_corner_uv) {
      if (!byFace.has(corner.face_id)) byFace.set(corner.face_id, []);
      byFace.get(corner.face_id).push(corner);
    }

    const texture = createCheckerTexture();
    for (const [faceId, corners] of [...byFace.entries()].sort((a, b) => a[0] - b[0])) {
      corners.sort((a, b) => a.corner - b.corner);
      const positions = [];
      const uvs = [];
      for (const c of corners) {
        positions.push(c.uv[0], c.uv[1], 0);
        uvs.push(c.uv[0], c.uv[1]);
      }
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
      geometry.setAttribute("uv", new THREE.Float32BufferAttribute(uvs, 2));
      const flipped = result.summary.flipped_face_ids.includes(faceId);
      const material = new THREE.MeshBasicMaterial({
        map: texture,
        color: flipped ? 0xff7777 : 0xffffff,
        side: THREE.DoubleSide,
      });
      const mesh = new THREE.Mesh(geometry, material);
      mesh.userData.faceId = faceId;
      this.group.add(mesh);
      this.faceMeshes.push(mesh);

      const edge = new THREE.LineLoop(
        new THREE.BufferGeometry().setAttribute("position", new THREE.Float32BufferAttribute(positions, 3)),
        new THREE.LineBasicMaterial({ color: flipped ? 0x9b0000 : 0x111820 })
      );
      edge.userData.faceId = faceId;
      this.group.add(edge);
    }

    this.addAnchors(result.anchors || []);
    this.fitToUVs(result.uv_vertices.map((v) => v.uv));
    this.setSelectedFace(this.selectedFace);
  }

  addAnchors(anchors) {
    for (const anchor of anchors) {
      const [x, y] = anchor.uv;
      const circle = new THREE.Mesh(
        new THREE.CircleGeometry(0.025, 28),
        new THREE.MeshBasicMaterial({ color: x === 0 && y === 0 ? 0x00a83d : 0xe08800, side: THREE.DoubleSide })
      );
      circle.position.set(x, y, 0.02);
      const ring = new THREE.LineLoop(
        new THREE.BufferGeometry().setAttribute(
          "position",
          new THREE.Float32BufferAttribute(circle.geometry.attributes.position.array, 3)
        ),
        new THREE.LineBasicMaterial({ color: 0x000000 })
      );
      ring.position.copy(circle.position);
      this.group.add(circle, ring);
    }
  }

  setSelectedFace(faceId) {
    this.selectedFace = faceId;
    this.disposeGroup(this.highlightGroup);
    if (faceId == null) return;
    const source = this.faceMeshes?.find((m) => m.userData.faceId === faceId);
    if (!source) return;
    const geometry = source.geometry.clone();
    const highlight = new THREE.Mesh(
      geometry,
      new THREE.MeshBasicMaterial({ color: 0xffea00, transparent: true, opacity: 0.38, side: THREE.DoubleSide })
    );
    highlight.position.z = 0.003;
    this.highlightGroup.add(highlight);
  }

  fitToUVs(uvs) {
    const xs = uvs.map((p) => p[0]);
    const ys = uvs.map((p) => p[1]);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    const width = Math.max(maxX - minX, 0.001);
    const height = Math.max(maxY - minY, 0.001);
    const pad = 0.18 * Math.max(width, height);
    this.bounds = {
      minX: minX - pad,
      maxX: maxX + pad,
      minY: minY - pad,
      maxY: maxY + pad,
    };
    this.resize();
    this.controls.target.set((minX + maxX) / 2, (minY + maxY) / 2, 0);
    this.camera.position.set((minX + maxX) / 2, (minY + maxY) / 2, 5);
  }

  handlePointerDown = (event) => {
    const hit = this.pick(event);
    if (hit) this.onPickFace?.(hit.object.userData.faceId);
  };

  handlePointerMove = (event) => {
    const hit = this.pick(event);
    this.renderer.domElement.style.cursor = hit ? "pointer" : "default";
  };

  pick(event) {
    if (!this.faceMeshes?.length) return null;
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    this.pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const hits = this.raycaster.intersectObjects(this.faceMeshes, false);
    return hits[0] || null;
  }

  resize() {
    const rect = this.container.getBoundingClientRect();
    const w = Math.max(1, rect.width);
    const h = Math.max(1, rect.height);
    this.renderer.setSize(w, h);
    const b = this.bounds || { minX: -0.2, maxX: 1.2, minY: -0.7, maxY: 0.7 };
    const bw = b.maxX - b.minX;
    const bh = b.maxY - b.minY;
    const aspect = w / h;
    let viewWidth = bw;
    let viewHeight = bh;
    if (viewWidth / viewHeight < aspect) viewWidth = viewHeight * aspect;
    else viewHeight = viewWidth / aspect;
    const cx = (b.minX + b.maxX) / 2;
    const cy = (b.minY + b.maxY) / 2;
    this.camera.left = cx - viewWidth / 2;
    this.camera.right = cx + viewWidth / 2;
    this.camera.top = cy + viewHeight / 2;
    this.camera.bottom = cy - viewHeight / 2;
    this.camera.updateProjectionMatrix();
  }

  disposeGroup(group) {
    group.traverse((object) => {
      if (object.geometry) object.geometry.dispose();
      if (object.material && object !== this.grid) object.material.dispose();
    });
    group.clear();
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
      ctx.fillStyle = (x + y) % 2 ? "#f4f4eb" : "#20242b";
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
