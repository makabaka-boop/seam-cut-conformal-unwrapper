"""Small hand-authored example meshes used by the UI and tests."""
from __future__ import annotations


def plane_grid(segments: int = 4) -> dict:
    positions = []
    for row in range(segments + 1):
        for col in range(segments + 1):
            x = 2.0 * col / segments - 1.0
            y = 2.0 * row / segments - 1.0
            positions.append([x, y, 0.0])

    faces = []
    stride = segments + 1
    for row in range(segments):
        for col in range(segments):
            a = row * stride + col
            b = a + 1
            d = a + stride
            c = d + 1
            faces.append([a, b, c])
            faces.append([a, c, d])
    return {
        "name": f"plane_{segments}x{segments}",
        "positions": positions,
        "faces": faces,
        "seam_edges": [],
        "description": "Already a topological disk with no cut edges; useful for numerical checks.",
    }


def cube_tree_cut() -> dict:
    positions = [
        [-1, -1, -1],
        [1, -1, -1],
        [1, 1, -1],
        [-1, 1, -1],
        [-1, -1, 1],
        [1, -1, 1],
        [1, 1, 1],
        [-1, 1, 1],
    ]
    faces = [
        [0, 3, 2], [0, 2, 1],  # z = -1
        [4, 5, 6], [4, 6, 7],  # z = +1
        [0, 4, 7], [0, 7, 3],  # x = -1
        [1, 2, 6], [1, 6, 5],  # x = +1
        [0, 1, 5], [0, 5, 4],  # y = -1
        [3, 7, 6], [3, 6, 2],  # y = +1
    ]
    # A spanning tree of cube edges opens a closed cube to one topological disk.
    seam_edges = [[0, 1], [1, 2], [2, 3], [1, 5], [5, 4], [5, 6], [6, 7]]
    return {
        "name": "cube_tree_cut",
        "positions": positions,
        "faces": faces,
        "seam_edges": seam_edges,
        "description": "Cube cut along a spanning tree. Cut vertices appear as separate boundary sectors.",
    }


def closed_tetrahedron() -> dict:
    return {
        "name": "closed_tetrahedron",
        "positions": [
            [0, 0, 1],
            [1, 0, 0],
            [0, 1, 0],
            [-1, -1, 0],
        ],
        "faces": [[0, 1, 2], [0, 3, 1], [0, 2, 3], [1, 3, 2]],
        "seam_edges": [],
        "description": "Closed surface with no boundary: topology must be rejected before solving.",
    }


def disconnected_cut_plane() -> dict:
    # Two triangles share one interior edge. Cutting it disconnects the dual graph.
    return {
        "name": "disconnected_cut_plane",
        "positions": [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
        "faces": [[0, 1, 2], [0, 2, 3]],
        "seam_edges": [[0, 2]],
        "description": "An illegal cut through a disk: the two faces become disconnected and there are two boundary loops.",
    }


bad_plane_cut = disconnected_cut_plane

SAMPLES = {
    "plane": plane_grid,
    "cube": cube_tree_cut,
    "closed_tetra": closed_tetrahedron,
    "bad_plane_cut": disconnected_cut_plane,
}

