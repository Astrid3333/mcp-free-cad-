# Growth-accommodation socket handlers for FreeCAD MCP
#
# Pediatric prosthetic sockets go obsolete fast — kids outgrow them in
# months, and reprinting + refitting a whole socket each time is expensive
# and slow, especially for community/volunteer-driven fabrication (e-NABLE
# style). This handler generates a *telescoping* socket: an outer shell
# plus a family of inner-liner inserts at different sizes, all sharing the
# same outer shell and quick-release interface, so only the liner gets
# reprinted as the child grows.
#
# Design decisions:
#   - Liners are generated as offset shells from a single base profile
#     (parametric, not separately modeled per size) so the whole size
#     family stays consistent and editable from one source curve.
#   - Sizes are expressed as growth-percentile offsets in mm, not arbitrary
#     labels — this keeps the tool clinically legible ("+3mm liner") and
#     avoids inventing a sizing scheme.
#   - The outer shell keeps a constant socket-to-terminal-device interface
#     (reuses quick_connect_ops fittings) so the child's gripper/hand
#     doesn't need to change when the liner is swapped.

import json
from typing import Any, Dict, List

from .base import BaseHandler


class GrowthSocketOpsHandler(BaseHandler):
    """Telescoping / nested-liner socket generation for pediatric prosthetics."""

    _ALLOWED_OPERATIONS = frozenset({
        "create_liner_family", "create_outer_shell",
    })

    # ------------------------------------------------------------------
    def create_outer_shell(self, args: Dict[str, Any]) -> str:
        """Create the fixed outer socket shell from a base profile sketch,
        sized to accept the largest liner in the family plus a fixed wall
        thickness.

        Args:
          profile_sketch: name of a closed Sketch defining the socket's
                           outer cross-section profile
          length_mm:       socket length along the extrusion axis
          max_liner_offset_mm: the largest liner offset expected (mm) — the
                           shell's inner cavity is sized to fit this liner
                           plus clearance
          wall_thickness_mm: shell wall thickness
          clearance_mm:    gap between largest liner and shell inner wall,
                           for liner insertion/removal
          name:            name for the resulting object

        Returns JSON with the created shell object name.
        """
        try:
            profile_name = args.get("profile_sketch", "")
            length = float(args.get("length_mm", 120.0))
            max_liner_offset = float(args.get("max_liner_offset_mm", 6.0))
            wall = float(args.get("wall_thickness_mm", 3.0))
            clearance = float(args.get("clearance_mm", 0.3))
            name = args.get("name", "SocketOuterShell")

            if not profile_name:
                return json.dumps({"ok": False, "details": {},
                                    "message": "Missing required argument: profile_sketch"})

            doc = self.get_document()
            if not doc:
                return json.dumps({"ok": False, "details": {},
                                    "message": "No active FreeCAD document"})

            profile = self.get_object(profile_name, doc)
            if not profile:
                return json.dumps({"ok": False, "details": {},
                                    "message": f"Profile sketch not found: {profile_name}"})

            import Part

            outer_offset_total = max_liner_offset + clearance + wall
            inner_offset_total = max_liner_offset + clearance

            base_face = Part.Face(Part.Wire(profile.Shape.Edges))
            outer_face = base_face.makeOffset2D(outer_offset_total)
            inner_face = base_face.makeOffset2D(inner_offset_total)

            outer_solid = outer_face.extrude(__import__("FreeCAD").Vector(0, 0, length))
            inner_solid = inner_face.extrude(__import__("FreeCAD").Vector(0, 0, length))
            shell_solid = outer_solid.cut(inner_solid)

            shell = doc.addObject("Part::Feature", name)
            shell.Shape = shell_solid
            doc.recompute()

            return json.dumps({
                "ok": True,
                "details": {"shell_name": shell.Name,
                             "inner_cavity_offset_mm": inner_offset_total,
                             "wall_thickness_mm": wall},
                "message": (
                    f"Created outer shell '{shell.Name}' sized for liners up to "
                    f"+{max_liner_offset}mm with {clearance}mm clearance and "
                    f"{wall}mm walls."
                ),
            })
        except Exception as e:
            return json.dumps({"ok": False, "details": {},
                                "message": f"Error in create_outer_shell: {e}"})

    # ------------------------------------------------------------------
    def create_liner_family(self, args: Dict[str, Any]) -> str:
        """Generate a family of liner inserts at a series of growth
        offsets from the same base profile.

        Args:
          profile_sketch: base profile Sketch (limb cross-section, snug fit)
          length_mm:      liner length along extrusion axis
          growth_offsets_mm: list of offsets (mm) to grow the profile outward
                           for each size step, e.g. [0, 2, 4, 6]
          liner_thickness_mm: wall thickness of each liner
          name_prefix:    base name for created objects (size appended)

        Returns JSON listing all created liner object names with their offsets.
        """
        try:
            profile_name = args.get("profile_sketch", "")
            length = float(args.get("length_mm", 120.0))
            offsets = args.get("growth_offsets_mm", [0, 2, 4, 6])
            thickness = float(args.get("liner_thickness_mm", 2.0))
            name_prefix = args.get("name_prefix", "SocketLiner")

            if not profile_name:
                return json.dumps({"ok": False, "details": {},
                                    "message": "Missing required argument: profile_sketch"})
            if not offsets:
                return json.dumps({"ok": False, "details": {},
                                    "message": "growth_offsets_mm must be a non-empty list"})

            doc = self.get_document()
            if not doc:
                return json.dumps({"ok": False, "details": {},
                                    "message": "No active FreeCAD document"})
            profile = self.get_object(profile_name, doc)
            if not profile:
                return json.dumps({"ok": False, "details": {},
                                    "message": f"Profile sketch not found: {profile_name}"})

            import Part
            import FreeCAD

            base_face = Part.Face(Part.Wire(profile.Shape.Edges))
            created = []

            for offset in offsets:
                outer_face = base_face.makeOffset2D(offset + thickness)
                inner_face = base_face.makeOffset2D(offset)
                outer_solid = outer_face.extrude(FreeCAD.Vector(0, 0, length))
                inner_solid = inner_face.extrude(FreeCAD.Vector(0, 0, length))
                liner_solid = outer_solid.cut(inner_solid)

                obj_name = f"{name_prefix}_{offset}mm"
                liner = doc.addObject("Part::Feature", obj_name)
                liner.Shape = liner_solid
                created.append({"name": liner.Name, "growth_offset_mm": offset})

            doc.recompute()

            return json.dumps({
                "ok": True,
                "details": {"liners": created, "max_offset_mm": max(offsets)},
                "message": (
                    f"Created {len(created)} liner(s) at offsets {offsets} mm. "
                    f"Outer shell should be sized for max_liner_offset_mm="
                    f"{max(offsets)} to fit the largest one."
                ),
            })
        except Exception as e:
            return json.dumps({"ok": False, "details": {},
                                "message": f"Error in create_liner_family: {e}"})
