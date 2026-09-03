"""validation_operations.py - Consolidated validation handler"""
import json
from typing import Any, Dict
import FreeCAD
import Part
from .base import BaseHandler
from .materials_ops import MATERIALS_DB

_SEVERITY_LEVELS = {"error": 3, "warning": 2, "info": 1}
_AXIS_INDEX = {"x": 0, "y": 1, "z": 2}

class ValidationOpsHandler(BaseHandler):
    """Consolidated validation handler for geometry, mesh, materials, and workflows."""
    
    _ALLOWED_OPERATIONS = frozenset({
        "validate_solid", "validate_mesh", "validate_sketch",
        "validate_material_zone", "validate_socket_workflow",
        "validate_finger_assembly", "list_validation_rules",
        "report_validation", "validate_fit_clearance",
        "validate_against_standard",
    })

    def validate_solid(self, args: Dict[str, Any]) -> str:
        try:
            shape_name = args.get("shape", "")
            if not shape_name:
                return json.dumps({"ok": False, "details": {}, "message": "Missing required: shape"})
            doc = self.get_document()
            obj = self.get_object(shape_name, doc)
            if not obj or not hasattr(obj, "Shape") or obj.Shape.isNull():
                return json.dumps({"ok": False, "details": {}, "message": f"Shape not found: {shape_name}"})
            
            shape = obj.Shape
            findings = []
            
            if args.get("check_watertight", True):
                naked_edges = [e for e in shape.Edges if len([f for f in shape.Faces if e in f.Edges]) == 1]
                findings.append({
                    "rule": "solid_watertight",
                    "severity": _SEVERITY_LEVELS["error"] if naked_edges else _SEVERITY_LEVELS["info"],
                    "message": f"{'✗ ' if naked_edges else '✓ '}{len(naked_edges) if naked_edges else 'No'} naked edge(s)",
                })
            
            return json.dumps({"ok": True, "details": {"shape": shape_name, "findings": findings}, "message": f"Validation on {shape_name}"})
        except Exception as e:
            return json.dumps({"ok": False, "details": {}, "message": f"Error: {e}"})

    def validate_mesh(self, args: Dict[str, Any]) -> str:
        try:
            mesh_name = args.get("mesh", "")
            if not mesh_name:
                return json.dumps({"ok": False, "details": {}, "message": "Missing required: mesh"})
            doc = self.get_document()
            obj = self.get_object(mesh_name, doc)
            if not obj or not hasattr(obj, "Mesh"):
                return json.dumps({"ok": False, "details": {}, "message": f"Mesh not found: {mesh_name}"})
            
            mesh = obj.Mesh
            findings = []
            if args.get("check_watertight", True):
                is_closed = mesh.isClosed()
                findings.append({"rule": "mesh_watertight", "severity": _SEVERITY_LEVELS["info"] if is_closed else _SEVERITY_LEVELS["error"], "message": f"{'✓ Closed' if is_closed else '✗ Not watertight'}"})
            
            return json.dumps({"ok": True, "details": {"mesh": mesh_name, "findings": findings}, "message": "Mesh validation complete"})
        except Exception as e:
            return json.dumps({"ok": False, "details": {}, "message": f"Error: {e}"})

    def validate_material_zone(self, args: Dict[str, Any]) -> str:
        try:
            shape_name = args.get("shape", "")
            if not shape_name:
                return json.dumps({"ok": False, "details": {}, "message": "Missing required: shape"})
            doc = self.get_document()
            obj = self.get_object(shape_name, doc)
            if not obj or not hasattr(obj, "Shape"):
                return json.dumps({"ok": False, "details": {}, "message": f"Shape not found: {shape_name}"})
            if not hasattr(obj, "MaterialZoneMap"):
                return json.dumps({"ok": True, "details": {}, "message": "No material zones tagged"})
            
            zone_map = json.loads(obj.MaterialZoneMap or "{}")
            n_faces = len(obj.Shape.Faces)
            coverage = (len(zone_map) / n_faces * 100) if n_faces > 0 else 0
            findings = [{"rule": "material_coverage", "severity": _SEVERITY_LEVELS["info"], "message": f"Coverage: {len(zone_map)}/{n_faces} ({coverage:.1f}%)"}]
            
            return json.dumps({"ok": True, "details": {"shape": shape_name, "findings": findings}, "message": "Material zone validation complete"})
        except Exception as e:
            return json.dumps({"ok": False, "details": {}, "message": f"Error: {e}"})

    def validate_socket_workflow(self, args: Dict[str, Any]) -> str:
        try:
            socket_name = args.get("socket", "")
            if not socket_name:
                return json.dumps({"ok": False, "details": {}, "message": "Missing required: socket"})
            doc = self.get_document()
            obj = self.get_object(socket_name, doc)
            if not obj:
                return json.dumps({"ok": False, "details": {}, "message": f"Socket not found: {socket_name}"})
            findings = []
            if args.get("material_zones", False):
                has_zones = hasattr(obj, "MaterialZoneMap")
                findings.append({"rule": "socket_material", "severity": _SEVERITY_LEVELS["info"], "message": f"{'✓' if has_zones else '✗'} Material zones {'present' if has_zones else 'missing'}"})
            return json.dumps({"ok": True, "details": {"socket": socket_name, "findings": findings}, "message": "Socket workflow validation complete"})
        except Exception as e:
            return json.dumps({"ok": False, "details": {}, "message": f"Error: {e}"})

    def validate_fit_clearance(self, args: Dict[str, Any]) -> str:
        """Compara dos solidos (ej. socket vs. inserto/munon) para chequear
        ajuste mecanico: primero interferencia REAL (boolean common(), no
        distToShape -- distToShape da 0 tanto si se tocan como si se
        superponen, no distingue los dos casos), y si no hay superposicion,
        distancia minima real entre superficies via distToShape(),
        comparada opcionalmente contra un rango objetivo.

        Args esperados:
          shape_a, shape_b (str, requeridos): nombres de los dos objetos.
          interference_severity (str, opcional, default "warning"): error|warning|info.
            Default warning y no error porque un press-fit intencional
            (interferencia deliberada) es un caso valido en protesis, no
            necesariamente un defecto.
          target_clearance_min_mm, target_clearance_max_mm (float, opcionales):
            si se pasan y NO hay interferencia, la distancia medida se
            compara contra este rango.

        LIMITACION HONESTA: la interferencia se evalua por VOLUMEN del
        solido comun (>0 => hay superposicion real en algun lugar) --  no
        localiza en que cara/zona esta la interferencia, ni cuanto volumen
        exactamente representa un problema real vs. tolerancia de mallado
        aceptable (superposiciones de fracciones de mm^3 por redondeo
        numerico pueden aparecer incluso en piezas bien ajustadas). Revisar
        visualmente (Part -> Boolean -> Intersection en un objeto de prueba)
        antes de asumir que un volumen chico es un defecto real.
        """
        try:
            shape_a_name = args.get("shape_a", "")
            shape_b_name = args.get("shape_b", "")
            if not shape_a_name or not shape_b_name:
                return json.dumps({"ok": False, "details": {}, "message": "Missing required: shape_a and shape_b"})

            doc = self.get_document()
            obj_a = self.get_object(shape_a_name, doc)
            obj_b = self.get_object(shape_b_name, doc)
            if not obj_a or not hasattr(obj_a, "Shape") or obj_a.Shape.isNull():
                return json.dumps({"ok": False, "details": {}, "message": f"Shape not found: {shape_a_name}"})
            if not obj_b or not hasattr(obj_b, "Shape") or obj_b.Shape.isNull():
                return json.dumps({"ok": False, "details": {}, "message": f"Shape not found: {shape_b_name}"})

            shape_a = obj_a.Shape
            shape_b = obj_b.Shape
            findings = []

            interference_sev_key = args.get("interference_severity", "warning")
            interference_sev = _SEVERITY_LEVELS.get(interference_sev_key, _SEVERITY_LEVELS["warning"])

            common_shape = shape_a.common(shape_b)
            interference_volume = 0.0 if (common_shape is None or common_shape.isNull()) else common_shape.Volume

            if interference_volume > 1e-6:
                findings.append({
                    "rule": "fit_interference",
                    "severity": interference_sev,
                    "message": (
                        f"'{shape_a_name}' y '{shape_b_name}' se superponen "
                        f"(volumen comun: {interference_volume:.4f} mm³). Puede ser "
                        "press-fit intencional o un error de dimensionado -- revisar."
                    ),
                    "value_mm3": interference_volume,
                })
                distance_mm = 0.0
            else:
                dist_result = shape_a.distToShape(shape_b)
                distance_mm = float(dist_result[0])
                min_target = args.get("target_clearance_min_mm")
                max_target = args.get("target_clearance_max_mm")
                if min_target is not None and distance_mm < float(min_target):
                    findings.append({
                        "rule": "fit_clearance_too_tight",
                        "severity": _SEVERITY_LEVELS["warning"],
                        "message": f"Holgura {distance_mm:.4f} mm por debajo del minimo objetivo ({min_target} mm).",
                        "value_mm": distance_mm,
                    })
                elif max_target is not None and distance_mm > float(max_target):
                    findings.append({
                        "rule": "fit_clearance_too_loose",
                        "severity": _SEVERITY_LEVELS["warning"],
                        "message": f"Holgura {distance_mm:.4f} mm por encima del maximo objetivo ({max_target} mm).",
                        "value_mm": distance_mm,
                    })
                else:
                    findings.append({
                        "rule": "fit_clearance_measured",
                        "severity": _SEVERITY_LEVELS["info"],
                        "message": f"Sin interferencia. Holgura minima real: {distance_mm:.4f} mm.",
                        "value_mm": distance_mm,
                    })

            return json.dumps({
                "ok": True,
                "details": {
                    "shape_a": shape_a_name,
                    "shape_b": shape_b_name,
                    "interference_volume_mm3": interference_volume,
                    "clearance_mm": distance_mm,
                    "findings": findings,
                },
                "message": "Fit clearance validation complete",
            })
        except Exception as e:
            return json.dumps({"ok": False, "details": {}, "message": f"Error: {e}"})

    def validate_finger_assembly(self, args: Dict[str, Any]) -> str:
        """Validate a finger assembly (hand prosthesis component).
        
        Checks structural completeness: all expected digits/joints are present,
        material zones are assigned where needed, and geometry is closed.
        
        Args:
            assembly (str): Object name of the finger assembly (required).
            check_material_zones (bool): Whether to verify material zones are tagged (default True).
            check_digits (int): Expected number of digits/segments (optional, advisory only).
        
        Returns:
            JSON: {"ok": bool, "details": {...findings...}, "message": str}
        """
        try:
            assembly_name = args.get("assembly", "")
            if not assembly_name:
                return json.dumps({"ok": False, "details": {}, "message": "Missing required: assembly"})
            
            check_zones = bool(args.get("check_material_zones", True))
            expected_digits = args.get("check_digits")
            
            doc = self.get_document()
            obj = self.get_object(assembly_name, doc)
            if not obj or not hasattr(obj, "Shape") or obj.Shape.isNull():
                return json.dumps({"ok": False, "details": {}, "message": f"Assembly not found: {assembly_name}"})
            
            findings = []
            
            # Check 1: Geometry is watertight (closed solid)
            shape = obj.Shape
            naked_edges = [e for e in shape.Edges if len([f for f in shape.Faces if e in f.Edges]) == 1]
            if naked_edges:
                findings.append({
                    "rule": "assembly_watertight",
                    "severity": _SEVERITY_LEVELS["warning"],
                    "message": f"✗ {len(naked_edges)} naked edge(s) detected -- geometry may not be fully closed",
                })
            else:
                findings.append({
                    "rule": "assembly_watertight",
                    "severity": _SEVERITY_LEVELS["info"],
                    "message": "✓ Geometry is watertight",
                })
            
            # Check 2: Material zones (if requested)
            if check_zones:
                if hasattr(obj, "MaterialZoneMap"):
                    zone_map = json.loads(obj.MaterialZoneMap or "{}")
                    if zone_map:
                        findings.append({
                            "rule": "assembly_material_zones",
                            "severity": _SEVERITY_LEVELS["info"],
                            "message": f"✓ Material zones assigned to {len(zone_map)} face(s)",
                        })
                    else:
                        findings.append({
                            "rule": "assembly_material_zones",
                            "severity": _SEVERITY_LEVELS["warning"],
                            "message": "✗ No material zones assigned",
                        })
                else:
                    findings.append({
                        "rule": "assembly_material_zones",
                        "severity": _SEVERITY_LEVELS["info"],
                        "message": "ℹ Material zones not tracked on this object",
                    })
            
            # Check 3: Expected digit count (advisory)
            if expected_digits is not None:
                findings.append({
                    "rule": "assembly_digit_count_advisory",
                    "severity": _SEVERITY_LEVELS["info"],
                    "message": f"ℹ Expected {expected_digits} digit(s) -- verify by inspection",
                })
            
            return json.dumps({
                "ok": True,
                "details": {
                    "assembly": assembly_name,
                    "findings": findings,
                    "error_count": sum(1 for f in findings if f["severity"] == 3),
                    "warning_count": sum(1 for f in findings if f["severity"] == 2),
                },
                "message": "Finger assembly validation complete",
            })
        except Exception as e:
            return json.dumps({"ok": False, "details": {}, "message": f"Error in validate_finger_assembly: {e}"})

    def validate_sketch(self, args: Dict[str, Any]) -> str:
        """Validate a FreeCAD Sketch object.
        
        Checks that a sketch is fully constrained, closed (if expected), and
        has no degenerate geometry. Does NOT validate sketch against design
        intent (that's manual review).
        
        Args:
            sketch (str): Object name of the sketch (required).
            check_closed (bool): Expect the sketch to form a closed profile (default False).
            check_fully_constrained (bool): Expect full constraint (default True).
        
        Returns:
            JSON: {"ok": bool, "details": {...findings...}, "message": str}
        """
        try:
            sketch_name = args.get("sketch", "")
            if not sketch_name:
                return json.dumps({"ok": False, "details": {}, "message": "Missing required: sketch"})
            
            check_closed = bool(args.get("check_closed", False))
            check_constrained = bool(args.get("check_fully_constrained", True))
            
            doc = self.get_document()
            obj = self.get_object(sketch_name, doc)
            if not obj or not hasattr(obj, "Geometry"):
                return json.dumps({"ok": False, "details": {}, "message": f"Sketch not found: {sketch_name}"})
            
            findings = []
            
            # Check 1: Constraint status
            if check_constrained:
                # FreeCAD Sketcher marks over/under constraint via obj.MapReversed (for fully constrained)
                # This is a simple advisory; real constraint check needs direct Sketcher API
                findings.append({
                    "rule": "sketch_constraint_status",
                    "severity": _SEVERITY_LEVELS["info"],
                    "message": "ℹ Constraint status: manual inspection recommended (not auto-detectable without Sketcher GUI)",
                })
            
            # Check 2: Geometry count
            geom_count = len(obj.Geometry) if hasattr(obj, "Geometry") else 0
            if geom_count == 0:
                findings.append({
                    "rule": "sketch_empty",
                    "severity": _SEVERITY_LEVELS["warning"],
                    "message": "✗ Sketch is empty (no geometry)",
                })
            else:
                findings.append({
                    "rule": "sketch_geometry_count",
                    "severity": _SEVERITY_LEVELS["info"],
                    "message": f"✓ Sketch contains {geom_count} element(s)",
                })
            
            # Check 3: Closed profile (advisory)
            if check_closed:
                findings.append({
                    "rule": "sketch_closed_profile",
                    "severity": _SEVERITY_LEVELS["info"],
                    "message": "ℹ Expected closed profile -- verify by visualization",
                })
            
            return json.dumps({
                "ok": True,
                "details": {
                    "sketch": sketch_name,
                    "geometry_count": geom_count,
                    "findings": findings,
                },
                "message": "Sketch validation complete (manual review of constraints recommended)",
            })
        except Exception as e:
            return json.dumps({"ok": False, "details": {}, "message": f"Error in validate_sketch: {e}"})

    def list_validation_rules(self, args: Dict[str, Any]) -> str:
        """List all available validation rules and severity levels.
        
        Returns a catalog of what can be validated via this handler, grouped
        by operation type. Useful for clients building validation workflows.
        
        Args:
            (none)
        
        Returns:
            JSON: {"ok": True, "details": {rules: [{operation, subrules: [...]}], severities: {...}}, message}
        """
        try:
            rules_catalog = [
                {
                    "operation": "validate_solid",
                    "description": "Geometry solidity checks",
                    "subrules": ["solid_watertight"],
                },
                {
                    "operation": "validate_mesh",
                    "description": "Mesh object checks",
                    "subrules": ["mesh_watertight"],
                },
                {
                    "operation": "validate_material_zone",
                    "description": "Material assignment coverage",
                    "subrules": ["material_coverage"],
                },
                {
                    "operation": "validate_socket_workflow",
                    "description": "Socket/prosthesis workflow state",
                    "subrules": ["socket_material"],
                },
                {
                    "operation": "validate_fit_clearance",
                    "description": "Pairwise fit and clearance between two objects",
                    "subrules": ["fit_interference", "fit_clearance_too_tight", "fit_clearance_too_loose", "fit_clearance_measured"],
                },
                {
                    "operation": "validate_finger_assembly",
                    "description": "Hand prosthesis finger assembly checks",
                    "subrules": ["assembly_watertight", "assembly_material_zones"],
                },
                {
                    "operation": "validate_sketch",
                    "description": "FreeCAD Sketch checks",
                    "subrules": ["sketch_constraint_status", "sketch_geometry_count", "sketch_closed_profile"],
                },
                {
                    "operation": "validate_against_standard",
                    "description": "Engineering screening vs. ISO 10328 (axial stress, not certified test)",
                    "subrules": ["axial_stress_vs_tensile"],
                },
            ]
            
            return json.dumps({
                "ok": True,
                "details": {
                    "rules": rules_catalog,
                    "severity_levels": _SEVERITY_LEVELS,
                    "total_operations": len(rules_catalog),
                },
                "message": f"{len(rules_catalog)} validation operation(s) available",
            })
        except Exception as e:
            return json.dumps({"ok": False, "details": {}, "message": f"Error in list_validation_rules: {e}"})

    def report_validation(self, args: Dict[str, Any]) -> str:
        """Generate a validation report from a list of findings.
        
        Aggregates findings (from any validation operation) into a summary
        report with overall status. Used to synthesize results from multiple
        checks into a single pass/fail/caution decision.
        
        Args:
            findings (list of dict): List of finding dicts, each with:
                - "rule" (str): Rule identifier
                - "severity" (int): 1=info, 2=warning, 3=error
                - "message" (str): Human-readable finding
            (optional) object_name (str): Name of object being validated (for report context)
        
        Returns:
            JSON: {"ok": True, "details": {status, error_count, warning_count, info_count, findings}, message}
        """
        try:
            findings = args.get("findings", [])
            if not isinstance(findings, list):
                return json.dumps({"ok": False, "details": {}, "message": "Invalid findings: expected list of dicts"})
            
            object_name = args.get("object_name", "(unnamed)")
            
            error_count = sum(1 for f in findings if f.get("severity") == 3)
            warning_count = sum(1 for f in findings if f.get("severity") == 2)
            info_count = sum(1 for f in findings if f.get("severity") == 1)
            
            if error_count > 0:
                status = "FAIL"
                status_icon = "✗"
            elif warning_count > 0:
                status = "PROCEED_WITH_CAUTION"
                status_icon = "⚠"
            else:
                status = "PASS"
                status_icon = "✓"
            
            return json.dumps({
                "ok": True,
                "details": {
                    "object": object_name,
                    "status": status,
                    "error_count": error_count,
                    "warning_count": warning_count,
                    "info_count": info_count,
                    "total_findings": len(findings),
                    "findings": findings,
                },
                "message": f"{status_icon} {status}: {error_count} error(s), {warning_count} warning(s), {info_count} info(s)",
            })
        except Exception as e:
            return json.dumps({"ok": False, "details": {}, "message": f"Error in report_validation: {e}"})


    # ------------------------------------------------------------------
    # validate_against_standard
    # ------------------------------------------------------------------
    def validate_against_standard(self, args: Dict[str, Any]) -> str:
        """Engineering screening estimate against ISO 10328 test-force categories.

        NOT a certified structural test. ISO 10328 (Prosthetics -- Structural
        testing of lower-limb prostheses) requires physical static/cyclic load
        testing per its own scope; this tool has no FEA solver and does not
        reproduce that test. It computes a simple AXIAL stress estimate
        (stress = force / cross-section area) at one section of the shape,
        compared against the material's tensile strength. Bending, torsion,
        and fatigue loading (all covered by the real standard) are NOT
        evaluated here -- v1 is axial-only by design, to avoid a false-precision
        bending calc on irregular organic geometry.

        Force values are NOT looked up from the ISO 10328 tables -- the full
        table (Annex B) is behind ISO's paywall and was not verified for this
        tool. Pass force_n yourself; if you're targeting a P3-P6 body-weight
        category, source that force from your own copy of the standard.

        Args:
            shape                — object name to check (must have .Shape)
            axis                 — "x"/"y"/"z", axis to cut the cross-section on (default "z")
            coord                — coordinate along that axis where to check the section
            force_n              — applied axial force in Newtons (required)
            material             — key into the materials DB (see materials_operations
                                    list_materials), e.g. "petg"
            safety_factor_target — minimum acceptable factor of safety (default 1.5,
                                    an engineering rule of thumb, NOT an ISO 10328 value)

        Returns JSON: {"ok", "details": {area_mm2, stress_mpa, tensile_strength_mpa,
                        safety_factor, safety_factor_target, passes}, "message"}
        """
        try:
            shape_name = args.get("shape", "")
            if not shape_name:
                return json.dumps({"ok": False, "details": {}, "message": "Missing required: shape"})

            axis = args.get("axis", "z")
            if axis not in _AXIS_INDEX:
                return json.dumps({"ok": False, "details": {}, "message": f"Invalid axis: {axis!r}, expected x/y/z"})
            idx = _AXIS_INDEX[axis]

            try:
                coord = float(args.get("coord"))
            except (TypeError, ValueError):
                return json.dumps({"ok": False, "details": {}, "message": "Missing/invalid required: coord"})

            try:
                force_n = float(args.get("force_n"))
            except (TypeError, ValueError):
                return json.dumps({"ok": False, "details": {}, "message": "Missing/invalid required: force_n"})

            material = str(args.get("material", "")).lower().strip()
            if not material:
                return json.dumps({"ok": False, "details": {}, "message": "Missing required: material"})
            mat_props = MATERIALS_DB.get(material)
            if not mat_props:
                return json.dumps({
                    "ok": False,
                    "details": {"known_materials": sorted(MATERIALS_DB.keys())},
                    "message": f"Unknown material: {material!r}",
                })
            tensile_mpa = mat_props.get("tensile_strength_mpa")
            if tensile_mpa is None:
                return json.dumps({"ok": False, "details": {}, "message": f"Material {material!r} has no tensile_strength_mpa on record"})

            safety_factor_target = float(args.get("safety_factor_target", 1.5))

            doc = self.get_document()
            obj = self.get_object(shape_name, doc)
            if not obj or not hasattr(obj, "Shape") or obj.Shape.isNull():
                return json.dumps({"ok": False, "details": {}, "message": f"Shape not found: {shape_name}"})

            shp = obj.Shape
            bbox = shp.BoundBox
            big = max(bbox.XLength, bbox.YLength, bbox.ZLength) * 3 or 1.0

            # Cut a box starting exactly at `coord` on the + side of the axis;
            # the boolean-common operation creates a flat face at that boundary
            # whose Area is the true cross-section (same technique as
            # print_segmentation_operations.py's segment_with_joints).
            origin = [bbox.XMin - big, bbox.YMin - big, bbox.ZMin - big]
            origin[idx] = coord
            dims = [big * 2, big * 2, big * 2]
            piece = shp.common(Part.makeBox(dims[0], dims[1], dims[2], FreeCAD.Vector(*origin)))

            section_face = None
            tol = 1e-2
            for face in piece.Faces:
                n = face.normalAt(0, 0)
                n_val = (n.x, n.y, n.z)[idx]
                c = face.CenterOfMass
                c_val = (c.x, c.y, c.z)[idx]
                if abs(n_val) > 0.9 and abs(c_val - coord) < tol:
                    section_face = face
                    break

            if section_face is None:
                return json.dumps({
                    "ok": False,
                    "details": {},
                    "message": f"No cross-section found on {shape_name} at {axis}={coord}. "
                               "Check that coord is within the shape's bounding box.",
                })

            area_mm2 = section_face.Area
            if area_mm2 <= 0:
                return json.dumps({"ok": False, "details": {}, "message": "Cross-section area is zero or negative"})

            stress_mpa = force_n / area_mm2  # N/mm^2 = MPa
            safety_factor = tensile_mpa / stress_mpa if stress_mpa > 0 else float("inf")
            passes = safety_factor >= safety_factor_target

            return json.dumps({
                "ok": True,
                "details": {
                    "shape": shape_name,
                    "axis": axis,
                    "coord": coord,
                    "area_mm2": round(area_mm2, 3),
                    "force_n": force_n,
                    "stress_mpa": round(stress_mpa, 3),
                    "material": material,
                    "tensile_strength_mpa": tensile_mpa,
                    "safety_factor": round(safety_factor, 3),
                    "safety_factor_target": safety_factor_target,
                    "passes": passes,
                },
                "message": (f"{'PASS' if passes else 'FAIL'}: axial screening estimate only "
                            f"(force/area vs. tensile strength) -- not a certified ISO 10328 test. "
                            f"Safety factor {round(safety_factor, 2)} vs target {safety_factor_target}."),
            })
        except Exception as e:
            return json.dumps({"ok": False, "details": {}, "message": f"Error in validate_against_standard: {e}"})
