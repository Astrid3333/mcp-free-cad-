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
        "organic_sweep", "section_profiles", "hollow_cross_section_stack",
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
    def hollow_cross_section_stack(self, args: Dict[str, Any]) -> str:
        """Build a hollow anatomical shell (e.g. a prosthetic socket wall) in
        one call, by lofting an OUTER and an INNER stack of cross-sections
        and subtracting inner from outer. This is the boolean-based
        replacement for the old offset_surface + face_index approach: a
        smooth (non-ruled) loft in OCC produces a single continuous lateral
        face, so there is no "face of section N" to apply a per-station
        offset to after the fact. Instead, wall thickness must already be
        baked into the INNER profile's width/height before this is called
        (see munon_a_secciones.py: construir_secciones() does exactly this,
        contracting ap/ml per section by 2x the landmark's wall thickness).

        This does NOT compute thickness for you — sections_inner must
        already be the correctly-shrunk profiles. This method only
        orchestrates: loft outer, loft inner, cut.

        Args:
          doc_name:       FreeCAD document name
          sections_outer: list of section dicts (see cross_section_stack) —
                           the real/measured outer profile.
          sections_inner: list of section dicts, same length/order as
                           sections_outer, already shrunk by wall thickness.
          axis:           "x" | "y" | "z" — same for both stacks
          ruled:           same as cross_section_stack (applies to both lofts)
          closed_loft:     same as cross_section_stack (applies to both lofts)
          outer_name:      name for the outer loft solid (default "Socket_Outer")
          inner_name:      name for the inner loft solid (default "Socket_Inner")
          wall_name:       name for the final cut (hollow wall) solid (default "Socket_Wall")
          keep_outer_visible: if True (default), re-show Socket_Outer after the
                           cut so it stays available as a proxy of the real limb
                           for a later contact_pressure_operations QA pass —
                           cut_objects hides source objects by default.

        Returns JSON with the created wall solid's name, or an error at
        whichever stage failed (outer loft / inner loft / cut) so you know
        which one to look at.
        """
        try:
            doc_name = args.get("doc_name")
            doc = FreeCAD.getDocument(doc_name) if doc_name else self.get_document()
            if not doc:
                return json.dumps({"ok": False, "details": {},
                                    "message": f"No document found (doc_name={doc_name!r})"})

            sections_outer = args.get("sections_outer") or []
            sections_inner = args.get("sections_inner") or []
            if len(sections_outer) < 2 or len(sections_inner) < 2:
                return json.dumps({"ok": False, "details": {},
                                    "message": "sections_outer and sections_inner must each have at least 2 entries"})
            if len(sections_outer) != len(sections_inner):
                return json.dumps({"ok": False, "details": {
                                        "outer_count": len(sections_outer),
                                        "inner_count": len(sections_inner)},
                                    "message": "sections_outer and sections_inner must have the same length "
                                               "(one inner profile per outer section) -- mismatched counts usually "
                                               "mean a section was dropped upstream (e.g. ESPESOR_MINIMO_MM raised "
                                               "in construir_secciones before it got here)."})

            axis = str(args.get("axis", "z"))
            ruled = bool(args.get("ruled", False))
            closed_loft = bool(args.get("closed_loft", False))
            outer_name = args.get("outer_name") or "Socket_Outer"
            inner_name = args.get("inner_name") or "Socket_Inner"
            wall_name = args.get("wall_name") or "Socket_Wall"
            keep_outer_visible = args.get("keep_outer_visible", True)

            # Sort both stacks by position BEFORE anything else touches them.
            # cross_section_stack/makeLoft connects wires in list order, not
            # spatial order -- if the caller passes sections descending
            # (e.g. distal-to-proximal measurement order, which is common
            # and perfectly valid), leaving them unsorted here produces a
            # non-monotonic position sequence once the end-margin sections
            # get spliced in below (margins are derived from the sorted
            # extremes but were being inserted around the *unsorted* list),
            # which folds the loft back on itself at both ends instead of
            # producing a clean tube. Sorting outer the same way keeps it
            # paired correctly with inner for the later cut.
            sections_outer = sorted(sections_outer, key=lambda s: float(s.get("position", 0.0)))
            sections_inner = sorted(sections_inner, key=lambda s: float(s.get("position", 0.0)))

            # Extend the inner stack a few mm past the outer's first/last
            # position so the cut fully penetrates at both ends. Without
            # this, inner's end caps sit in the exact same plane as outer's
            # end caps -- a coincident-face degenerate boolean input that
            # produces a broken/non-watertight wall (confirmed via
            # distToShape: contact points land exactly at the two end
            # planes, not a mid-height crossing). The margin sections reuse
            # the nearest real inner section's shape/dims verbatim; they
            # exist only to punch through cleanly, not to represent real
            # anatomy there. Skipped for closed_loft, which has no flat end
            # caps to begin with.
            sections_inner_for_loft = sections_inner
            if not closed_loft:
                END_MARGIN_MM = 3.0
                positions_outer = [float(s.get("position", 0.0)) for s in sections_outer]
                outer_lo, outer_hi = min(positions_outer), max(positions_outer)

                # sections_inner is already sorted ascending by position at
                # this point, so its first/last entries ARE the extremes --
                # safe to splice margins directly onto it without re-sorting.
                margin_lo = dict(sections_inner[0])
                margin_lo["position"] = outer_lo - END_MARGIN_MM
                margin_hi = dict(sections_inner[-1])
                margin_hi["position"] = outer_hi + END_MARGIN_MM

                sections_inner_for_loft = [margin_lo] + sections_inner + [margin_hi]

            outer_result_raw = self.cross_section_stack({
                "doc_name": doc_name, "sections": sections_outer, "axis": axis,
                "name": outer_name, "ruled": ruled, "closed_loft": closed_loft,
            })
            outer_result = json.loads(outer_result_raw)
            if not outer_result.get("ok"):
                return json.dumps({"ok": False, "details": {"stage": "outer_loft", "result": outer_result},
                                    "message": f"Outer loft failed: {outer_result.get('message')}"})

            inner_result_raw = self.cross_section_stack({
                "doc_name": doc_name, "sections": sections_inner_for_loft, "axis": axis,
                "name": inner_name, "ruled": ruled, "closed_loft": closed_loft,
            })
            inner_result = json.loads(inner_result_raw)
            if not inner_result.get("ok"):
                return json.dumps({"ok": False, "details": {"stage": "inner_loft", "result": inner_result},
                                    "message": f"Inner loft failed: {inner_result.get('message')}. "
                                               f"Outer loft '{outer_name}' was already created and left in the "
                                               f"document -- check it for a plausible cause (e.g. an inner "
                                               f"profile degenerate/self-intersecting)."})

            if self.server is None or not hasattr(self.server, "boolean_ops"):
                return json.dumps({"ok": False, "details": {"stage": "cut",
                                        "outer_name": outer_name, "inner_name": inner_name},
                                    "message": "No boolean_ops handler available on self.server -- "
                                               "both lofts were created ("
                                               f"{outer_name}, {inner_name}) but the cut step could not run. "
                                               "Run boolean_operations -> cut_objects manually with "
                                               f"base={outer_name!r}, tools=[{inner_name!r}]."})

            cut_result = self.server.boolean_ops.cut_objects({
                "base": outer_name, "tools": [inner_name], "name": wall_name,
            })
            # cut_objects (boolean_ops.py) returns a plain string, not JSON --
            # both success and error paths are prose, so check for the known
            # failure prefixes rather than trying to parse it as JSON.
            cut_failed = (
                cut_result.startswith("Error")
                or cut_result.startswith("Need ")
                or "not found" in cut_result
                or "empty/invalid shape" in cut_result
            )
            if cut_failed:
                return json.dumps({"ok": False, "details": {"stage": "cut", "cut_result": cut_result,
                                        "outer_name": outer_name, "inner_name": inner_name},
                                    "message": f"Cut failed: {cut_result}. Both lofts were created "
                                               f"({outer_name}, {inner_name}) -- inspect them for a degenerate "
                                               f"or self-intersecting inner profile before retrying the cut."})

            if keep_outer_visible:
                outer_obj = self.get_object(outer_name, doc)
                if outer_obj is not None:
                    outer_obj.Visibility = True

            return json.dumps({
                "ok": True,
                "details": {"outer_name": outer_name, "inner_name": inner_name, "wall_name": wall_name,
                             "section_count": len(sections_outer), "axis": axis, "ruled": ruled,
                             "outer_kept_visible": bool(keep_outer_visible)},
                "message": (
                    f"Created hollow wall '{wall_name}' = {outer_name} cut {inner_name}, from "
                    f"{len(sections_outer)} paired outer/inner cross-sections along {axis}-axis. "
                    f"Wall thickness came entirely from the inner profile shrink baked in upstream -- "
                    f"this method did not compute or validate thickness itself. This is a geometric "
                    f"proxy, not a scanned/clinical fit -- validate against the actual limb model, "
                    f"and consider contact_pressure_operations against '{outer_name}' as a QA pass "
                    f"before fabrication."
                ),
            })
        except Exception as e:
            return json.dumps({"ok": False, "details": {},
                                "message": f"Error in hollow_cross_section_stack: {e}"})

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
