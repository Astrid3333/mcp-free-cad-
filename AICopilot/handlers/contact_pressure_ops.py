# Contact-pressure proxy handlers for FreeCAD MCP
#
# A cheap, geometry-only proxy for socket-fit quality: given the inner
# surface of a socket and an approximate residual-limb model (even a rough
# cylinder/ellipsoid stand-in), estimate where the socket surface is closest
# to (or overlapping) the limb model. Closer/overlapping = higher expected
# contact pressure. This is NOT a substitute for FEA or clinical pressure
# mapping — it's a first-pass geometric screen to catch obvious problem
# zones (pinch points, tight radii) before a physical fitting session.
#
# Design decisions:
#   - Reuses the same OCCT-precision tolerance conventions as spatial_ops.py
#     so results are directly comparable/combinable with interference checks.
#   - Distance is sampled at a grid of points on the socket's inner surface
#     rather than solved analytically — simple, robust to any surface shape,
#     and fast enough for interactive iteration on a laptop.
#   - Output is a heat-map-style list of (point, distance, risk_level) that
#     an artifact/plot can visualize; this handler does not render anything
#     itself, it only computes.

import json
import math
from typing import Any, Dict, List

from .base import BaseHandler

_OCCT_LIN_TOL = 1e-7  # mm, matches spatial_ops.py convention

# Risk thresholds: distance from socket inner surface to limb model.
# Negative distance = overlap (socket surface intrudes into limb volume).
_RISK_THRESHOLDS_MM = [
    (-999.0, 0.0, "overlap"),        # socket physically interferes — must fix
    (0.0, 0.5, "high_pressure"),     # very tight, likely uncomfortable
    (0.5, 2.0, "moderate_pressure"), # snug but probably tolerable
    (2.0, 999.0, "loose"),           # gap — may cause slippage/rubbing
]


def _classify(distance_mm: float) -> str:
    for lo, hi, label in _RISK_THRESHOLDS_MM:
        if lo <= distance_mm < hi:
            return label
    return "unknown"


class ContactPressureOpsHandler(BaseHandler):
    """Geometric proxy analysis for socket-to-limb contact/fit quality."""

    _ALLOWED_OPERATIONS = frozenset({
        "sample_socket_clearance", "summarize_pressure_zones",
    })

    # ------------------------------------------------------------------
    def sample_socket_clearance(self, args: Dict[str, Any]) -> str:
        """Sample points on a socket's inner surface (faces) and compute
        distance to a limb-model shape, classifying each sample by risk.

        Args:
          socket_shape:     name of the socket object
          limb_model_shape: name of the (simplified) limb model object
          samples_per_face: how many sample points per face (grid resolution)
          inner_face_indices: optional list of 1-based face indices that are
                               the socket's inner (limb-facing) surface. If
                               omitted, all faces are sampled (less precise).

        Returns JSON with per-sample distance + risk classification and a
        summary count by risk level.
        """
        try:
            socket_name = args.get("socket_shape", "")
            limb_name = args.get("limb_model_shape", "")
            samples_per_face = int(args.get("samples_per_face", 5))
            inner_face_indices = args.get("inner_face_indices")

            if not socket_name or not limb_name:
                return json.dumps({"ok": False, "details": {},
                                    "message": "Missing socket_shape or limb_model_shape"})

            doc = self.get_document()
            if not doc:
                return json.dumps({"ok": False, "details": {},
                                    "message": "No active FreeCAD document"})

            socket = self.get_object(socket_name, doc)
            limb = self.get_object(limb_name, doc)
            if not socket or not hasattr(socket, "Shape"):
                return json.dumps({"ok": False, "details": {},
                                    "message": f"Socket object not found: {socket_name}"})
            if not limb or not hasattr(limb, "Shape"):
                return json.dumps({"ok": False, "details": {},
                                    "message": f"Limb model object not found: {limb_name}"})

            faces = socket.Shape.Faces
            if inner_face_indices:
                face_iter = [(i, faces[i - 1]) for i in inner_face_indices
                             if 0 < i <= len(faces)]
            else:
                face_iter = list(enumerate(faces, start=1))

            samples = []
            for face_idx, face in face_iter:
                u0, u1, v0, v1 = face.ParameterRange
                for iu in range(samples_per_face):
                    for iv in range(samples_per_face):
                        u = u0 + (u1 - u0) * (iu + 0.5) / samples_per_face
                        v = v0 + (v1 - v0) * (iv + 0.5) / samples_per_face
                        try:
                            pnt = face.valueAt(u, v)
                        except Exception:
                            continue

                        # Signed distance proxy: distToShape gives unsigned
                        # nearest distance; treat points inside the limb
                        # model as negative (overlap).
                        dist_info = limb.Shape.distToShape(
                            __import__("Part").Vertex(pnt)
                        )
                        raw_dist = dist_info[0]
                        is_inside = limb.Shape.isInside(pnt, _OCCT_LIN_TOL, True)
                        signed_dist = -raw_dist if is_inside else raw_dist

                        samples.append({
                            "face_index": face_idx,
                            "point_mm": [round(pnt.x, 3), round(pnt.y, 3), round(pnt.z, 3)],
                            "distance_mm": round(signed_dist, 4),
                            "risk": _classify(signed_dist),
                        })

            risk_counts: Dict[str, int] = {}
            for s in samples:
                risk_counts[s["risk"]] = risk_counts.get(s["risk"], 0) + 1

            overlap_count = risk_counts.get("overlap", 0)
            high_count = risk_counts.get("high_pressure", 0)

            msg_parts = [f"Sampled {len(samples)} points across {len(face_iter)} face(s)."]
            if overlap_count:
                msg_parts.append(f"{overlap_count} point(s) show OVERLAP — socket "
                                  f"geometry physically intrudes into the limb model.")
            if high_count:
                msg_parts.append(f"{high_count} point(s) in high-pressure zone "
                                  f"(<0.5mm clearance).")
            if not overlap_count and not high_count:
                msg_parts.append("No overlap or high-pressure zones detected.")

            return json.dumps({
                "ok": overlap_count == 0,
                "details": {"samples": samples, "risk_counts": risk_counts},
                "message": " ".join(msg_parts),
            })
        except Exception as e:
            return json.dumps({"ok": False, "details": {},
                                "message": f"Error in sample_socket_clearance: {e}"})

    # ------------------------------------------------------------------
    def summarize_pressure_zones(self, args: Dict[str, Any]) -> str:
        """Cluster the raw samples from sample_socket_clearance into
        contiguous problem zones by proximity, so the message is
        actionable ('one tight zone near the wrist edge') instead of a
        flat list of hundreds of points.

        Args:
          samples: the "samples" list returned by sample_socket_clearance
          cluster_radius_mm: max distance between points to be same cluster
          risk_levels: which risk labels to cluster (default: overlap,
                       high_pressure)

        Returns JSON with cluster centroids, point counts, and worst
        distance per cluster.
        """
        try:
            samples = args.get("samples", [])
            cluster_radius = float(args.get("cluster_radius_mm", 5.0))
            risk_levels = set(args.get("risk_levels", ["overlap", "high_pressure"]))

            flagged = [s for s in samples if s.get("risk") in risk_levels]
            if not flagged:
                return json.dumps({
                    "ok": True, "details": {"clusters": []},
                    "message": f"No samples in risk levels {sorted(risk_levels)}.",
                })

            # Simple greedy clustering — fine for the point counts this
            # handler produces (hundreds, not millions).
            clusters: List[Dict[str, Any]] = []
            for s in flagged:
                p = s["point_mm"]
                placed = False
                for c in clusters:
                    cp = c["centroid_mm"]
                    d = math.dist(p, cp)
                    if d <= cluster_radius:
                        c["points"].append(s)
                        n = len(c["points"])
                        c["centroid_mm"] = [
                            (cp[i] * (n - 1) + p[i]) / n for i in range(3)
                        ]
                        c["worst_distance_mm"] = min(c["worst_distance_mm"], s["distance_mm"])
                        placed = True
                        break
                if not placed:
                    clusters.append({
                        "centroid_mm": p,
                        "points": [s],
                        "worst_distance_mm": s["distance_mm"],
                    })

            summary = [
                {
                    "centroid_mm": [round(v, 2) for v in c["centroid_mm"]],
                    "point_count": len(c["points"]),
                    "worst_distance_mm": round(c["worst_distance_mm"], 3),
                }
                for c in sorted(clusters, key=lambda c: c["worst_distance_mm"])
            ]

            return json.dumps({
                "ok": True,
                "details": {"clusters": summary},
                "message": (
                    f"Found {len(summary)} problem zone(s). Worst: "
                    f"{summary[0]['worst_distance_mm']} mm at "
                    f"{summary[0]['centroid_mm']}."
                ),
            })
        except Exception as e:
            return json.dumps({"ok": False, "details": {},
                                "message": f"Error in summarize_pressure_zones: {e}"})
