# Organic/freeform geometry handlers for FreeCAD MCP
#
# Cross-section-stack and loft-based solid generation for anatomical forms
# (prosthetic sockets, limb-following geometry) that can't be expressed
# with rigid primitives (box/cylinder/cone).
#
# Design decisions:
#   - Sections are built as raw Part wires (circle / ellipse / rounded
#     rectangle), NOT Sketcher sketches. This avoids the datum-plane +
#     attachment complexity of parametric sketches, at the cost of the
#     result being less "editable later" than a Sketcher-based feature.
#     Good enough for a first-pass anatomical proxy; can be upgraded to
#     sketch-based sections later if parametric editability is needed.
#   - Only a practical subset of the tool's declared operation enum is
#     implemented here (cross_section_stack, organic_loft, skin_solid,
#     offset_surface, organic_sweep, section_profiles). The others
#     (bspline_surface, blend_surface, point_cloud_surface, etc.) are
#     declared in the tool schema for future work but will currently
#     return "Unknown organic_operations operation: X" until handlers
#     are added below.
#   - organic_sweep and section_profiles are the two that actually break
#     the "straight x/y/z axis only" limitation of cross_section_stack:
#     organic_sweep follows an arbitrary curved spine via Part::Sweep
#     (corrected-Frenet by default, i.e. no unwanted twist), and
#     section_profiles samples cross-sections by arc length + tangent
#     along a curved spine, feeding organic_loft with sections that
#     actually bend in 3D instead of sitting on one straight line.

import json
import math
from typing import Any, Dict, List

import FreeCAD
import Part

from .base import BaseHandler


# ---------------------------------------------------------------------------
# Section-wire builders
# ---------------------------------------------------------------------------

def _rounded_rect_wire(width: float, height: float, corner_radius: float) -> "Part.Wire":
    """Build a closed wire for a rounded rectangle centered at the origin,
    in the local XY plane."""
    w2, h2 = width / 2.0, height / 2.0
    r = max(0.0, min(corner_radius, w2, h2))

    if r <= 1e-6:
        pts = [
            FreeCAD.Vector(-w2, -h2, 0), FreeCAD.Vector(w2, -h2, 0),
            FreeCAD.Vector(w2, h2, 0), FreeCAD.Vector(-w2, h2, 0),
            FreeCAD.Vector(-w2, -h2, 0),
        ]
        return Part.makePolygon(pts)

    # Four straight edges + four corner arcs, going counter-clockwise
    # starting at the bottom edge's left end.
    edges = []
    corners = [
        # (arc_center, start_angle_deg, end_angle_deg)
        (FreeCAD.Vector(w2 - r, -h2 + r, 0), -90, 0),
        (FreeCAD.Vector(w2 - r, h2 - r, 0), 0, 90),
        (FreeCAD.Vector(-w2 + r, h2 - r, 0), 90, 180),
        (FreeCAD.Vector(-w2 + r, -h2 + r, 0), 180, 270),
    ]
    line_starts = [
        (FreeCAD.Vector(-w2 + r, -h2, 0), FreeCAD.Vector(w2 - r, -h2, 0)),
        (FreeCAD.Vector(w2, -h2 + r, 0), FreeCAD.Vector(w2, h2 - r, 0)),
        (FreeCAD.Vector(w2 - r, h2, 0), FreeCAD.Vector(-w2 + r, h2, 0)),
        (FreeCAD.Vector(-w2, h2 - r, 0), FreeCAD.Vector(-w2, -h2 + r, 0)),
    ]
    for (p1, p2), (center, a1, a2) in zip(line_starts, corners):
        edges.append(Part.makeLine(p1, p2))
        edges.append(Part.makeCircle(r, center, FreeCAD.Vector(0, 0, 1), a1, a2))

    wire = Part.Wire(Part.__sortEdges__(edges) if hasattr(Part, "__sortEdges__") else edges)
    return wire


def _ellipse_wire(width: float, height: float) -> "Part.Wire":
    """Closed elliptical wire centered at the origin, local XY plane.
    width/height are full diameters along X/Y (matches cross_section_stack
    docstring convention); a circle is just width == height."""
    major = max(width, height) / 2.0
    minor = min(width, height) / 2.0
    if major <= 1e-6:
        raise ValueError("width/height must be > 0")
    ell = Part.Ellipse(FreeCAD.Vector(0, 0, 0), major, minor)
    edge = ell.toShape()
    wire = Part.Wire([edge])
    if width < height:
        # Ellipse() puts the major axis along local X; rotate 90 deg so the
        # larger dimension lines up with height, matching caller intent.
        wire.rotate(FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 0, 1), 90)
    return wire


def _circle_wire(width: float) -> "Part.Wire":
    radius = width / 2.0
    if radius <= 1e-6:
        raise ValueError("width (diameter) must be > 0")
    edge = Part.makeCircle(radius)
    return Part.Wire([edge])


def _polygon_wire(points) -> "Part.Wire":
    """Closed wire built from explicit (x, y) points in the local XY plane,
    connected with straight edges (not a smooth spline). Use for asymmetric
    sections (e.g. per-quadrant trim cuts) that a pure circle/ellipse/
    rounded_rect can't express -- see herramientas-auxiliares/protesis/
    perfil_seccion_asimetrica.py for one way to generate `points`.

    points: list of (x, y) tuples/lists, in mm, local to the section plane.
    At least 3 points required. The wire is closed automatically (no need
    to repeat the first point at the end)."""
    if len(points) < 3:
        raise ValueError("polygon section needs at least 3 points")
    vecs = [FreeCAD.Vector(float(x), float(y), 0) for x, y in points]
    vecs.append(vecs[0])  # close the loop
    return Part.makePolygon(vecs)


def _smooth_polygon_wire(points) -> "Part.Wire":
    """Closed wire built from explicit (x, y) points in the local XY plane,
    interpolated with a smooth PERIODIC B-spline (not straight edges).

    Use for organic/anatomical sections where the perimeter itself should
    read as a continuous curve rather than a faceted polygon -- e.g. an
    asymmetric socket cross-section from
    herramientas-auxiliares/protesis/perfil_seccion_asimetrica.py.

    points: list of (x, y) tuples/lists, in mm, local to the section plane.
    At least 4 points required (a periodic spline needs enough points to
    define curvature around the loop). Do not repeat the first point at
    the end -- periodicity is handled by the BSplineCurve itself.
    """
    if len(points) < 4:
        raise ValueError("smooth_polygon section needs at least 4 points")
    vecs = [FreeCAD.Vector(float(x), float(y), 0) for x, y in points]
    curve = Part.BSplineCurve()
    curve.interpolate(vecs, PeriodicFlag=True)
    return Part.Wire([curve.toShape()])


def _section_wire(shape: str, width: float, height: float, corner_radius: float,
                   points=None) -> "Part.Wire":
    shape = (shape or "circle").lower()
    if shape == "circle":
        return _circle_wire(width)
    if shape == "ellipse":
        return _ellipse_wire(width, height or width)
    if shape == "rounded_rect":
        return _rounded_rect_wire(width, height or width, corner_radius or 0.0)
    if shape == "polygon":
        if not points:
            raise ValueError(
                "shape='polygon' requires a non-empty 'points' list "
                "(list of [x, y] pairs) in the section dict"
            )
        return _polygon_wire(points)
    if shape == "smooth_polygon":
        if not points:
            raise ValueError(
                "shape='smooth_polygon' requires a non-empty 'points' list "
                "(list of [x, y] pairs) in the section dict"
            )
        return _smooth_polygon_wire(points)
    raise ValueError(f"Unknown section shape {shape!r}. Use circle|ellipse|rounded_rect|polygon|smooth_polygon.")


_AXIS_VECTORS = {
    "x": FreeCAD.Vector(1, 0, 0),
    "y": FreeCAD.Vector(0, 1, 0),
    "z": FreeCAD.Vector(0, 0, 1),
}


def _place_section(wire: "Part.Wire", axis: str, position: float, twist_deg: float = 0.0):
    """Move a section wire (built flat in local XY, normal +Z) so its plane
    is perpendicular to `axis` and it sits at `position` mm along that axis.
    Optional twist_deg rotates the section about the axis before placement
    (useful for anatomically-twisted forms like a transradial socket)."""
    axis = axis.lower()
    if axis not in _AXIS_VECTORS:
        raise ValueError(f"axis must be x, y, or z, got {axis!r}")

    if twist_deg:
        wire.rotate(FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 0, 1), twist_deg)

    if axis == "z":
        placement = FreeCAD.Placement(FreeCAD.Vector(0, 0, position), FreeCAD.Rotation())
    elif axis == "x":
        # Rotate local-XY-plane wire so its normal points along +X, then
        # translate along X.
        rot = FreeCAD.Rotation(FreeCAD.Vector(0, 1, 0), 90)
        placement = FreeCAD.Placement(FreeCAD.Vector(position, 0, 0), rot)
    else:  # y
        rot = FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), -90)
        placement = FreeCAD.Placement(FreeCAD.Vector(0, position, 0), rot)

    wire.Placement = placement
    return wire


class OrganicOpsHandler(BaseHandler):
    """Freeform / organic solid modeling for forms rigid primitives can't
    express: prosthetic sockets, anatomical cross-sections, biomorphic
    forms. See module docstring for which of the schema's declared
    operations are actually implemented."""

    _ALLOWED_OPERATIONS = frozenset({
        "cross_section_stack", "organic_loft", "skin_solid", "offset_surface",
        "organic_sweep", "section_profiles",
    })

    # ------------------------------------------------------------------
    def cross_section_stack(self, args: Dict[str, Any]) -> str:
        """Build a parametric solid by lofting through a stack of 2D
        cross-sections placed along an axis. Ideal for anatomical forms
        like prosthetic sockets specified as a series of measurements
        (e.g. circumferences/widths at different heights).

        Args:
          doc_name:  FreeCAD document name
          sections:  list of {position, shape, width, height, corner_radius,
                     twist_deg} — see tool schema for the full example.
          axis:      "x" | "y" | "z" — axis sections are stacked along
          name:      name for the resulting solid
          ruled:     if True, linear interpolation between sections instead
                     of a smooth loft (sharper transitions, useful for
                     angular/rounded-rect stacks)
          closed_loft: close the loft back to the first section

        Returns JSON with the created object's name, or an error.
        """
        try:
            doc_name = args.get("doc_name")
            doc = FreeCAD.getDocument(doc_name) if doc_name else self.get_document()
            if not doc:
                return json.dumps({"ok": False, "details": {},
                                    "message": f"No document found (doc_name={doc_name!r})"})

            sections = args.get("sections") or []
            if len(sections) < 2:
                return json.dumps({"ok": False, "details": {},
                                    "message": "sections must have at least 2 entries"})

            axis = str(args.get("axis", "z"))
            name = args.get("name") or "OrganicSolid"
            ruled = bool(args.get("ruled", False))
            closed_loft = bool(args.get("closed_loft", False))

            wires = []
            for i, sec in enumerate(sections):
                try:
                    w = _section_wire(
                        sec.get("shape", "circle"),
                        float(sec.get("width", 10.0)),
                        float(sec.get("height", 0.0)) or float(sec.get("width", 10.0)),
                        float(sec.get("corner_radius", 0.0)),
                        sec.get("points"),
                    )
                    _place_section(w, axis, float(sec.get("position", 0.0)),
                                    float(sec.get("twist_deg", 0.0)))
                    wires.append(w)
                except Exception as sec_err:
                    return json.dumps({"ok": False, "details": {"section_index": i},
                                        "message": f"Error building section {i}: {sec_err}"})

            solid = Part.makeLoft(wires, True, ruled, closed_loft)

            feature = doc.addObject("Part::Feature", name)
            feature.Shape = solid
            doc.recompute()

            return json.dumps({
                "ok": True,
                "details": {"feature_name": feature.Name, "section_count": len(wires),
                             "axis": axis, "ruled": ruled},
                "message": (
                    f"Created '{feature.Name}' from {len(wires)} cross-sections "
                    f"along {axis}-axis ({'ruled' if ruled else 'smooth'} loft). "
                    f"This is a geometric proxy, not a scanned/clinical fit — "
                    f"validate against the actual limb model before fabrication."
                ),
            })
        except Exception as e:
            return json.dumps({"ok": False, "details": {},
                                "message": f"Error in cross_section_stack: {e}"})

    # ------------------------------------------------------------------
    def organic_loft(self, args: Dict[str, Any]) -> str:
        """Loft between existing named sketches/wires in the document, with
        optional ruled/ closed_loft behavior. Unlike cross_section_stack
        (which generates its own sections from measurements), this lofts
        through profiles you've already built (e.g. via sketch_operations).

        Args:
          doc_name:   FreeCAD document name
          profiles:   list of sketch/wire object names, in loft order
          name:       name for the resulting solid
          ruled, closed_loft: same as cross_section_stack
        """
        try:
            doc_name = args.get("doc_name")
            doc = FreeCAD.getDocument(doc_name) if doc_name else self.get_document()
            if not doc:
                return json.dumps({"ok": False, "details": {},
                                    "message": f"No document found (doc_name={doc_name!r})"})

            profile_names: List[str] = args.get("profiles") or []
            if len(profile_names) < 2:
                return json.dumps({"ok": False, "details": {},
                                    "message": "profiles must list at least 2 sketch/wire names"})

            name = args.get("name") or "OrganicLoft"
            ruled = bool(args.get("ruled", False))
            closed_loft = bool(args.get("closed_loft", False))

            wires = []
            for pname in profile_names:
                obj = self.get_object(pname, doc)
                if not obj:
                    return json.dumps({"ok": False, "details": {},
                                        "message": f"Profile object not found: {pname}"})
                shp = getattr(obj, "Shape", None)
                if shp is None or shp.Wires == []:
                    return json.dumps({"ok": False, "details": {},
                                        "message": f"Object {pname} has no usable wire"})
                wires.append(shp.Wires[0])

            solid = Part.makeLoft(wires, True, ruled, closed_loft)
            feature = doc.addObject("Part::Feature", name)
            feature.Shape = solid
            doc.recompute()

            return json.dumps({
                "ok": True,
                "details": {"feature_name": feature.Name, "profile_count": len(wires)},
                "message": f"Created '{feature.Name}' lofting through {len(wires)} profiles.",
            })
        except Exception as e:
            return json.dumps({"ok": False, "details": {},
                                "message": f"Error in organic_loft: {e}"})

    # ------------------------------------------------------------------
    def skin_solid(self, args: Dict[str, Any]) -> str:
        """Close a set of named cross-section wires into a solid skin.
        Thin wrapper over the same loft machinery as organic_loft, kept as
        a separate operation name to match the tool schema's vocabulary
        (skin vs loft terminology from surfacing workflows)."""
        return self.organic_loft(args)

    # ------------------------------------------------------------------
    def offset_surface(self, args: Dict[str, Any]) -> str:
        """Uniform-thickness offset (shell) of an existing shape — e.g. to
        turn a lofted socket outer surface into a walled shell of a given
        thickness.

        Args:
          doc_name, shape (object name to offset), offset (mm, default 2),
          name: name for the resulting object
        """
        try:
            doc_name = args.get("doc_name")
            doc = FreeCAD.getDocument(doc_name) if doc_name else self.get_document()
            if not doc:
                return json.dumps({"ok": False, "details": {},
                                    "message": f"No document found (doc_name={doc_name!r})"})

            object_name = args.get("shape") or args.get("object_name")
            if not object_name:
                return json.dumps({"ok": False, "details": {},
                                    "message": "Missing required argument: shape"})
            obj = self.get_object(object_name, doc)
            if not obj or not hasattr(obj, "Shape"):
                return json.dumps({"ok": False, "details": {},
                                    "message": f"Object not found or has no Shape: {object_name}"})

            offset = float(args.get("offset", 2.0))
            name = args.get("name") or f"{object_name}_Offset"

            new_shape = obj.Shape.makeOffsetShape(offset, 1e-3, fill=False)
            feature = doc.addObject("Part::Feature", name)
            feature.Shape = new_shape
            doc.recompute()

            return json.dumps({
                "ok": True,
                "details": {"feature_name": feature.Name, "offset_mm": offset},
                "message": f"Created offset surface '{feature.Name}' ({offset} mm).",
            })
        except Exception as e:
            return json.dumps({"ok": False, "details": {},
                                "message": f"Error in offset_surface: {e}"})

    # ------------------------------------------------------------------
    def organic_sweep(self, args: Dict[str, Any]) -> str:
        """Sweep a profile along a CURVED spine (path) — unlike
        cross_section_stack / organic_loft, which only stack sections along
        a straight x/y/z axis, this follows an arbitrary 3D curve (typically
        a spline sketch built with sketch_operations). This is the primary
        way to get true anatomical/biomorphic curvature rather than a
        straight-axis proxy.

        Args:
          doc_name:  FreeCAD document name
          spine:     name of an existing sketch/wire/edge object — the path
                     the profile follows. Give it a spline (not a straight
                     line) to actually get curvature.
          profiles:  list whose first entry is the profile to sweep (a
                     closed sketch/wire name); 'profile' is also accepted
                     as a single-name shortcut.
          solid:     close the result into a solid (default True)
          frenet:    False (default) = corrected frame, no unwanted twist
                     through inflection points ("normal correction" in the
                     tool description). True = strict Frenet frame, which
                     tracks the spine's own torsion exactly but can twist
                     unexpectedly on straighter stretches.
          name:      name for the resulting object
        """
        try:
            doc_name = args.get("doc_name")
            doc = FreeCAD.getDocument(doc_name) if doc_name else self.get_document()
            if not doc:
                return json.dumps({"ok": False, "details": {},
                                    "message": f"No document found (doc_name={doc_name!r})"})

            profile_names = args.get("profiles") or []
            profile_name = (profile_names[0] if profile_names
                             else args.get("profile") or args.get("profile_sketch"))
            spine_name = args.get("spine")
            if not profile_name:
                return json.dumps({"ok": False, "details": {},
                                    "message": "Missing required argument: profiles[0] (or 'profile') — "
                                               "the closed section to sweep"})
            if not spine_name:
                return json.dumps({"ok": False, "details": {},
                                    "message": "Missing required argument: spine — the path the profile follows"})

            profile_obj = self.get_object(profile_name, doc)
            if not profile_obj:
                return json.dumps({"ok": False, "details": {},
                                    "message": f"Profile object not found: {profile_name}"})
            spine_obj = self.get_object(spine_name, doc)
            if not spine_obj:
                return json.dumps({"ok": False, "details": {},
                                    "message": f"Spine object not found: {spine_name}"})

            solid = bool(args.get("solid", True))
            frenet = bool(args.get("frenet", False))
            name = args.get("name") or "OrganicSweep"

            sweep = doc.addObject("Part::Sweep", name)
            sweep.Sections = [profile_obj]
            sweep.Spine = spine_obj
            sweep.Solid = solid
            sweep.Frenet = frenet
            doc.recompute()

            if sweep.Shape is None or sweep.Shape.isNull():
                return json.dumps({
                    "ok": False, "details": {"feature_name": sweep.Name},
                    "message": "Sweep produced an empty/invalid shape. Common causes: the spine has sharp "
                               "kinks the profile can't follow, or the profile isn't roughly perpendicular "
                               "to the spine's start tangent. Try frenet=true, or check the spine curve.",
                })

            return json.dumps({
                "ok": True,
                "details": {"feature_name": sweep.Name, "spine": spine_name,
                             "profile": profile_name, "frenet": frenet},
                "message": (
                    f"Created '{sweep.Name}' sweeping '{profile_name}' along the curved spine '{spine_name}' "
                    f"({'Frenet' if frenet else 'corrected/non-twisting'} frame). "
                    f"This is a geometric proxy, not a scanned/clinical fit — validate before fabrication."
                ),
            })
        except Exception as e:
            return json.dumps({"ok": False, "details": {},
                                "message": f"Error in organic_sweep: {e}"})

    # ------------------------------------------------------------------
    def section_profiles(self, args: Dict[str, Any]) -> str:
        """Generate cross-section wires spaced by ARC LENGTH along a curved
        spine, each oriented perpendicular to the spine's tangent at that
        point — unlike cross_section_stack's sections, which sit at
        positions along one straight x/y/z axis. Feed the resulting object
        names, in order, into organic_loft's `profiles` argument to skin a
        solid that actually bends in 3D.

        Args:
          doc_name:       FreeCAD document name
          spine:          name of an existing sketch/wire/edge — the curve
                           to sample sections along (use a spline for real
                           curvature)
          n_sections:     how many sections to generate (default 8, min 2)
          shape:          circle | ellipse | rounded_rect | polygon |
                           smooth_polygon — section shape for generated
                           wires (default circle); ignored if profile_sketch
                           is given
          width, height, corner_radius, points: section size/shape params,
                           same meaning as in cross_section_stack; constant
                           across all generated sections in this pass
          profile_sketch: (optional) name of an existing closed sketch/wire
                           to clone and re-orient at each spine point
                           instead of generating a fresh analytic section
          name:           name prefix for generated objects (default
                           "Section" -> Section_0, Section_1, ...)

        Returns the ordered list of created object names.
        """
        try:
            doc_name = args.get("doc_name")
            doc = FreeCAD.getDocument(doc_name) if doc_name else self.get_document()
            if not doc:
                return json.dumps({"ok": False, "details": {},
                                    "message": f"No document found (doc_name={doc_name!r})"})

            spine_name = args.get("spine")
            if not spine_name:
                return json.dumps({"ok": False, "details": {}, "message": "Missing required argument: spine"})
            spine_obj = self.get_object(spine_name, doc)
            if not spine_obj or not hasattr(spine_obj, "Shape") or spine_obj.Shape.isNull():
                return json.dumps({"ok": False, "details": {},
                                    "message": f"Spine object not found or has no usable shape: {spine_name}"})

            edges = spine_obj.Shape.Edges
            if not edges:
                return json.dumps({"ok": False, "details": {},
                                    "message": f"Spine '{spine_name}' has no edges to sample"})
            # Single continuous edge assumed for this pass; a multi-edge
            # spine (several sketch segments) is combined into one Wire so
            # arc length is measured across the whole path, but per-edge
            # parametrization discontinuities at sharp corners aren't
            # smoothed — use a single spline edge for best results.
            edge = edges[0] if len(edges) == 1 else Part.Wire(edges)
            total_length = edge.Length
            if total_length <= 1e-6:
                return json.dumps({"ok": False, "details": {}, "message": f"Spine '{spine_name}' has zero length"})

            n_sections = int(args.get("n_sections", 8))
            if n_sections < 2:
                return json.dumps({"ok": False, "details": {}, "message": "n_sections must be >= 2"})

            profile_sketch_name = args.get("profile_sketch")
            if profile_sketch_name:
                proto_obj = self.get_object(profile_sketch_name, doc)
                if not proto_obj or not hasattr(proto_obj, "Shape") or not proto_obj.Shape.Wires:
                    return json.dumps({"ok": False, "details": {},
                                        "message": f"profile_sketch object not found or has no wire: {profile_sketch_name}"})
                proto_wire = proto_obj.Shape.Wires[0]
            else:
                shape_kind = args.get("shape", "circle")
                width = float(args.get("width", 10.0))
                height = float(args.get("height", 0.0)) or width
                corner_radius = float(args.get("corner_radius", 0.0))
                proto_wire = _section_wire(shape_kind, width, height, corner_radius, args.get("points"))

            name_prefix = args.get("name") or "Section"
            created: List[str] = []
            z_axis = FreeCAD.Vector(0, 0, 1)
            for i in range(n_sections):
                dist = (total_length * i) / (n_sections - 1)
                try:
                    param = edge.getParameterByLength(dist)
                except Exception:
                    # Fallback for curve types where getParameterByLength
                    # isn't supported: uniform split by parameter instead
                    # of arc length (less even, but never fails outright).
                    p0, p1 = edge.FirstParameter, edge.LastParameter
                    param = p0 + (p1 - p0) * (i / (n_sections - 1))

                point = edge.valueAt(param)
                try:
                    tangent = edge.tangentAt(param)
                except Exception:
                    tangent = FreeCAD.Vector(0, 0, 1)
                if tangent.Length < 1e-9:
                    tangent = FreeCAD.Vector(0, 0, 1)
                tangent.normalize()

                wire = proto_wire.copy()
                # proto_wire is flat in local XY with normal +Z; rotate so
                # that normal aligns with the spine tangent at this point.
                if tangent.cross(z_axis).Length < 1e-9:
                    rot = (FreeCAD.Rotation() if tangent.z > 0
                           else FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), 180))
                else:
                    rot = FreeCAD.Rotation(z_axis, tangent)
                wire.Placement = FreeCAD.Placement(point, rot)

                obj_name = f"{name_prefix}_{i}"
                feature = doc.addObject("Part::Feature", obj_name)
                feature.Shape = wire
                created.append(feature.Name)

            doc.recompute()

            return json.dumps({
                "ok": True,
                "details": {"section_names": created, "spine": spine_name, "n_sections": n_sections},
                "message": (
                    f"Created {len(created)} cross-sections along the curved spine '{spine_name}' "
                    f"(arc-length spaced, tangent-oriented). Pass these names, in order, as organic_loft's "
                    f"'profiles' to skin a solid that follows the spine's curvature."
                ),
            })
        except Exception as e:
            return json.dumps({"ok": False, "details": {},
                                "message": f"Error in section_profiles: {e}"})
