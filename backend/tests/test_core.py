import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import samples
from app.core import MeshError, prepare_chart, solve_lscm


class TestLSCM(unittest.TestCase):
    def assert_close(self, actual, expected, tol=1e-8):
        self.assertTrue(abs(actual - expected) <= tol, f"{actual} != {expected} (tol {tol})")

    def test_plane_is_disk_and_exact_conformal(self):
        mesh = samples.plane_grid(3)
        prep = prepare_chart(mesh)
        self.assertTrue(prep["is_topological_disk"])
        self.assertEqual(prep["boundary_loop_count"], 1)
        self.assertEqual(prep["euler_characteristic"], 1)
        self.assertEqual(prep["chart_vertex_count"], 16)

        boundary = prep["boundary_vertices"]
        result = solve_lscm(mesh, [
            {"vertex": boundary[0], "uv": [0, 0]},
            {"vertex": boundary[1], "uv": [1, 0]},
        ])
        self.assertTrue(result["ok"], result.get("warnings"))
        self.assertEqual(result["summary"]["rank"], result["summary"]["expected_rank"])
        self.assert_close(result["summary"]["residual_norm"], 0.0, 1e-8)
        self.assertEqual(result["summary"]["flipped_face_ids"], [])
        self.assert_close(result["summary"]["max_angle_error_deg"], 0.0, 1e-7)

    def test_seam_split_identities_are_not_coordinate_deduped(self):
        mesh = samples.cube_tree_cut()
        prep = prepare_chart(mesh)
        self.assertTrue(prep["is_topological_disk"])
        self.assertGreater(prep["chart_vertex_count"], 8)
        by_original = {}
        for v in prep["chart_vertices"]:
            by_original.setdefault(v["original_vertex"], []).append(v["id"])
        duplicated = {k: v for k, v in by_original.items() if len(v) > 1}
        self.assertTrue(duplicated, "tree-cut endpoints must split into sectors")
        for ids in duplicated.values():
            self.assertEqual(len(ids), len(set(ids)))

    def test_closed_tetrahedron_is_rejected_with_witness(self):
        mesh = samples.closed_tetrahedron()
        prep = prepare_chart(mesh)
        self.assertFalse(prep["is_topological_disk"])
        self.assertEqual(prep["boundary_loop_count"], 0)
        self.assertEqual(prep["witness"]["kind"], "closed_surface")
        result = solve_lscm(mesh, [{"vertex": 0, "uv": [0, 0]}, {"vertex": 1, "uv": [1, 0]}])
        self.assertEqual(result["status"], "invalid_topology")

    def test_disconnecting_disk_cut_returns_component_and_boundary_witness(self):
        mesh = samples.bad_plane_cut()
        prep = prepare_chart(mesh)
        self.assertFalse(prep["is_topological_disk"])
        self.assertEqual(len(prep["cut_components"]), 2)
        self.assertEqual(prep["boundary_loop_count"], 2)
        self.assertEqual(prep["witness"]["kind"], "disconnected_after_cut")

    def test_anchors_must_be_distinct_split_boundary_vertices_at_required_positions(self):
        mesh = samples.plane_grid(1)
        prep = prepare_chart(mesh)
        with self.assertRaisesRegex(MeshError, "exactly two"):
            solve_lscm(mesh, [{"vertex": 0, "uv": [0, 0]}])
        with self.assertRaisesRegex(MeshError, "different split"):
            solve_lscm(mesh, [{"vertex": 0, "uv": [0, 0]}, {"vertex": 0, "uv": [1, 0]}])
        interior = set(range(prep["chart_vertex_count"])) - set(prep["boundary_vertices"])
        if interior:
            v = next(iter(interior))
            with self.assertRaisesRegex(MeshError, "not on the cut boundary"):
                solve_lscm(mesh, [{"vertex": 0, "uv": [0, 0]}, {"vertex": v, "uv": [1, 0]}])
        with self.assertRaisesRegex(MeshError, r"\(0,0\)"):
            solve_lscm(mesh, [{"vertex": 0, "uv": [0.2, 0]}, {"vertex": 1, "uv": [1, 0]}])

    def test_inconsistent_orientation_is_rejected(self):
        mesh = samples.plane_grid(1)
        mesh["faces"][0] = list(reversed(mesh["faces"][0]))
        with self.assertRaisesRegex(MeshError, "orientation"):
            prepare_chart(mesh)

    def test_unknown_seam_edge_and_triangle_limit_reported(self):
        mesh = samples.plane_grid(1)
        mesh["seam_edges"] = [[1, 2]]
        with self.assertRaisesRegex(MeshError, "not incident"):
            prepare_chart(mesh)
        with self.assertRaisesRegex(MeshError, "at most"):
            prepare_chart(samples.plane_grid(12))

    def test_export_contains_every_face_corner_uv_and_original_face_id(self):
        mesh = samples.plane_grid(2)
        boundary = prepare_chart(mesh)["boundary_vertices"]
        result = solve_lscm(mesh, [
            {"vertex": boundary[0], "uv": [0, 0]},
            {"vertex": boundary[1], "uv": [1, 0]},
        ])
        corners = result["face_corner_uv"]
        self.assertEqual(len(corners), 3 * len(mesh["faces"]))
        for face_id in range(len(mesh["faces"])):
            face_corners = [c for c in corners if c["face_id"] == face_id]
            self.assertEqual(len(face_corners), 3)
            for c in face_corners:
                self.assertEqual(len(c["uv"]), 2)
                self.assertTrue(all(math.isfinite(v) for v in c["uv"]))


if __name__ == "__main__":
    unittest.main()
