# Quick-connect interface handlers for FreeCAD MCP
#
# A small parametric library of socket <-> terminal-device connectors
# (bayonet, threaded, magnetic-assist) so the same socket can accept
# different end effectors (work hook, cosmetic hand, tool adapter) without
# refitting. This is the piece that makes growth_socket_ops liners and
# different hands/hooks actually interchangeable in practice.
#
# Design decisions:
#   - Each connector type generates a MATCHED male/female pair from the
#     same call, so dimensions can never drift out of sync between the two
#     halves (a common failure mode when they're modeled separately).
#   - Bayonet is the default recommendation for daily-use prosthetics —
#     no loose hardware, tolerant of dirt/print imprecision, one-handed
#     donning with the sound hand.
#   - Magnetic-assist is offered as a *retention aid* layered on top of
#     bayonet/threaded, not a standalone connector — magnets alone don't
#     resist the torque of lifting an object.

import json
import math
from typing import Any, Dict

from .base import BaseHandler

_CONNECTOR_PRESETS = {
    "bayonet": {
        "recommended_diameter_mm": 25.0,
        "recommended_lug_count": 3,
        "notes": "No loose hardware; quarter-turn lock. Good default for "
                 "daily-use hand/hook swaps.",
    },
    "threaded": {
        "recommended_diameter_mm": 22.0,
        "recommended_pitch_mm": 2.0,
        "notes": "Very secure, higher torque resistance than bayonet, but "
                 "slower to don/doff and can cross-thread if misaligned "
                 "one-handed.",
    },
}


class QuickConnectOpsHandler(BaseHandler):
    """Parametric socket-to-terminal-device quick-connect interfaces."""

    _ALLOWED_OPERATIONS = frozenset({
        "create_bayonet_pair", "create_threaded_pair", "add_magnetic_retention",
        "list_connector_presets",
    })

    # ------------------------------------------------------------------
    def list_connector_presets(self, args: Dict[str, Any]) -> str:
        """Return the built-in connector presets and their recommended
        starting dimensions."""
        return json.dumps({
            "ok": True,
            "details": {"presets": _CONNECTOR_PRESETS},
            "message": f"{len(_CONNECTOR_PRESETS)} connector preset(s) available: "
                       f"{list(_CONNECTOR_PRESETS)}.",
        })

    # ------------------------------------------------------------------
    def create_bayonet_pair(self, args: Dict[str, Any]) -> str:
        """Create matched male (socket-side) and female (device-side)
        bayonet connector halves.

        Args:
          diameter_mm:   outer diameter of the mating cylinder
          lug_count:     number of bayonet lugs (2-4 typical)
          lug_length_mm, lug_thickness_mm, lug_travel_deg: lug geometry
          barrel_length_mm: length of the mating cylinder
          male_position_mm / female_position_mm: [x,y,z] placement
          name_prefix:   base name for created objects

        Returns JSON with created object names for both halves.
        """
        try:
            diameter = float(args.get("diameter_mm", 25.0))
            lug_count = int(args.get("lug_count", 3))
            lug_length = float(args.get("lug_length_mm", 6.0))
            lug_thickness = float(args.get("lug_thickness_mm", 2.0))
            lug_travel_deg = float(args.get("lug_travel_deg", 30.0))
            barrel_length = float(args.get("barrel_length_mm", 15.0))
            male_pos = args.get("male_position_mm", [0, 0, 0])
            female_pos = args.get("female_position_mm", [40, 0, 0])
            name_prefix = args.get("name_prefix", "Bayonet")

            doc = self.get_document()
            if not doc:
                return json.dumps({"ok": False, "details": {},
                                    "message": "No active FreeCAD document"})

            import Part
            import FreeCAD

            radius = diameter / 2.0

            # Male half: barrel + protruding lugs
            barrel = Part.makeCylinder(radius, barrel_length)
            lugs = []
            for i in range(lug_count):
                angle = i * (360.0 / lug_count)
                lug = Part.makeBox(lug_thickness, radius * 0.35, lug_length)
                lug.translate(FreeCAD.Vector(-lug_thickness / 2, radius, barrel_length - lug_length))
                lug.rotate(FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 0, 1), angle)
                lugs.append(lug)
            male_shape = barrel
            for lug in lugs:
                male_shape = male_shape.fuse(lug)
            male_shape.translate(FreeCAD.Vector(*male_pos))

            male_obj = doc.addObject("Part::Feature", f"{name_prefix}_Male")
            male_obj.Shape = male_shape

            # Female half: bore with matching L-shaped slots (bore radius
            # slightly larger for clearance, slot geometry mirrors lug travel)
            clearance = 0.2
            bore = Part.makeCylinder(radius + clearance, barrel_length + 1)
            slots = []
            for i in range(lug_count):
                angle = i * (360.0 / lug_count)
                # Straight entry slot
                entry = Part.makeBox(lug_thickness + 2 * clearance, radius * 0.4, lug_length + 2)
                entry.translate(FreeCAD.Vector(-(lug_thickness + 2 * clearance) / 2, radius - 1,
                                                barrel_length - lug_length - 1))
                entry.rotate(FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 0, 1), angle)
                slots.append(entry)
                # Twist-lock slot (rotated cut representing the quarter-turn path)
                twist = Part.makeBox(lug_thickness + 2 * clearance, radius * 0.4, lug_length + 2)
                twist.translate(FreeCAD.Vector(-(lug_thickness + 2 * clearance) / 2, radius - 1,
                                                barrel_length - lug_length - 1))
                twist.rotate(FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 0, 1),
                             angle + lug_travel_deg)
                slots.append(twist)

            female_shape = bore
            for slot in slots:
                female_shape = female_shape.fuse(slot)
            female_shape.translate(FreeCAD.Vector(*female_pos))

            female_obj = doc.addObject("Part::Feature", f"{name_prefix}_Female")
            female_obj.Shape = female_shape

            doc.recompute()

            return json.dumps({
                "ok": True,
                "details": {
                    "male_name": male_obj.Name,
                    "female_name": female_obj.Name,
                    "diameter_mm": diameter,
                    "lug_count": lug_count,
                    "lug_travel_deg": lug_travel_deg,
                },
                "message": (
                    f"Created matched bayonet pair: '{male_obj.Name}' (male, "
                    f"{lug_count} lugs) and '{female_obj.Name}' (female bore, "
                    f"quarter-turn lock over {lug_travel_deg}°). Note: the "
                    f"female half here is a solid to cut/fuse into your device "
                    f"body — subtract '{female_obj.Name}' from your terminal "
                    f"device shape to create the actual socket."
                ),
            })
        except Exception as e:
            return json.dumps({"ok": False, "details": {},
                                "message": f"Error in create_bayonet_pair: {e}"})

    # ------------------------------------------------------------------
    def create_threaded_pair(self, args: Dict[str, Any]) -> str:
        """Create matched male/female threaded connector halves using
        FreeCAD's Part ThreadProfile / helix-sweep approach.

        Args:
          diameter_mm, pitch_mm, length_mm: thread geometry
          male_position_mm / female_position_mm: [x,y,z] placement
          name_prefix: base name for created objects

        Returns JSON with created object names for both halves. Falls back
        to a simplified (non-threaded, friction-fit taper) pair with a
        warning if the Part thread-sweep API isn't available in this
        FreeCAD build.
        """
        try:
            diameter = float(args.get("diameter_mm", 22.0))
            pitch = float(args.get("pitch_mm", 2.0))
            length = float(args.get("length_mm", 15.0))
            male_pos = args.get("male_position_mm", [0, 0, 0])
            female_pos = args.get("female_position_mm", [40, 0, 0])
            name_prefix = args.get("name_prefix", "Threaded")

            doc = self.get_document()
            if not doc:
                return json.dumps({"ok": False, "details": {},
                                    "message": "No active FreeCAD document"})

            import Part
            import FreeCAD

            try:
                # Preferred: real helical thread via Part::Thread if present
                # in this FreeCAD build (added in recent versions).
                male_shape = Part.makeThread(
                    pitch, diameter, length
                ) if hasattr(Part, "makeThread") else None
            except Exception:
                male_shape = None

            fallback_used = male_shape is None
            if fallback_used:
                # Simplified friction-taper fallback: a slight cone instead
                # of real threads. Not load-rated for high torque — flag it.
                radius = diameter / 2.0
                male_shape = Part.makeCone(radius, radius * 0.92, length)

            male_shape.translate(FreeCAD.Vector(*male_pos))
            male_obj = doc.addObject("Part::Feature", f"{name_prefix}_Male")
            male_obj.Shape = male_shape

            radius = diameter / 2.0
            female_bore = (Part.makeCone(radius + 0.1, radius * 0.92 + 0.1, length)
                            if fallback_used else
                            Part.makeCylinder(radius + 0.15, length))
            female_bore.translate(FreeCAD.Vector(*female_pos))
            female_obj = doc.addObject("Part::Feature", f"{name_prefix}_Female")
            female_obj.Shape = female_bore

            doc.recompute()

            msg = (
                f"Created matched threaded pair: '{male_obj.Name}' / "
                f"'{female_obj.Name}' (pitch {pitch}mm, dia {diameter}mm)."
            )
            if fallback_used:
                msg += (
                    " WARNING: this FreeCAD build's Part module has no thread-sweep "
                    "API — used a friction-taper fallback instead of real threads. "
                    "Not suitable for load-bearing connections; use "
                    "create_bayonet_pair for daily-use prosthetics instead."
                )

            return json.dumps({
                "ok": True,
                "details": {"male_name": male_obj.Name, "female_name": female_obj.Name,
                             "used_fallback_taper": fallback_used},
                "message": msg,
            })
        except Exception as e:
            return json.dumps({"ok": False, "details": {},
                                "message": f"Error in create_threaded_pair: {e}"})

    # ------------------------------------------------------------------
    def add_magnetic_retention(self, args: Dict[str, Any]) -> str:
        """Cut magnet-sized recesses into an existing connector pair as a
        retention aid (prevents accidental partial-disengagement, does NOT
        replace the mechanical lock for load-bearing).

        Args:
          male_shape / female_shape: object names to cut recesses into
          magnet_diameter_mm, magnet_thickness_mm: standard disc-magnet size
          position_mm: [x,y,z] center of the recess on each part
          name_suffix: appended to output object names

        Returns JSON with the two new cut feature names.
        """
        try:
            male_name = args.get("male_shape", "")
            female_name = args.get("female_shape", "")
            mag_d = float(args.get("magnet_diameter_mm", 6.0))
            mag_t = float(args.get("magnet_thickness_mm", 2.0))
            pos = args.get("position_mm", [0, 0, 0])
            suffix = args.get("name_suffix", "_MagRecess")

            if not male_name or not female_name:
                return json.dumps({"ok": False, "details": {},
                                    "message": "Missing male_shape or female_shape"})

            doc = self.get_document()
            if not doc:
                return json.dumps({"ok": False, "details": {},
                                    "message": "No active FreeCAD document"})

            results = {}
            import Part
            import FreeCAD
            for role, obj_name in (("male", male_name), ("female", female_name)):
                obj = self.get_object(obj_name, doc)
                if not obj or not hasattr(obj, "Shape"):
                    return json.dumps({"ok": False, "details": {},
                                        "message": f"Object not found: {obj_name}"})
                recess = Part.makeCylinder(mag_d / 2.0, mag_t)
                recess.translate(FreeCAD.Vector(*pos))
                cut_shape = obj.Shape.cut(recess)

                new_name = f"{obj_name}{suffix}"
                new_obj = doc.addObject("Part::Feature", new_name)
                new_obj.Shape = cut_shape
                results[role] = new_obj.Name

            doc.recompute()

            return json.dumps({
                "ok": True,
                "details": results,
                "message": (
                    f"Added {mag_d}mm x {mag_t}mm magnet recesses to both halves: "
                    f"{results['male']}, {results['female']}. Remember: magnets "
                    f"assist alignment/retention only — the mechanical lock "
                    f"(bayonet/thread) still carries the load."
                ),
            })
        except Exception as e:
            return json.dumps({"ok": False, "details": {},
                                "message": f"Error in add_magnetic_retention: {e}"})
