"""Topological cutting and area-weighted LSCM implementation.

The implementation intentionally uses no mesh-processing, UV-unwrapping or
numerical third-party library.  It splits face *sectors* after cutting, checks
the resulting topology, assembles the LSCM rows per triangle, then solves the
dense least-squares system with a small Cholesky implementation.
"""
from __future__ import annotations

import math
from typing import Any

MAX_TRIANGLES = 200
_EPS = 1.0e-12


class MeshError(ValueError):
    """Raised for an invalid input mesh or seam specification."""


class _DSU:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))
        self.weight = [1] * n

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.weight[ra] < self.weight[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        self.weight[ra] += self.weight[rb]


def _sub(a: list[float], b: list[float]) -> list[float]:
    return [a[i] - b[i] for i in range(len(a))]


def _add(a: list[float], b: list[float]) -> list[float]:
    return [a[i] + b[i] for i in range(len(a))]


def _dot(a: list[float], b: list[float]) -> float:
    return sum(a[i] * b[i] for i in range(len(a)))


def _scale(a: list[float], s: float) -> list[float]:
    return [x * s for x in a]


def _cross3(a: list[float], b: list[float]) -> list[float]:
    return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]


def _norm(a: list[float]) -> float:
    return math.sqrt(_dot(a, a))


def _as_float_vector(value: Any, name: str, length: int) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != length:
        raise MeshError(f"{name} must be a list of {length} numbers")
    try:
        result = [float(v) for v in value]
    except (TypeError, ValueError) as exc:
        raise MeshError(f"{name} must contain numbers") from exc
    if not all(math.isfinite(v) for v in result):
        raise MeshError(f"{name} contains a non-finite number")
    return result


def _triangle_area(positions: list[list[float]], tri: list[int]) -> float:
    return _norm(_cross3(_sub(positions[tri[1]], positions[tri[0]]),
                         _sub(positions[tri[2]], positions[tri[0]]))) * 0.5


def _angle(a: list[float], b: list[float], c: list[float]) -> float | None:
    v1, v2 = _sub(a, b), _sub(c, b)
    n1, n2 = _norm(v1), _norm(v2)
    if n1 <= 1.0e-14 or n2 <= 1.0e-14:
        return None
    cosine = _dot(v1, v2) / (n1 * n2)
    return math.acos(max(-1.0, min(1.0, cosine)))


def validate_and_build(mesh: dict[str, Any]):
    """Validate raw mesh data and build basic half-edge incidence."""
    if not isinstance(mesh, dict):
        raise MeshError("mesh must be an object")

    raw_positions = mesh.get("positions")
    raw_faces = mesh.get("faces")
    if not isinstance(raw_positions, list) or not raw_positions:
        raise MeshError("positions must be a non-empty list")
    if not isinstance(raw_faces, list) or not raw_faces:
        raise MeshError("faces must be a non-empty list")
    if len(raw_faces) > MAX_TRIANGLES:
        raise MeshError(f"this tool accepts at most {MAX_TRIANGLES} triangles")

    positions = [
        _as_float_vector(p, f"positions[{i}]", 3)
        for i, p in enumerate(raw_positions)
    ]

    faces: list[list[int]] = []
    seen_triangles: set[tuple[int, int, int]] = set()
    for fi, face in enumerate(raw_faces):
        if not isinstance(face, (list, tuple)) or len(face) != 3:
            raise MeshError(f"faces[{fi}] must contain three vertex indices")
        try:
            tri = [int(v) for v in face]
        except (TypeError, ValueError) as exc:
            raise MeshError(f"faces[{fi}] contains a non-integer index") from exc
        if len(set(tri)) != 3:
            raise MeshError(f"faces[{fi}] is degenerate: repeated vertex index")
        if any(v < 0 or v >= len(positions) for v in tri):
            raise MeshError(f"faces[{fi}] refers to a missing vertex")
        key = tuple(sorted(tri))
        if key in seen_triangles:
            raise MeshError(f"faces[{fi}] duplicates another triangle")
        seen_triangles.add(key)

        e01 = _sub(positions[tri[1]], positions[tri[0]])
        e02 = _sub(positions[tri[2]], positions[tri[0]])
        cross_norm = _norm(_cross3(e01, e02))
        edge_scale = _norm(e01) * _norm(e02)
        if edge_scale > 0.0 and cross_norm <= 1.0e-14 * edge_scale:
            raise MeshError(f"faces[{fi}] is geometrically degenerate")
        faces.append(tri)

    raw_edges = mesh.get("seam_edges") or []
    if not isinstance(raw_edges, list):
        raise MeshError("seam_edges must be a list of vertex-index pairs")
    seam_edges: list[tuple[int, int]] = []
    seen_edges: set[tuple[int, int]] = set()
    for ei, edge in enumerate(raw_edges):
        if not isinstance(edge, (list, tuple)) or len(edge) != 2:
            raise MeshError(f"seam_edges[{ei}] must contain two vertex indices")
        try:
            a, b = int(edge[0]), int(edge[1])
        except (TypeError, ValueError) as exc:
            raise MeshError(f"seam_edges[{ei}] contains a non-integer index") from exc
        if a == b:
            raise MeshError(f"seam_edges[{ei}] is a self-loop")
        if not (0 <= a < len(positions) and 0 <= b < len(positions)):
            raise MeshError(f"seam_edges[{ei}] refers to a missing vertex")
        key = (min(a, b), max(a, b))
        if key not in seen_edges:
            seen_edges.add(key)
            seam_edges.append(key)

    undirected: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for fi, tri in enumerate(faces):
        for j in range(3):
            a, b = tri[j], tri[(j + 1) % 3]
            undirected.setdefault((min(a, b), max(a, b)), []).append((fi, j))

    seam_set = set(seam_edges)
    unknown_edges = seam_set - set(undirected)
    if unknown_edges:
        a, b = sorted(unknown_edges)[0]
        raise MeshError(f"seam edge ({a}, {b}) is not incident to any triangle")

    face_dsu = _DSU(len(faces))
    for (a, b), occurrences in undirected.items():
        if len(occurrences) > 2:
            raise MeshError(f"edge ({a}, {b}) has {len(occurrences)} incident triangles; non-manifold")
        if len(occurrences) == 2:
            (f1, j1), (f2, j2) = occurrences
            tri1, tri2 = faces[f1], faces[f2]
            edge1 = (tri1[j1], tri1[(j1 + 1) % 3])
            edge2 = (tri2[j2], tri2[(j2 + 1) % 3])
            if edge1 == edge2:
                raise MeshError(f"faces {f1} and {f2} disagree in orientation around edge ({a}, {b})")
            if edge2 != (edge1[1], edge1[0]):
                raise MeshError(f"edge ({a}, {b}) is non-manifold or face orientation is inconsistent")
            # The supplied surface itself must be connected even if a later
            # cut disconnects it; prepare_chart builds a separate post-cut DSU.
            face_dsu.union(f1, f2)

    components: dict[int, list[int]] = {}
    for fi in range(len(faces)):
        components.setdefault(face_dsu.find(fi), []).append(fi)
    if len(components) > 1:
        comps = sorted((sorted(v) for v in components.values()), key=lambda x: x[0])
        raise MeshError("input face adjacency is disconnected; witness face components: " + repr(comps))

    return positions, faces, seam_edges, undirected, {}


def prepare_chart(mesh: dict[str, Any]) -> dict[str, Any]:
    """Split face corners across seams and test whether the result is a disk."""
    positions, faces, seam_edges, undirected, _directed = validate_and_build(mesh)
    seam_set = set(seam_edges)
    corner_count = 3 * len(faces)
    corner_dsu = _DSU(corner_count)
    face_dsu = _DSU(len(faces))
    twin: dict[tuple[int, int], tuple[int, int]] = {}
    uncut_interior_edges = 0
    original_boundary_edges = 0

    # Only uncut interior edges identify opposite corners.  A cut edge keeps
    # its two sectors apart, even when their 3D positions are identical.
    for (a, b), occurrences in undirected.items():
        if len(occurrences) == 1:
            original_boundary_edges += 1
            continue
        (f1, j1), (f2, j2) = occurrences
        if (a, b) in seam_set:
            continue
        uncut_interior_edges += 1
        face_dsu.union(f1, f2)
        tri1, tri2 = faces[f1], faces[f2]
        corner_dsu.union(3 * f1 + j1, 3 * f2 + ((j2 + 1) % 3))
        corner_dsu.union(3 * f1 + ((j1 + 1) % 3), 3 * f2 + j2)
        twin[(tri1[j1], tri1[(j1 + 1) % 3])] = (f2, j2)
        twin[(tri2[j2], tri2[(j2 + 1) % 3])] = (f1, j1)

    root_to_id: dict[int, int] = {}
    corner_chart = [0] * corner_count
    for c in range(corner_count):
        root = corner_dsu.find(c)
        if root not in root_to_id:
            root_to_id[root] = len(root_to_id)
        corner_chart[c] = root_to_id[root]
    chart_count = len(root_to_id)

    chart_corners: list[list[int]] = [[] for _ in range(chart_count)]
    for c, chart_id in enumerate(corner_chart):
        chart_corners[chart_id].append(c)

    cut_components_raw: dict[int, list[int]] = {}
    for fi in range(len(faces)):
        cut_components_raw.setdefault(face_dsu.find(fi), []).append(fi)
    component_witness = sorted((sorted(v) for v in cut_components_raw.values()), key=lambda x: x[0])

    boundary_halfedges: list[tuple[int, int]] = []
    for fi, tri in enumerate(faces):
        for j in range(3):
            if (tri[j], tri[(j + 1) % 3]) not in twin:
                boundary_halfedges.append((fi, j))

    def next_boundary_halfedge(h: tuple[int, int]) -> tuple[int, int]:
        f, j = h
        while True:
            nj = (j + 1) % 3
            tri = faces[f]
            key = (tri[nj], tri[(nj + 1) % 3])
            if key not in twin:
                return f, nj
            f, j = twin[key]

    loops: list[dict[str, Any]] = []
    seen_boundary: set[tuple[int, int]] = set()
    for start in boundary_halfedges:
        if start in seen_boundary:
            continue
        vertex_loop: list[int] = []
        corner_loop: list[int] = []
        original_vertex_loop: list[int] = []
        current = start
        while current not in seen_boundary:
            seen_boundary.add(current)
            f, j = current
            corner = 3 * f + j
            vertex_loop.append(corner_chart[corner])
            corner_loop.append(corner)
            original_vertex_loop.append(faces[f][j])
            current = next_boundary_halfedge(current)
        loops.append({
            "chart_vertices": vertex_loop,
            "corner_ids": corner_loop,
            "original_vertices": original_vertex_loop,
            "length": len(vertex_loop),
        })

    edge_count = 3 * len(faces) - uncut_interior_edges
    euler = chart_count - edge_count + len(faces)
    is_disk = len(component_witness) == 1 and len(loops) == 1 and euler == 1

    boundary_chart_ids = sorted({corner_chart[3 * f + j] for f, j in boundary_halfedges})
    boundary_set = set(boundary_chart_ids)
    chart_vertices = []
    for chart_id, corners in enumerate(chart_corners):
        original = faces[corners[0] // 3][corners[0] % 3]
        chart_vertices.append({
            "id": chart_id,
            "original_vertex": original,
            "position": positions[original],
            "corner_ids": corners,
            "face_ids": sorted({c // 3 for c in corners}),
            "boundary": chart_id in boundary_set,
        })

    face_corners = []
    for fi, tri in enumerate(faces):
        face_corners.append([{
            "corner_id": 3 * fi + j,
            "chart_vertex": corner_chart[3 * fi + j],
            "original_vertex": tri[j],
        } for j in range(3)])

    return {
        "valid_for_solve": is_disk,
        "triangle_count": len(faces),
        "original_vertex_count": len(positions),
        "chart_vertex_count": chart_count,
        "edge_count": edge_count,
        "boundary_edge_count": len(boundary_halfedges),
        "euler_characteristic": euler,
        "genus_if_connected": (2 - len(loops) - euler) // 2 if len(component_witness) == 1 else None,
        "is_topological_disk": is_disk,
        "seam_edges": [list(e) for e in seam_edges],
        "seam_interior_edges": [list(e) for e in seam_edges if len(undirected[e]) == 2],
        "original_boundary_edge_count": original_boundary_edges,
        "chart_vertices": chart_vertices,
        "boundary_vertices": boundary_chart_ids,
        "face_corners": face_corners,
        "boundary_loops": loops,
        "boundary_loop_count": len(loops),
        "cut_components": component_witness,
        "witness": _disk_witness(is_disk, loops, component_witness, euler),
    }


def _disk_witness(is_disk, loops, components, euler):
    if is_disk:
        return None
    if len(components) > 1:
        return {
            "kind": "disconnected_after_cut",
            "message": "The seam separates the surface into multiple face components.",
            "face_components": components,
        }
    if len(loops) == 0:
        return {
            "kind": "closed_surface",
            "message": "No boundary was created; the surface is still closed.",
            "euler_characteristic": euler,
        }
    return {
        "kind": "not_disk_boundary",
        "message": f"Expected one boundary loop and Euler characteristic 1; found {len(loops)} loops and chi={euler}.",
        "boundary_loops": [loop["original_vertices"] for loop in loops],
        "chart_boundary_loops": [loop["chart_vertices"] for loop in loops],
        "euler_characteristic": euler,
    }


def _cholesky_solve_spd(a: list[list[float]], b: list[float]) -> tuple[list[float], bool, float, int]:
    """Solve symmetric positive-definite A x = b.

    Returns the solution, strict SPD status, smallest pivot, and pivot rank.
    """
    n = len(a)
    l = [[0.0] * n for _ in range(n)]
    scale = max((abs(a[i][i]) for i in range(n)), default=1.0)
    tolerance = 1.0e-12 * max(scale, 1.0)
    spd = True
    min_pivot = math.inf
    pivot_rank = 0
    for i in range(n):
        for j in range(i + 1):
            total = a[i][j] - sum(l[i][k] * l[j][k] for k in range(j))
            if i == j:
                if total <= tolerance:
                    spd = False
                    total = max(total, tolerance)
                else:
                    pivot_rank += 1
                min_pivot = min(min_pivot, total)
                l[i][j] = math.sqrt(total)
            else:
                l[i][j] = total / l[j][j]

    y = [0.0] * n
    for i in range(n):
        y[i] = (b[i] - sum(l[i][j] * y[j] for j in range(i))) / l[i][i]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = (y[i] - sum(l[j][i] * x[j] for j in range(i + 1, n))) / l[i][i]
    return x, spd, min_pivot if n else math.inf, pivot_rank


def solve_lscm(mesh: dict[str, Any], anchors) -> dict[str, Any]:
    """Pin two boundary chart vertices and solve area-weighted LSCM."""
    prep = prepare_chart(mesh)
    if not prep["valid_for_solve"]:
        return {
            "ok": False,
            "status": "invalid_topology",
            "message": "The cut surface is not one topological disk; no LSCM solve was attempted.",
            "preparation": prep,
        }

    anchor_map: dict[int, list[float]] = {}
    raw_anchor_vertices: list[int] = []
    if isinstance(anchors, dict):
        for key, uv in anchors.items():
            vid = int(key)
            anchor_map[vid] = _as_float_vector(uv, f"anchor {key}", 2)
            raw_anchor_vertices.append(vid)
    elif isinstance(anchors, list):
        for item in anchors:
            if not isinstance(item, dict):
                raise MeshError("anchor entries must be objects")
            vid = int(item["vertex"])
            anchor_map[vid] = _as_float_vector(item.get("uv"), f"anchor {vid}", 2)
            raw_anchor_vertices.append(vid)
    else:
        raise MeshError("anchors must be an object or list")

    boundary_set = set(prep["boundary_vertices"])
    n_charts = prep["chart_vertex_count"]
    if len(raw_anchor_vertices) == 2 and len(set(raw_anchor_vertices)) != 2:
        raise MeshError("the two anchors must be different split vertices")
    if len(anchor_map) != 2:
        raise MeshError("exactly two split boundary vertices must be anchored")
    for vid, uv in anchor_map.items():
        if not 0 <= vid < n_charts:
            raise MeshError(f"anchor chart vertex {vid} does not exist")
        if vid not in boundary_set:
            raise MeshError(f"anchor chart vertex {vid} is not on the cut boundary")
    required = {(0.0, 0.0), (1.0, 0.0)}
    actual = {(round(uv[0], 12), round(uv[1], 12)) for uv in anchor_map.values()}
    if actual != required:
        raise MeshError("anchors must be fixed at exactly (0,0) and (1,0)")

    positions, faces, _seam_edges, _undirected, _directed = validate_and_build(mesh)
    corner_chart = [c["chart_vertex"] for row in prep["face_corners"] for c in row]
    n = n_charts
    total_scalars = 2 * n

    pinned: dict[int, float] = {}
    for vid, uv in anchor_map.items():
        pinned[2 * vid] = uv[0]
        pinned[2 * vid + 1] = uv[1]
    free_columns = [i for i in range(total_scalars) if i not in pinned]
    free_count = len(free_columns)

    # Two rows per triangle: sqrt(A)*(u_x-v_y), sqrt(A)*(u_y+v_x).
    free_rows: list[list[float]] = []
    rhs: list[float] = []
    full_rows: list[list[float]] = []

    for fi, tri in enumerate(faces):
        p = [positions[tri[j]] for j in range(3)]
        normal = _cross3(_sub(p[1], p[0]), _sub(p[2], p[0]))
        normal_norm = _norm(normal)
        n3 = _scale(normal, 1.0 / normal_norm)
        reference = [0.0, 1.0, 0.0] if abs(n3[2]) > 0.8 else [0.0, 0.0, 1.0]
        e1 = _cross3(reference, n3)
        e1 = _scale(e1, 1.0 / _norm(e1))
        e2 = _cross3(n3, e1)  # n = e1 x e2, preserving orientation.

        x = [_dot(q, e1) for q in p]
        y = [_dot(q, e2) for q in p]
        signed_area = 0.5 * ((x[1] - x[0]) * (y[2] - y[0]) - (y[1] - y[0]) * (x[2] - x[0]))
        if signed_area <= 0.0:
            raise MeshError(f"face {fi} produced a non-positive local frame")
        s = 1.0 / (2.0 * math.sqrt(signed_area))
        c1 = (y[1] - y[2], y[2] - y[0], y[0] - y[1])
        c2 = (x[2] - x[1], x[0] - x[2], x[1] - x[0])
        chart_ids = [corner_chart[3 * fi + j] for j in range(3)]

        for sign in (1.0, -1.0):
            # Rows are u_x-v_y and u_y+v_x; shared c1/c2 coefficients appear
            # as a small 90-degree rotation between u and v blocks.
            row = [0.0] * total_scalars
            if sign == 1.0:
                for k, cid in enumerate(chart_ids):
                    row[2 * cid] = s * c1[k]
                    row[2 * cid + 1] = -s * c2[k]
            else:
                for k, cid in enumerate(chart_ids):
                    row[2 * cid] = s * c2[k]
                    row[2 * cid + 1] = s * c1[k]
            full_rows.append(row)
            free_rows.append([row[col] for col in free_columns])
            pin_contribution = sum(row[col] * value for col, value in pinned.items())
            rhs.append(-pin_contribution)

    # Normal equations B^T B x = B^T d.  Dense Cholesky is sufficient at 200
    # triangles and keeps the project dependency-free.
    normal = [[0.0] * free_count for _ in range(free_count)]
    normal_rhs = [0.0] * free_count
    for row, d in zip(free_rows, rhs):
        for i, vi in enumerate(row):
            if vi == 0.0:
                continue
            normal_rhs[i] += vi * d
            row_i = normal[i]
            for j in range(i, free_count):
                row_i[j] += vi * row[j]
    for i in range(free_count):
        for j in range(i):
            normal[i][j] = normal[j][i]

    free_solution, spd, min_pivot, rank = _cholesky_solve_spd(normal, normal_rhs)
    uv_flat = [0.0] * total_scalars
    for col, value in pinned.items():
        uv_flat[col] = value
    for col, value in zip(free_columns, free_solution):
        uv_flat[col] = value

    residual_vector = [sum(row[j] * uv_flat[j] for j in range(total_scalars)) for row in full_rows]
    residual_norm = math.sqrt(sum(r * r for r in residual_vector))

    # Pivot rank from Cholesky. A pinned disk chart has rank 2V-4.
    expected_rank = total_scalars - 4
    rank_deficient = rank < expected_rank or not spd

    uv = [[uv_flat[2 * i], uv_flat[2 * i + 1]] for i in range(n)]
    flipped_faces: list[int] = []
    degenerate_uv_faces: list[int] = []
    face_metrics = []
    corner_results = []
    angle_errors: list[float] = []

    for fi, tri in enumerate(faces):
        ids = [corner_chart[3 * fi + j] for j in range(3)]
        uv3 = [uv[cid] for cid in ids]
        signed_uv_area = 0.5 * (
            (uv3[1][0] - uv3[0][0]) * (uv3[2][1] - uv3[0][1])
            - (uv3[1][1] - uv3[0][1]) * (uv3[2][0] - uv3[0][0])
        )
        if signed_uv_area < -1.0e-12:
            flipped_faces.append(fi)
        if abs(signed_uv_area) <= 1.0e-12:
            degenerate_uv_faces.append(fi)
        area3 = _triangle_area(positions, tri)
        face_max = 0.0
        for j in range(3):
            k, l = (j + 1) % 3, (j + 2) % 3
            angle3 = _angle(positions[tri[k]], positions[tri[j]], positions[tri[l]])
            angle2 = _angle(uv3[k], uv3[j], uv3[l])
            if angle3 is None or angle2 is None:
                err = None
                angle3_out = None if angle3 is None else math.degrees(angle3)
                angle2_out = None if angle2 is None else math.degrees(angle2)
            else:
                err = abs(math.degrees(angle3 - angle2))
                angle3_out = math.degrees(angle3)
                angle2_out = math.degrees(angle2)
                angle_errors.append(err)
                face_max = max(face_max, err)
            corner_results.append({
                "face_id": fi,
                "corner": j,
                "original_vertex": tri[j],
                "chart_vertex": ids[j],
                "uv": uv3[j],
                "angle_3d_deg": angle3_out,
                "angle_uv_deg": angle2_out,
                "angle_error_deg": err,
            })
        r1, r2 = residual_vector[2 * fi], residual_vector[2 * fi + 1]
        face_metrics.append({
            "face_id": fi,
            "conformal_residual": math.hypot(r1, r2),
            "area_3d": area3,
            "signed_uv_area": signed_uv_area,
            "area_ratio": signed_uv_area / area3 if area3 else None,
            "flipped": fi in flipped_faces,
            "degenerate_uv": fi in degenerate_uv_faces,
            "max_angle_error_deg": face_max,
        })

    status = "ok"
    warnings: list[str] = []
    if rank_deficient:
        status = "rank_deficient"
        warnings.append("LSCM free system rank is below 2V-4; the pinned UVs are not uniquely determined.")
    if flipped_faces or degenerate_uv_faces:
        status = "flipped_or_degenerate" if status == "ok" else status + "_with_inversion"
        warnings.append("The solution contains flipped or degenerate UV triangles and must not be packaged as a usable chart.")

    return {
        "ok": not rank_deficient and not flipped_faces and not degenerate_uv_faces,
        "status": status,
        "warnings": warnings,
        "preparation": prep,
        "anchors": [{"vertex": vid, "uv": uvv} for vid, uvv in anchor_map.items()],
        "uv_vertices": [{"id": i, "uv": uv[i]} for i in range(n)],
        "face_corner_uv": corner_results,
        "faces": face_metrics,
        "summary": {
            "chart_vertex_count": n,
            "matrix_shape": [len(full_rows), total_scalars],
            "rank": rank,
            "expected_rank": expected_rank,
            "rank_deficient": rank_deficient,
            "cholesky_min_pivot": min_pivot,
            "residual_norm": residual_norm,
            "residual_rms": residual_norm / math.sqrt(len(residual_vector)),
            "max_conformal_residual": max(m["conformal_residual"] for m in face_metrics),
            "max_angle_error_deg": max(angle_errors) if angle_errors else None,
            "flipped_face_ids": flipped_faces,
            "degenerate_uv_face_ids": degenerate_uv_faces,
        },
    }
