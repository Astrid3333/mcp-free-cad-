"""Harness/strap attachment planning for prosthetic and orthotic devices that
need external strap retention (not just an interference-fit socket) -- e.g.
quadruped limb harnesses (quadruped_limb_operations doesn't cover this),
pediatric growth sockets with auxiliary straps, or any device where a
webbing/buckle system supplements primary suspension.

This is a geometric proxy generator + straight-line clearance screening tool,
NOT a strap tension/load simulator and NOT a collision-with-solid checker.
Anchor proxies are simple post/slot primitives sized from preset webbing
widths -- swap for real hardware CAD before fabrication.
"""

import json
from typing import Any, Dict

import FreeCAD
import Part

from .base import BaseHandler


_ANCHOR_PRESETS = {
    "d_ring_loop": {
        "webbing_width_mm": 25.0,
        "post_diameter_mm": 6.0,
        "post_height_mm": 8.0,
        "notes": "Standard D-ring style loop anchor for 25mm (1in) webbing. "
                 "Post is a proxy for a molded-in loop or heat-set insert.",
    },
    "webbing_slot": {
        "webbing_width_mm": 20.0,
        "slot_length_mm": 24.0,
        "slot_width_mm": 4.0,
        "post_height_mm": 6.0,
        "notes": "Slotted pass-through anchor for lighter 20mm webbing, no "
                 "hardware insert needed if wall thickness allows.",
    },
    "buckle_post": {
        "webbing_width_mm": 25.0,
        "post_diameter_mm": 8.0,
        "post_height_mm": 10.0,
        "notes": "Single post for a side-release buckle female half. Verify "
                 "post diameter against the actual buckle hardware before "
                 "fabricating.",
    },
}


class HarnessAttachmentOpsHandler(BaseHandler):
    """Strap/harness anchor point placement and clearance screening for
    external-suspension prosthetic and orthotic devices."""

    _ALLOWED_OPERATIONS = frozenset({
        "list_anchor_presets", "place_strap_anchor", "check_strap_clearance",
    })

    # ------------------------------------------------------------------
    def list_anchor_presets(self, args: Dict[str, Any]) -> str:
        """Read-only. Returns the built-in anchor hardware presets (webbing
        width, proxy post/slot dimensions). Engineering placeholders --
        match against real hardware datasheets before fabricating.
        """
        return json.dumps({
            "ok": True,
            "details": {"presets": _ANCHOR_PRESETS, "count": len(_ANCHOR_PRESETS)},
            "message": f"{len(_ANCHOR_PRESETS)} anchor preset(s).",
        })

    # ------------------------------------------------------------------
    def place_strap_anchor(self, args: Dict[str, Any]) -> str:
        """Create a proxy anchor solid (post or slot) at a given position in
        the active document, representing a strap/harness attachment point.
        This is a standalone geometric proxy -- it does NOT fuse into a
        target shell automatically; run a boolean union (or a PartDesign
        pad/pocket) against the actual socket wall afterwards.

        Args:
          doc_name:    FreeCAD document name
          anchor_type: one of list_anchor_presets() keys (default "d_ring_loop")
          position:    [x, y, z] mm, anchor origin
          normal:      [x, y, z] outward-normal direction the anchor should
                       project along (default [0, 0, 1])
          name:        name for the resulting proxy object
          overrides:   optional dict overriding preset dimensions, e.g.
                       {"post_diameter_mm": 7.0}

        Returns JSON with the created object's name, or an error.
        """
        try:
            doc_name = args.get("doc_name")
            doc = FreeCAD.getDocument(doc_name) if doc_name else self.get_document()
            if not doc:
                return json.dumps({"ok": False, "details": {},
                                    "message": f"No document found (doc_name={doc_name!r})"})

            anchor_type = args.get("anchor_type", "d_ring_loop")
            preset = _ANCHOR_PRESETS.get(anchor_type)
            if preset is None:
                return json.dumps({"ok": False, "details": {"known_types": list(_ANCHOR_PRESETS)},
                                    "message": f"Unknown anchor_type {anchor_type!r}"})

            dims = dict(preset)
            dims.update(args.get("overrides") or {})

            pos = args.get("position") or [0.0, 0.0, 0.0]
            normal = args.get("normal") or [0.0, 0.0, 1.0]
            name = args.get("name") or f"Anchor_{anchor_type}"

            if anchor_type == "webbing_slot":
                slot_len = float(dims.get("slot_length_mm", 24.0))
                slot_w = float(dims.get("slot_width_mm", 4.0))
                thickness = float(dims.get("post_height_mm", 6.0))
                shape = Part.makeBox(slot_len, slot_w, thickness)
                shape.translate(FreeCAD.Vector(-slot_len / 2.0, -slot_w / 2.0, 0.0))
            else:
                diameter = float(dims.get("post_diameter_mm", 6.0))
                height = float(dims.get("post_height_mm", 8.0))
                shape = Part.makeCylinder(diameter / 2.0, height)

            vec_normal = FreeCAD.Vector(*normal)
            if vec_normal.Length > 1e-6:
                rot = FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), vec_normal)
                shape.rotate(FreeCAD.Vector(0, 0, 0), rot.Axis, rot.Angle)
            shape.translate(FreeCAD.Vector(*pos))

            feature = doc.addObject("Part::Feature", name)
            feature.Shape = shape
            doc.recompute()

            return json.dumps({
                "ok": True,
                "details": {"feature_name": feature.Name, "anchor_type": anchor_type,
                             "dims": dims, "position": pos},
                "message": (
                    f"Created anchor proxy '{feature.Name}' ({anchor_type}) at {pos}. "
                    f"Geometric proxy only -- union into the target shell and verify "
                    f"against real hardware dimensions before fabrication."
                ),
            })
        except Exception as e:
            return json.dumps({"ok": False, "details": {},
                                "message": f"Error in place_strap_anchor: {e}"})

    # ------------------------------------------------------------------
    def check_strap_clearance(self, args: Dict[str, Any]) -> str:
        """Screening check: given two or more anchor point positions, reports
        pairwise straight-line distances and flags pairs closer than a
        minimum strap-routing clearance (webbing width + margin). Does NOT
        check for solid geometry blocking the strap path between anchors --
        straight-line distance only, same limitation as contact_pressure_
        operations' geometric-screening scope.

        Args:
          positions:        list of [x, y, z] mm anchor positions (>=2)
          min_clearance_mm: minimum acceptable pairwise distance (default 30.0)

        Returns JSON with pairwise distances and any flagged pairs.
        """
        try:
            positions = args.get("positions") or []
            if len(positions) < 2:
                return json.dumps({"ok": False, "details": {},
                                    "message": "positions must have at least 2 entries"})
            min_clearance = float(args.get("min_clearance_mm", 30.0))

            pairs = []
            flagged = []
            for i in range(len(positions)):
                for j in range(i + 1, len(positions)):
                    p1 = FreeCAD.Vector(*positions[i])
                    p2 = FreeCAD.Vector(*positions[j])
                    dist = (p2 - p1).Length
                    entry = {"i": i, "j": j, "distance_mm": dist}
                    pairs.append(entry)
                    if dist < min_clearance:
                        flagged.append(entry)

            return json.dumps({
                "ok": True,
                "details": {"pairs": pairs, "flagged": flagged, "min_clearance_mm": min_clearance},
                "message": (
                    f"{len(flagged)} pair(s) below {min_clearance}mm clearance. "
                    f"Straight-line distance only -- does not check for solid "
                    f"geometry blocking the strap path between anchors."
                ),
            })
        except Exception as e:
            return json.dumps({"ok": False, "details": {},
                                "message": f"Error in check_strap_clearance: {e}"})
