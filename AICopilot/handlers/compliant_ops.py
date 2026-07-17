# Compliant-mechanism handlers for FreeCAD MCP
#
# Living-hinge / print-in-place flexure generation for prosthetic fingers
# and other subactuated joints.  Goal: replace pin-and-pivot joints (which
# wear, need lubrication, and are a common failure point in tendon-driven
# prosthetic hands) with a single-piece flexure whose stiffness and fatigue
# life are set by geometry, not hardware.
#
# Design decisions:
#   - Hinge thickness is derived from material + expected cycle count, not
#     just picked by eye. PETG and TPU have very different safe strain
#     limits before hinges start micro-cracking under repeated flexion.
#   - We generate the hinge as a thin rectangular reduced-section cut
#     across the part (classic "living hinge"), not as a separate part —
#     print-in-place, no assembly step, no lost pins.
#   - All geometry stays in the FreeCAD Sketcher/Part layer so hinges can
#     be edited later like any other feature (consistent with how
#     partdesign_ops.py treats fillet/chamfer as editable features).

import json
import math
from typing import Any, Dict

from .base import BaseHandler

# ---------------------------------------------------------------------------
# Material presets: safe strain limits and recommended hinge thickness
# ranges, derived from common FDM living-hinge design guidance. These are
# starting points, not certified values — always validate with a physical
# fatigue test before clinical use.
# ---------------------------------------------------------------------------

_MATERIAL_PRESETS = {
    "petg": {
        "min_thickness_mm": 0.6,
        "max_thickness_mm": 1.2,
        "safe_strain_pct": 4.0,      # conservative vs PETG's ~20% break strain
        "notes": "PETG hinges crack under repeated flex sooner than TPU; "
                 "favor the thicker end of the range and fewer expected cycles.",
    },
    "tpu": {
        "min_thickness_mm": 0.4,
        "max_thickness_mm": 1.0,
        "safe_strain_pct": 12.0,
        "notes": "TPU is the standard living-hinge material — high fatigue "
                 "life, but too flexible alone for load-bearing sections.",
    },
    "pla": {
        "min_thickness_mm": 0.8,
        "max_thickness_mm": 1.5,
        "safe_strain_pct": 2.0,
        "notes": "PLA is brittle for living hinges — only use for low-cycle "
                 "or single-use prototypes, not daily-use prosthetics.",
    },
}

_DEFAULT_CYCLE_DERATE = {
    # cycles_expected -> multiply base thickness by this factor
    # (more cycles = need thicker/stiffer hinge to stay under strain limit,
    # trading some flexibility for fatigue life)
    1000: 1.0,
    10000: 1.15,
    100000: 1.35,
    1000000: 1.6,
}


def _derate_for_cycles(cycles: int) -> float:
    """Return a thickness multiplier for the given expected cycle count."""
    thresholds = sorted(_DEFAULT_CYCLE_DERATE.keys())
    factor = _DEFAULT_CYCLE_DERATE[thresholds[0]]
    for t in thresholds:
        if cycles >= t:
            factor = _DEFAULT_CYCLE_DERATE[t]
    return factor


class CompliantOpsHandler(BaseHandler):
    """Living-hinge / compliant-joint generation for prosthetic mechanisms."""

    _ALLOWED_OPERATIONS = frozenset({
        "recommend_hinge_thickness", "create_living_hinge",
        "create_flexure_array",
    })

    # ------------------------------------------------------------------
    def recommend_hinge_thickness(self, args: Dict[str, Any]) -> str:
        """Recommend a hinge thickness given material, flex angle, and
        expected cycle count.

        Args:
          material:        "petg" | "tpu" | "pla"
          flex_angle_deg:  total angle the hinge must bend through (e.g. 90)
          hinge_length_mm: length of the hinge along the bend axis
          expected_cycles: int, how many flex cycles it should survive

        Returns JSON with recommended thickness (mm) and reasoning.
        """
        try:
            material = str(args.get("material", "tpu")).lower()
            if material not in _MATERIAL_PRESETS:
                return json.dumps({
                    "ok": False, "details": {},
                    "message": f"Unknown material {material!r}. "
                               f"Choose one of: {list(_MATERIAL_PRESETS)}",
                })
            preset = _MATERIAL_PRESETS[material]

            flex_angle_deg = float(args.get("flex_angle_deg", 90.0))
            hinge_length_mm = float(args.get("hinge_length_mm", 10.0))
            expected_cycles = int(args.get("expected_cycles", 10000))

            # Simple bend-strain model: strain ≈ thickness / (2 * bend_radius),
            # and bend_radius ≈ hinge_length / flex_angle_rad for a hinge that
            # bends roughly uniformly across its length.
            flex_angle_rad = math.radians(max(flex_angle_deg, 1.0))
            bend_radius = hinge_length_mm / flex_angle_rad

            safe_strain = preset["safe_strain_pct"] / 100.0
            # thickness = 2 * bend_radius * safe_strain, clamped to preset range
            base_thickness = 2.0 * bend_radius * safe_strain
            derate = _derate_for_cycles(expected_cycles)
            thickness = base_thickness * derate

            thickness = max(preset["min_thickness_mm"],
                             min(preset["max_thickness_mm"], thickness))

            return json.dumps({
                "ok": True,
                "details": {
                    "material": material,
                    "recommended_thickness_mm": round(thickness, 3),
                    "bend_radius_mm": round(bend_radius, 3),
                    "cycle_derate_factor": derate,
                    "material_notes": preset["notes"],
                    "thickness_range_mm": [preset["min_thickness_mm"],
                                            preset["max_thickness_mm"]],
                },
                "message": (
                    f"Recommended hinge thickness for {material.upper()}: "
                    f"{round(thickness, 2)} mm (bend radius {round(bend_radius, 2)} mm, "
                    f"derated for {expected_cycles} cycles). This is a starting "
                    f"estimate — validate with a physical fatigue sample before "
                    f"clinical use."
                ),
            })
        except Exception as e:
            return json.dumps({"ok": False, "details": {},
                                "message": f"Error in recommend_hinge_thickness: {e}"})

    # ------------------------------------------------------------------
    def create_living_hinge(self, args: Dict[str, Any]) -> str:
        """Cut a reduced-section living hinge across an existing solid.

        Args:
          shape:          name of the object to cut the hinge into
          position_mm:    [x, y, z] center point of the hinge cut
          axis:           "x" | "y" | "z" — bend axis (hinge runs perpendicular)
          thickness_mm:   remaining material thickness at the hinge
          width_mm:       width of the hinge cut across the part
          name:           name for the resulting feature

        Returns JSON with the created feature name, or an error if the
        object/geometry isn't found.
        """
        try:
            object_name = args.get("shape", "")
            if not object_name:
                return json.dumps({"ok": False, "details": {},
                                    "message": "Missing required argument: shape"})

            doc = self.get_document()
            if not doc:
                return json.dumps({"ok": False, "details": {},
                                    "message": "No active FreeCAD document"})

            obj = self.get_object(object_name, doc)
            if not obj or not hasattr(obj, "Shape"):
                return json.dumps({"ok": False, "details": {},
                                    "message": f"Object not found or has no Shape: {object_name}"})

            pos = args.get("position_mm", [0, 0, 0])
            axis = str(args.get("axis", "z")).lower()
            thickness = float(args.get("thickness_mm", 0.8))
            width = float(args.get("width_mm", 10.0))
            name = args.get("name", f"{object_name}_LivingHinge")

            import FreeCAD
            import Part

            bb = obj.Shape.BoundBox
            # Cutting box spans the full part in the two axes perpendicular
            # to the hinge thickness direction, and is `thickness` short of
            # spanning the part along the thickness axis (leaves material).
            span = {
                "x": (bb.YLength + 10, bb.ZLength + 10, thickness),
                "y": (bb.XLength + 10, bb.ZLength + 10, thickness),
                "z": (bb.XLength + 10, bb.YLength + 10, thickness),
            }
            if axis not in span:
                return json.dumps({"ok": False, "details": {},
                                    "message": f"axis must be x, y, or z, got {axis!r}"})

            l, w, box_thickness = span[axis]
            box = Part.makeBox(l if axis != "x" else box_thickness,
                                w if axis != "y" else box_thickness,
                                width if axis == "z" else w)

            center = FreeCAD.Vector(*pos)
            # Place cutting box centered on `pos`, sized so it removes
            # material down to `thickness_mm` remaining along `axis`.
            offset = FreeCAD.Vector(
                -box.BoundBox.XLength / 2, -box.BoundBox.YLength / 2, -box.BoundBox.ZLength / 2
            )
            box.translate(center + offset)

            cut_shape = obj.Shape.cut(box)
            feature = doc.addObject("Part::Feature", name)
            feature.Shape = cut_shape
            doc.recompute()

            return json.dumps({
                "ok": True,
                "details": {"feature_name": feature.Name, "axis": axis,
                             "thickness_mm": thickness},
                "message": (
                    f"Created living hinge '{feature.Name}' on {object_name}: "
                    f"{thickness} mm remaining thickness along {axis}-axis."
                ),
            })
        except Exception as e:
            return json.dumps({"ok": False, "details": {},
                                "message": f"Error in create_living_hinge: {e}"})

    # ------------------------------------------------------------------
    def create_flexure_array(self, args: Dict[str, Any]) -> str:
        """Create a row of parallel living hinges (finger-joint style array)
        along a shape, for a segmented compliant finger.

        Args:
          shape:          object to cut into
          start_mm / end_mm: [x, y, z] endpoints defining the array line
          count:          number of hinges
          axis, thickness_mm, width_mm: same as create_living_hinge

        Returns JSON listing all created feature names.
        """
        try:
            object_name = args.get("shape", "")
            start = args.get("start_mm", [0, 0, 0])
            end = args.get("end_mm", [50, 0, 0])
            count = int(args.get("count", 3))
            if count < 1:
                return json.dumps({"ok": False, "details": {},
                                    "message": "count must be >= 1"})

            created = []
            errors = []
            for i in range(count):
                t = (i + 1) / (count + 1)  # evenly spaced, not at the very ends
                pos = [start[k] + t * (end[k] - start[k]) for k in range(3)]
                sub_args = dict(args)
                sub_args["shape"] = created[-1]["feature_name"] if created else object_name
                sub_args["position_mm"] = pos
                sub_args["name"] = f"{object_name}_Hinge{i+1}"
                result = json.loads(self.create_living_hinge(sub_args))
                if result.get("ok"):
                    created.append(result["details"])
                else:
                    errors.append(result.get("message"))
                    break

            return json.dumps({
                "ok": len(errors) == 0,
                "details": {"created": created, "errors": errors},
                "message": (
                    f"Created {len(created)}/{count} hinges in array."
                    + (f" Stopped early: {errors[0]}" if errors else "")
                ),
            })
        except Exception as e:
            return json.dumps({"ok": False, "details": {},
                                "message": f"Error in create_flexure_array: {e}"})
