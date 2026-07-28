# Base handler class for FreeCAD MCP operations

import os
import FreeCAD
import time
from typing import Dict, Any, Optional, Callable

# Conditional GUI import (not available in console mode)
if FreeCAD.GuiUp:
    import FreeCADGui
else:
    FreeCADGui = None


class BaseHandler:
    """Base class for all FreeCAD operation handlers.

    Provides common utilities and document access patterns.
    """

    def __init__(self, server=None, log_operation: Optional[Callable] = None, capture_state: Optional[Callable] = None):
        """Initialize handler with optional reference to server.

        Args:
            server: Reference to FreeCADSocketServer for accessing shared resources
                   like selector, gui_task_queue, etc.
            log_operation: Debug logging function (optional)
            capture_state: State capture function (optional)
        """
        self.server = server
        self._log_operation = log_operation or self._noop_log
        self._capture_state = capture_state or self._noop_capture

    def _noop_log(self, *args, **kwargs):
        """No-op fallback if debug not available"""
        pass

    def _noop_capture(self):
        """No-op fallback if debug not available"""
        return {}

    @property
    def selector(self):
        """Access the selection manager from the server."""
        return self.server.selector if self.server else None

    def run_on_gui_thread(self, task_fn, timeout=30.0) -> str:
        """Run a callable on the Qt GUI thread via the server's tagged queue.

        Delegates to server._run_on_gui_thread which handles request ID
        tagging and stale response draining.

        Returns JSON string with result or error.
        """
        if self.server and hasattr(self.server, '_run_on_gui_thread'):
            return self.server._run_on_gui_thread(task_fn, timeout)
        # Fallback: run directly (no server or console mode)
        try:
            result = task_fn()
            return result
        except Exception as e:
            return f"Error: {e}"

    def log_and_return(self, operation: str, parameters: Dict, result: str = None, error: Exception = None, duration: float = None):
        """Helper to log operation and return result/error.

        Args:
            operation: Operation name
            parameters: Operation parameters
            result: Success result string
            error: Error exception if failed
            duration: Operation duration in seconds

        Returns:
            result string if success, error string if failed
        """
        self._log_operation(
            operation=operation,
            parameters=parameters,
            result=result,
            error=error,
            duration=duration
        )

        if error:
            # Also capture state on errors for debugging
            state = self._capture_state()
            self._log_operation(
                operation=f"{operation}_error_state",
                parameters=parameters,
                result=state
            )
            return f"Error in {operation}: {error}"
        return result

    def get_document(self) -> FreeCAD.Document:
        """Return the active FreeCAD document, or None if none is open.

        Callers that need a document must check the return value and return
        an error — never auto-create here.  Auto-creation calls
        FreeCAD.newDocument() which triggers NSWindow init on macOS and must
        only be done via view_control(operation='create_document').
        """
        return FreeCAD.ActiveDocument

    def get_object(self, object_name: str, doc: FreeCAD.Document = None):
        """Get an object by internal name or label from the document.

        Tries internal name first (fast, exact), then falls back to label
        search so callers can pass user-visible labels like "LeftTab".

        FreeCAD does NOT enforce uniqueness on Label — multiple objects can
        share the same Label, only Name is guaranteed unique.  When a label
        lookup hits multiple objects we REFUSE to guess which one was meant,
        because the previous "first match wins" behavior could silently
        perform destructive operations (move/rotate/cut) on the wrong solid.
        Callers should either pass the unique internal Name to disambiguate,
        or rename one of the objects so labels are unique.

        Args:
            object_name: Internal name or Label of the object to find
            doc: Document to search in (uses active document if not specified)

        Returns:
            FreeCAD object, or None if not found.

        Raises:
            ValueError: if `object_name` matches multiple objects by Label.
                The error message lists every candidate's internal Name so
                the caller can retry with an unambiguous identifier.  The
                surrounding handler try/except converts this into a clear
                error response for the MCP client.
        """
        if doc is None:
            doc = FreeCAD.ActiveDocument
        if doc is None:
            return None
        obj = doc.getObject(object_name)
        if obj is not None:
            return obj
        # Fall back to label search
        results = doc.getObjectsByLabel(object_name)
        if not results:
            return None
        if len(results) > 1:
            names = [getattr(o, "Name", "?") for o in results]
            raise ValueError(
                f"Ambiguous label {object_name!r}: {len(results)} objects "
                f"share this label ({', '.join(names)}). "
                f"Use the internal Name to disambiguate."
            )
        return results[0]

    def recompute(self, doc: FreeCAD.Document = None):
        """Recompute the document.

        Args:
            doc: Document to recompute (uses active document if not specified)
        """
        if doc is None:
            doc = FreeCAD.ActiveDocument
        if doc:
            doc.recompute()

    def find_font(self, font_file: str = '') -> str:
        """Find a usable .ttf font file, trying the given path then common system locations.

        Returns the resolved path, or '' if nothing is found.
        """
        if font_file and os.path.exists(font_file):
            return font_file
        # FreeCAD bundles fonts in its resource directory
        try:
            fc_fonts = os.path.join(FreeCAD.getResourceDir(), 'fonts')
            for name in ('LiberationSans-Regular.ttf', 'DejaVuSans.ttf'):
                path = os.path.join(fc_fonts, name)
                if os.path.exists(path):
                    return path
        except Exception:
            pass
        candidates = [
            '/System/Library/Fonts/Supplemental/Arial.ttf',  # macOS
            '/Library/Fonts/Arial.ttf',
            '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',  # Linux
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
            '/usr/share/fonts/TTF/DejaVuSans.ttf',
            'C:/Windows/Fonts/arial.ttf',  # Windows
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        return ''

    def save_before_risky_op(self, doc: FreeCAD.Document = None):
        """Auto-save document before a potentially crashy operation.

        Boolean operations on large compounds can crash FreeCAD.
        Saving first ensures the user doesn't lose work.
        """
        if doc is None:
            doc = FreeCAD.ActiveDocument
        try:
            if doc and getattr(doc, 'FileName', ''):
                doc.save()
        except Exception:
            pass  # non-fatal

    def check_complexity(self, objs, max_solids=500, max_faces=10000):
        """Check if objects are too complex for boolean operations.

        Returns a warning string if complexity is high, or None if OK.
        """
        total_solids = 0
        total_faces = 0
        for obj in objs:
            s = getattr(obj, 'Shape', None)
            if s is None:
                continue
            total_solids += len(s.Solids)
            total_faces += len(s.Faces)
        if total_solids > max_solids or total_faces > max_faces:
            return (f"WARNING: High complexity ({total_solids} solids, "
                    f"{total_faces} faces). Boolean operations on geometry "
                    f"this large may crash FreeCAD. Consider simplifying first.")
        return None

    def feed_to_mm_min(self, value):
        """Convert a FreeCAD feed property to a numeric value in mm/min.

        CAM feed/rapid properties (HorizFeed, VertFeed, ...) are App::PropertySpeed
        velocity Quantities whose base unit is mm/s. Reading the raw property and
        string-splitting it is fragile — the formatted string's unit depends on the
        user's unit schema (mm/s, m/s, ...), so a fixed ``* 60`` is wrong under any
        non-default schema. ``Quantity.getValueAs('mm/min')`` is exact regardless.

        Returns the mm/min value as a float, or None if it can't be interpreted.
        """
        if value is None:
            return None
        try:
            q = value if hasattr(value, 'getValueAs') else FreeCAD.Units.Quantity(value)
            return float(q.getValueAs('mm/min'))
        except Exception:
            # Last-resort fallback: assume the raw magnitude is already in mm/s.
            try:
                return float(str(value).split()[0]) * 60.0
            except Exception:
                return None

    def find_body(self, doc: FreeCAD.Document = None):
        """Find a PartDesign Body in the document.

        Args:
            doc: Document to search (uses active document if not specified)

        Returns:
            First PartDesign::Body found, or None
        """
        if doc is None:
            doc = FreeCAD.ActiveDocument
        if doc is None:
            return None
        for obj in doc.Objects:
            if obj.TypeId == "PartDesign::Body":
                return obj
        return None

    def find_body_for_object(self, obj, doc: FreeCAD.Document = None):
        """Find the PartDesign Body containing an object.

        Args:
            obj: Object to find the body for
            doc: Document to search (uses active document if not specified)

        Returns:
            PartDesign::Body containing the object, or None
        """
        if doc is None:
            doc = FreeCAD.ActiveDocument
        if doc is None:
            return None
        for body in doc.Objects:
            if body.TypeId == "PartDesign::Body" and obj in body.Group:
                return body
        return None

    # -----------------------------------------------------------------
    # Sketch wire diagnosis helpers
    # -----------------------------------------------------------------

    def _find_geo_for_point(self, sketch, vertex, tolerance: float = 0.5):
        """Find the geometry endpoint nearest to an open vertex.

        Iterates non-construction sketch geometry and compares each
        start/end point to *vertex* (a FreeCAD.Vector).

        Returns:
            (geo_id, pos_id, dist) tuple, or None if nothing within
            *tolerance* mm.  pos_id: 1=start, 2=end.
        """
        best = None
        best_dist = tolerance
        for i in range(sketch.GeometryCount):
            try:
                if sketch.getConstruction(i):
                    continue
                geo = sketch.Geometry[i]
                if not hasattr(geo, 'StartPoint') or not hasattr(geo, 'EndPoint'):
                    continue
                for pt, pos_id in ((geo.StartPoint, 1), (geo.EndPoint, 2)):
                    d = FreeCAD.Vector(vertex.x - pt.x,
                                      vertex.y - pt.y, 0).Length
                    if d < best_dist:
                        best_dist = d
                        best = (i, pos_id, d)
            except Exception:
                continue
        return best

    def _diagnose_open_wires(self, sketch) -> str:
        """Return an actionable diagnosis for open wire / unclosed profile.

        Combines three FreeCAD APIs:
        1. ``getOpenVertices()``  — exact XY of every dangling endpoint
        2. ``_find_geo_for_point()`` — maps each dangling point back to
           its geo_id + pos_id so the user knows which geometry to fix
        3. ``detectMissingPointOnPointConstraints()`` +
           ``getMissingPointOnPointConstraints()`` — generates the exact
           Coincident constraints needed to close the gaps

        Returns an empty string when no issues are detected.
        """
        issues = []
        open_verts = []

        # --- Step 1: find dangling endpoints ---
        try:
            open_verts = sketch.getOpenVertices()
        except Exception as exc:
            issues.append(f"  (getOpenVertices unavailable: {exc})")

        if open_verts:
            pos_names = {1: "start", 2: "end", 3: "center"}
            issues.append(f"{len(open_verts)} open endpoint(s) found:")
            for v in open_verts:
                match = self._find_geo_for_point(sketch, v)
                if match:
                    gid, pid, dist = match
                    gap = f" (gap {dist:.5f} mm)" if dist > 1e-6 else ""
                    pname = pos_names.get(pid, str(pid))
                    issues.append(
                        f"  • geo_id={gid} {pname}-point at "
                        f"({v.x:.4f}, {v.y:.4f}){gap}"
                    )
                else:
                    issues.append(
                        f"  • Dangling point at ({v.x:.4f}, {v.y:.4f})"
                        " — no matching geometry found within 0.5 mm"
                    )

        # --- Step 2: suggest Coincident constraints to close the gaps ---
        try:
            missing_count = sketch.detectMissingPointOnPointConstraints(
                precision=0.1, includeconstruction=False
            )
            if missing_count > 0:
                pairs = sketch.getMissingPointOnPointConstraints()
                issues.append(f"\n{missing_count} suggested fix(es):")
                for c in pairs:
                    issues.append(
                        f"  sketch_operations(operation=\"add_constraint\","
                        f" constraint_type=\"Coincident\","
                        f" sketch_name=\"{sketch.Name}\","
                        f" geo_id1={c.First}, pos_id1={c.FirstPos},"
                        f" geo_id2={c.Second}, pos_id2={c.SecondPos})"
                    )
        except Exception:
            # Graceful degradation for older FC builds
            pass

        return "\n".join(issues)

    # Prefixes considered outside any user-writable area on common platforms.
    # Allowlist approach: only home dir, /tmp, and platform-specific temp dirs
    # are permitted for file I/O operations.
    @staticmethod
    def _validate_file_path(path: str) -> "Optional[str]":
        """Return an error string if path is outside safe user-writable locations, else None.

        Safe locations: user home directory, /tmp/, /var/folders/ (macOS),
        /var/tmp/, and /Volumes/ (macOS external/network drives).
        On Windows: home dir and the system temp directory.
        """
        import sys as _sys
        if not path:
            return "file path is required"
        resolved = os.path.realpath(os.path.abspath(os.path.expanduser(path)))
        home = os.path.realpath(os.path.expanduser("~"))

        safe: list = [home]
        if _sys.platform == "win32":
            import tempfile as _tmp
            safe.append(os.path.realpath(_tmp.gettempdir()))
        else:
            # Resolve each prefix so symlinks (e.g. /tmp -> /private/tmp on macOS) match.
            safe += [os.path.realpath(p) for p in ("/tmp", "/var/folders", "/var/tmp", "/Volumes")]

        if any(resolved == s or resolved.startswith(s + os.sep) or resolved.startswith(s + "/")
               for s in safe):
            return None
        return (
            f"Path is outside allowed directories (home dir, /tmp, /Volumes). "
            f"Resolved path: {resolved}"
        )

    def create_body_if_needed(self, doc: FreeCAD.Document = None):
        """Create a PartDesign Body if one doesn't exist.

        If no document exists, creates one via GUI thread to avoid GIL deadlock.

        Args:
            doc: Document to create body in (uses active document if not specified)

        Returns:
            Existing or newly created PartDesign::Body
        """
        if doc is None:
            doc = FreeCAD.ActiveDocument
        if doc is None:
            return None

        body = self.find_body(doc)
        if not body:
            body = doc.addObject("PartDesign::Body", "Body")
            doc.recompute()
        return body

    # -----------------------------------------------------------------
    # Assembly-chain anchoring
    # -----------------------------------------------------------------
    # Lets pieces of the prosthetic chain (socket -> pylon -> terminal
    # device, etc.) place themselves relative to the piece that precedes
    # them logically, instead of always defaulting to the document origin.
    #
    # Anchors are PartDesign::CoordinateSystem objects attached (via
    # Support/MapMode) to a face of the "output" piece of a role. New
    # objects that continue the chain copy that anchor's resolved global
    # Placement (optionally offset) instead of starting at (0,0,0).
    #
    # NOTE: this is a placement *snapshot*, not a live parametric link.
    # Most boolean-result Part::Feature objects in this pipeline don't
    # support Part::AttachExtension in this FreeCAD build (confirmed on
    # 0.21.2 -- addExtension raises "not a python addable version"), so
    # re-running register_output_anchor() after the upstream piece
    # changes is what keeps downstream placements in sync; it is not
    # automatic. Objects that DO support native attachment (sketches,
    # PartDesign datum features, Part primitives) can still set
    # obj.Support / obj.MapMode directly for a live link if needed.

    ANCHOR_PREFIX = "LCS_"
    ANCHOR_SUFFIX = "_out"

    # Standard chain roles for prosthetic assemblies, grouped by mechanical
    # part -- not by anatomical section. A part is something that gets
    # fabricated, purchased, or swapped as its own unit; a section (e.g.
    # proximal/mid/distal circumference) is an internal detail of how a
    # single part like the socket is built (see organic_operations'
    # cross_section_stack) and is NOT its own role here.
    #
    # Handlers should register/consume these by constant, not by typing
    # the string directly, so a rename only touches this list.
    ROLE_SOCKET = "socket"
    ROLE_KNEE_MECHANISM = "knee_mechanism"
    ROLE_LIMB_JOINT = "limb_joint"
    ROLE_PYLON = "pylon"
    ROLE_QUICK_CONNECT = "quick_connect"
    ROLE_TERMINAL_DEVICE = "terminal_device"

    # Canonical order for a transradial/transtibial chain. Not enforced by
    # register_output_anchor/place_in_chain (those work with any role
    # string), but handlers and callers can use this to validate a chain
    # is being built in a sane order, or to walk "what comes next".
    ASSEMBLY_CHAIN_ROLES = (
        ROLE_SOCKET,
        ROLE_KNEE_MECHANISM,
        ROLE_PYLON,
        ROLE_QUICK_CONNECT,
        ROLE_TERMINAL_DEVICE,
    )

    def _anchor_name(self, role: str) -> str:
        """Internal name of the output anchor for a given assembly role."""
        return f"{self.ANCHOR_PREFIX}{role}{self.ANCHOR_SUFFIX}"

    def register_output_anchor(self, obj, role: str, face_name: str,
                                mode: str = "FlatFace", doc: FreeCAD.Document = None):
        """Mark obj as the current end of assembly role `role`, and (re)create
        the LCS anchor on its `face_name` that later pieces will attach to.

        Args:
            obj: object whose face defines where the next piece should start
            role: chain role name, e.g. 'socket', 'pylon', 'terminal_device'
            face_name: face on obj to attach the anchor to (e.g. 'Face2')
            mode: MapMode for the anchor, default 'FlatFace' (planar faces only;
                  use 'Concentric' for cylindrical faces, etc.)
            doc: document (uses obj.Document / ActiveDocument if not given)

        Returns:
            The anchor object (PartDesign::CoordinateSystem) on success,
            or None if the attachment failed (e.g. non-planar face with
            FlatFace mode) -- check anchor.State for 'Invalid' if you need
            the reason before deciding how to recover.
        """
        if obj is None:
            return None
        if doc is None:
            doc = obj.Document if hasattr(obj, "Document") else FreeCAD.ActiveDocument
        if doc is None:
            return None

        if not hasattr(obj, "AssemblyRole"):
            obj.addProperty("App::PropertyString", "AssemblyRole", "Assembly",
                             "Role of this object in the prosthetic assembly chain")
        obj.AssemblyRole = role

        anchor_name = self._anchor_name(role)
        anchor = doc.getObject(anchor_name)
        if anchor is None:
            anchor = doc.addObject("PartDesign::CoordinateSystem", anchor_name)

        # Support and MapMode are set with a recompute in between -- setting
        # both before any recompute has been observed to raise "AttachExtension
        # cannot find placement property" against this FreeCAD build/bridge
        # (0.21.2), even though each step works fine in isolation.
        anchor.AttachmentSupport = [(obj, face_name)]
        doc.recompute()
        anchor.MapMode = mode
        doc.recompute()

        if "Invalid" in anchor.State:
            return None
        return anchor

    def find_anchor_for_role(self, role: str, doc: FreeCAD.Document = None):
        """Return the output LCS anchor registered for `role`, or None if
        no piece has registered that role yet in this document."""
        if doc is None:
            doc = FreeCAD.ActiveDocument
        if doc is None:
            return None
        return doc.getObject(self._anchor_name(role))

    def place_in_chain(self, new_obj, expected_role: str, offset=None,
                        doc: FreeCAD.Document = None):
        """Place `new_obj` at the output anchor of `expected_role`, instead of
        leaving it at the document origin.

        This is a one-time placement snapshot (see class-level note above),
        so call it right after creating new_obj and before returning from
        the handler -- not as a persistent constraint.

        Args:
            new_obj: freshly created object to position
            expected_role: role whose anchor to attach to, e.g. 'socket'
            offset: optional (dx, dy, dz) tuple applied on top of the
                    anchor, expressed in the anchor's local frame
            doc: document (uses new_obj.Document / ActiveDocument if not given)

        Returns:
            None on success, or an error string explaining why placement
            could not be resolved (e.g. no anchor registered yet for that
            role). Callers should surface this to the MCP client rather
            than silently leaving new_obj at the origin.
        """
        if new_obj is None:
            return "new_obj is None"
        if doc is None:
            doc = new_obj.Document if hasattr(new_obj, "Document") else FreeCAD.ActiveDocument

        anchor = self.find_anchor_for_role(expected_role, doc)
        if anchor is None:
            return (f"No output anchor registered for role '{expected_role}'. "
                     f"Call register_output_anchor() on the preceding piece "
                     f"first, or place this piece explicitly if it is the "
                     f"first in the chain.")

        placement = anchor.Placement
        if offset:
            placement = placement.multiply(
                FreeCAD.Placement(FreeCAD.Vector(*offset), FreeCAD.Rotation())
            )
        new_obj.Placement = placement
        return None

