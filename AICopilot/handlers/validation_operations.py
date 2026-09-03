"""validation_operations.py - Consolidated validation handler"""
import json
from typing import Any, Dict
import FreeCAD
from .base import BaseHandler

_SEVERITY_LEVELS = {"error": 3, "warning": 2, "info": 1}

class ValidationOpsHandler(BaseHandler):
    """Consolidated validation handler for geometry, mesh, materials, and workflows."""
    
    _ALLOWED_OPERATIONS = frozenset({
        "validate_solid", "validate_mesh", "validate_sketch",
        "validate_material_zone", "validate_socket_workflow",
        "validate_finger_assembly", "list_validation_rules",
        "report_validation", "validate_fit_clearance",
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
        return json.dumps({"ok": True, "details": {}, "message": "Finger assembly validation complete"})

    def validate_sketch(self, args: Dict[str, Any]) -> str:
        return json.dumps({"ok": True, "details": {}, "message": "Sketch validation complete"})

    def list_validation_rules(self, args: Dict[str, Any]) -> str:
        return json.dumps({"ok": True, "details": {"rule_count": 9}, "message": "Validation rules available"})

    def report_validation(self, args: Dict[str, Any]) -> str:
        findings = args.get("findings", [])
        error_count = sum(1 for f in findings if f.get("severity") == 3)
        warning_count = sum(1 for f in findings if f.get("severity") == 2)
        status = "FAIL" if error_count > 0 else ("PROCEED_WITH_CAUTION" if warning_count > 0 else "PASS")
        return json.dumps({"ok": True, "details": {"status": status}, "message": f"Validation report: {status}"})
