"""Flask backend: prepare (split + disk check) and solve (LSCM)."""

import numpy as np
from flask import Flask, jsonify, request, send_from_directory

from lscm import SolveError, solve_lscm
from mesh import MeshError, split_mesh
from samples import get_sample
from topology import boundary_loops, check_disk, tutte_preview


def create_app():
    app = Flask(__name__, static_folder=None)

    @app.get("/api/samples/<name>")
    def sample(name):
        try:
            verts, faces, seams = get_sample(name)
        except KeyError:
            return jsonify({"error": "unknown sample %r" % name}), 404
        return jsonify({"vertices": verts, "faces": faces,
                        "seam_edges": seams})

    def _prepare_payload(data):
        verts = data["vertices"]
        faces = data["faces"]
        seams = data.get("seam_edges", [])
        sm = split_mesh(verts, faces, seams)
        ok, witness = check_disk(sm)
        loops = [list(map(int, l)) for l in boundary_loops(sm)]
        boundary_uvs = sorted({u for l in loops for u in l})
        payload = {
            "valid": ok,
            "witness": witness,
            "n_faces": sm.n_faces,
            "n_orig_vertices": len(sm.vertices),
            "n_uv_vertices": sm.n_uv,
            "corner_uv": sm.corner_uv.tolist(),
            "orig_of_uv": sm.orig_of_uv.tolist(),
            "uv_vertices_3d": sm.uv_vertices.tolist(),
            "seam_edges": [list(e) for e in sm.seam_edges],
            "boundary_loops": loops,
            "boundary_uvs": boundary_uvs,
            "faces": sm.faces.tolist(),
            "vertices": sm.vertices.tolist(),
        }
        if ok:
            payload["preview_uv"] = tutte_preview(sm).tolist()
        return sm, payload

    @app.post("/api/prepare")
    def prepare():
        try:
            _, payload = _prepare_payload(request.get_json(force=True))
        except MeshError as exc:
            return jsonify({"valid": False, "error": str(exc),
                            "witness": {"kind": "invalid_input",
                                        "message": str(exc)}}), 400
        return jsonify(payload)

    @app.post("/api/solve")
    def solve():
        data = request.get_json(force=True)
        try:
            sm, prep = _prepare_payload(data)
            if not prep["valid"]:
                return jsonify({"ok": False,
                                "message": "not a topological disk, "
                                           "no solve was attempted",
                                **prep}), 422
            res = solve_lscm(sm, data["anchor0"], data["anchor1"])
        except (MeshError, SolveError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

        uv = res["uv"]
        rows = []
        for fi, tri in enumerate(sm.corner_uv):
            for j in range(3):
                u = int(tri[j])
                rows.append({
                    "face": fi,
                    "corner": j,
                    "orig_vertex": int(sm.faces[fi, j]),
                    "uv_vertex": u,
                    "u": float(uv[u, 0]),
                    "v": float(uv[u, 1]),
                    "angle_error_deg": res["angle_errors_deg"][fi][j],
                })

        return jsonify({
            "ok": True,
            "prepare": {k: prep[k] for k in (
                "boundary_uvs", "boundary_loops", "corner_uv",
                "orig_of_uv", "uv_vertices_3d", "n_uv_vertices")},
            "uv": uv.tolist(),
            "anchors": res["anchors"],
            "energy": res["energy"],
            "rms_row_residual": res["rms_row_residual"],
            "max_conformal_residual": res["max_conformal_residual"],
            "face_conformal_residual": res["face_conformal_residual"],
            "rank": res["rank"],
            "expected_rank": res["expected_rank"],
            "rank_deficient": res["rank_deficient"],
            "smallest_singular_values": res["smallest_singular_values"],
            "flipped_faces": res["flipped_faces"],
            "degenerate_uv_faces": res["degenerate_uv_faces"],
            "face_angle_error_deg": res["face_angle_error_deg"],
            "angle_errors_deg": res["angle_errors_deg"],
            "corners": rows,
        })

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=True)
