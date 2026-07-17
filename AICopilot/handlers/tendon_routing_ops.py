# Tendon-routing handlers for FreeCAD MCP
#
# For tendon-driven prosthetic fingers (Cyborg Beast style): given a chain
# of joint positions, compute anchor points and check that the tendon path
# doesn't require a curvature tighter than the cable can survive without
# jamming or fraying.
#
# Design decisions:
#   - Purely geometric check, not a physics simulation. We model the tendon
#     as a polyline through anchor points and flag any segment pair whose
#     turn angle implies a bend radius under the cable's rated minimum.
#   - Anchor points are placed at a fixed fractional offset from each joint
#     center by default (0.8 * finger segment radius from the flex axis),
#     matching common e-NABLE-style tendon channel placement — but the
#     offset is overridable per joint for custom designs.
#   - Uses spatial_ops-style tolerance conventions (mm-scale absolute
#     tolerances) for consistency with the rest of this handler set.

import json
import math
from typing import Any, Dict, List, Tuple

from .base import BaseHandler

# Common cable minimum bend radii (mm), by cable type. Tighter than this
# and fishing-line/paracord tendons fray quickly at the bend point.
_CABLE_MIN_BEND_RADIUS_MM = {
    "fishing_line_20lb": 3.0,
    "fishing_line_50lb": 4.5,
    "paracord_thin": 6.0,
    "steel_cable_1mm": 8.0,
    "dyneema_1mm": 2.5,
}


def _vec_sub(a: List[float], b: List[float]) -> Tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _vec_len(v: Tuple[float, float, float]) -> float:
    return math.sqrt(sum(c * c for c in v))


def _vec_angle(v1: Tuple[float, float, float], v2: Tuple[float, float, float]) -> float:
    """Angle in degrees between two vectors."""
    l1, l2 = _vec_len(v1), _vec_len(v2)
    if l1 < 1e-9 or l2 < 1e-9:
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    cos_a = max(-1.0, min(1.0, dot / (l1 * l2)))
    return math.degrees(math.acos(cos_a))


class TendonRoutingHandler(BaseHandler):
    """Geometric tendon-path planning and clearance checks for
    tendon-driven prosthetic joints."""

    _ALLOWED_OPERATIONS = frozenset({
        "compute_anchor_points", "check_tendon_curvature",
        "check_tendon_path_clearance",
    })

    # ------------------------------------------------------------------
    def compute_anchor_points(self, args: Dict[str, Any]) -> str:
        """Given a chain of joint center positions and segment radii,
        compute tendon anchor points offset from the flex axis of each
        joint (the standard channel-routing placement).

        Args:
          joint_positions_mm: list of [x, y, z] joint centers, proximal to distal
          segment_radii_mm:   list of radii (one fewer than joints, or same
                               length — extra ignored), used to set anchor offset
          offset_fraction:    fraction of radius to offset anchor from center
                               (default 0.8 — near the volar/palmar surface)

        Returns JSON with computed anchor point list.
        """
        try:
            joints = args.get("joint_positions_mm", [])
            radii = args.get("segment_radii_mm", [])
            offset_fraction = float(args.get("offset_fraction", 0.8))

            if len(joints) < 2:
                return json.dumps({"ok": False, "details": {},
                                    "message": "Need at least 2 joint positions"})

            anchors = []
            for i, jp in enumerate(joints):
                r = radii[i] if i < len(radii) else (radii[-1] if radii else 2.0)
                # Offset anchor toward -Z (palmar side) from joint center —
                # override by editing this handler if your finger's palmar
                # axis differs from -Z in your model orientation.
                anchor = [jp[0], jp[1], jp[2] - r * offset_fraction]
                anchors.append(anchor)

            return json.dumps({
                "ok": True,
                "details": {"anchor_points_mm": anchors, "count": len(anchors)},
                "message": f"Computed {len(anchors)} tendon anchor points along "
                           f"the joint chain (offset {offset_fraction} x radius, -Z side).",
            })
        except Exception as e:
            return json.dumps({"ok": False, "details": {},
                                "message": f"Error in compute_anchor_points: {e}"})

    # ------------------------------------------------------------------
    def check_tendon_curvature(self, args: Dict[str, Any]) -> str:
        """Check whether the tendon path through a list of anchor points
        stays within a cable's minimum safe bend radius at every joint.

        Args:
          anchor_points_mm: list of [x, y, z] points the tendon passes through
          cable_type:       one of _CABLE_MIN_BEND_RADIUS_MM keys, or
          min_bend_radius_mm: explicit override

        Returns JSON with per-segment-pair turn angle, estimated local bend
        radius, and pass/fail against the cable's minimum.
        """
        try:
            points = args.get("anchor_points_mm", [])
            if len(points) < 3:
                return json.dumps({
                    "ok": True,
                    "details": {"checks": []},
                    "message": "Fewer than 3 anchor points — no turns to check.",
                })

            cable_type = args.get("cable_type")
            if args.get("min_bend_radius_mm") is not None:
                min_radius = float(args["min_bend_radius_mm"])
            elif cable_type in _CABLE_MIN_BEND_RADIUS_MM:
                min_radius = _CABLE_MIN_BEND_RADIUS_MM[cable_type]
            else:
                min_radius = _CABLE_MIN_BEND_RADIUS_MM["fishing_line_20lb"]

            checks = []
            all_ok = True
            for i in range(1, len(points) - 1):
                v_in = _vec_sub(points[i], points[i - 1])
                v_out = _vec_sub(points[i + 1], points[i])
                turn_angle = _vec_angle(v_in, v_out)

                # Estimate local bend radius from the shorter adjacent segment
                # length and turn angle (chord-based approximation): a sharper
                # turn over a shorter segment implies a tighter effective bend.
                seg_len = min(_vec_len(v_in), _vec_len(v_out))
                if turn_angle < 0.5:
                    est_radius = float("inf")
                else:
                    est_radius = seg_len / (2 * math.sin(math.radians(turn_angle) / 2) + 1e-9)

                ok = est_radius >= min_radius
                if not ok:
                    all_ok = False
                checks.append({
                    "joint_index": i,
                    "turn_angle_deg": round(turn_angle, 2),
                    "estimated_bend_radius_mm": (
                        round(est_radius, 2) if est_radius != float("inf") else None
                    ),
                    "min_required_mm": min_radius,
                    "ok": ok,
                })

            failing = [c for c in checks if not c["ok"]]
            msg = (
                f"All {len(checks)} tendon turns within safe bend radius "
                f"({min_radius} mm minimum)."
                if all_ok else
                f"{len(failing)}/{len(checks)} turns TOO TIGHT for min radius "
                f"{min_radius} mm — reroute anchors at joint index(es) "
                f"{[c['joint_index'] for c in failing]}."
            )

            return json.dumps({
                "ok": all_ok,
                "details": {"checks": checks, "cable_type": cable_type,
                             "min_bend_radius_mm": min_radius},
                "message": msg,
            })
        except Exception as e:
            return json.dumps({"ok": False, "details": {},
                                "message": f"Error in check_tendon_curvature: {e}"})

    # ------------------------------------------------------------------
    def check_tendon_path_clearance(self, args: Dict[str, Any]) -> str:
        """Check that a straight-line tendon segment between two anchor
        points doesn't pass through solid material of a given shape
        (i.e. the channel actually needs to be drilled/printed there).

        Args:
          shape:             name of the object to check against
          point_a_mm, point_b_mm: segment endpoints
          samples:            number of points to sample along the segment

        Returns JSON with any sample points found inside solid material.
        """
        try:
            object_name = args.get("shape", "")
            a = args.get("point_a_mm")
            b = args.get("point_b_mm")
            samples = int(args.get("samples", 10))

            if not object_name or not a or not b:
                return json.dumps({"ok": False, "details": {},
                                    "message": "Missing shape, point_a_mm, or point_b_mm"})

            doc = self.get_document()
            if not doc:
                return json.dumps({"ok": False, "details": {},
                                    "message": "No active FreeCAD document"})
            obj = self.get_object(object_name, doc)
            if not obj or not hasattr(obj, "Shape"):
                return json.dumps({"ok": False, "details": {},
                                    "message": f"Object not found: {object_name}"})

            import FreeCAD

            blocked_points = []
            for i in range(samples + 1):
                t = i / samples
                p = FreeCAD.Vector(
                    a[0] + t * (b[0] - a[0]),
                    a[1] + t * (b[1] - a[1]),
                    a[2] + t * (b[2] - a[2]),
                )
                # isInside(point, tolerance, checkSolidOnly)
                if obj.Shape.isInside(p, 1e-6, True):
                    blocked_points.append([round(p.x, 3), round(p.y, 3), round(p.z, 3)])

            ok = len(blocked_points) == 0
            msg = (
                f"Tendon path from {a} to {b} is clear of {object_name}'s solid material."
                if ok else
                f"Tendon path passes THROUGH solid material at {len(blocked_points)} "
                f"sample point(s) — a channel/hole needs to be added along this path."
            )
            return json.dumps({
                "ok": ok,
                "details": {"blocked_points_mm": blocked_points, "samples": samples},
                "message": msg,
            })
        except Exception as e:
            return json.dumps({"ok": False, "details": {},
                                "message": f"Error in check_tendon_path_clearance: {e}"})
