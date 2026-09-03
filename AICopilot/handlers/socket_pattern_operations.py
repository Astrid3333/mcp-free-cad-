"""
socket_pattern_operations.py

Modulo para el fork Astrid3333/mcp-free-cad- : operaciones de geometria
con patrones COMUNES de protesica de socket (transtibial / transfemoral),
pensado para completar lo que organic_ops.py y growth_socket_operations.py
no cubren todavia.

Sigue el patron real confirmado en organic_ops.py (offset_surface):
  - self.get_document(doc_name) / FreeCAD.getDocument(doc_name)
  - self.get_object(object_name, doc)
  - doc.addObject("Part::Feature", name); feature.Shape = shape; doc.recompute()
  - cada operacion: def op(self, args: Dict[str, Any]) -> str, retorna
    json.dumps({"ok": bool, "details": {...}, "message": str})

INTEGRACION:
  1. Ya deberia estar en AICopilot/handlers/socket_pattern_operations.py
  2. En freecad_mcp_handler.py:
       from .socket_pattern_operations import SocketPatternOpsHandler
       ...
       socket_pattern_handler = SocketPatternOpsHandler(server, log_operation, capture_state)
       generic_dispatch_map.update({
           op: socket_pattern_handler for op in SocketPatternOpsHandler.OPERATIONS
       })
  3. Registrar OPERATIONS en la lista/schema de tools expuestas por el server
     (el mismo lugar donde estan registradas las de organic_ops / materials_ops).
"""

import json
import math
from typing import Any, Dict

import FreeCAD
import Part

from .base import BaseHandler


class SocketPatternOpsHandler(BaseHandler):
    """Patrones geometricos comunes de socket protesico."""

    OPERATIONS = (
        "generate_trim_line",
        "rectify_socket",
        "total_surface_bearing_shell",
        "liner_offset",
        "check_draft_angles",
        "socket_pylon_transition",
    )

    _ALLOWED_OPERATIONS = frozenset(OPERATIONS)

    def _resolve_doc_and_object(self, args: Dict[str, Any], key="shape"):
        doc_name = args.get("doc_name")
        doc = FreeCAD.getDocument(doc_name) if doc_name else self.get_document()
        if not doc:
            return None, None, json.dumps({
                "ok": False, "details": {},
                "message": f"No document found (doc_name={doc_name!r})",
            })
        object_name = args.get(key) or args.get("object_name")
        if not object_name:
            return doc, None, json.dumps({
                "ok": False, "details": {},
                "message": f"Missing required argument: {key}",
            })
        obj = self.get_object(object_name, doc)
        if not obj or not hasattr(obj, "Shape"):
            return doc, None, json.dumps({
                "ok": False, "details": {},
                "message": f"Object not found or has no Shape: {object_name}",
            })
        return doc, obj, None

    @staticmethod
    def _angular_delta(deg_a, deg_b):
        return (deg_a - deg_b + 180.0) % 360.0 - 180.0

    def generate_trim_line(self, args: Dict[str, Any]) -> str:
        """Contorno de corte proximal (brim): alza patelar anterior,
        caida poplitea posterior, alivio en zonas sensibles.
        Args: doc_name, shape, proximal_plane_z, n_points(72),
        anterior_patellar_rise(15), anterior_angle_deg(0),
        posterior_popliteal_drop(10), medial_relief_deg(20), name"""
        try:
            doc, obj, err = self._resolve_doc_and_object(args)
            if err:
                return err
            n = int(args.get("n_points", 72))
            z0 = float(args["proximal_plane_z"])
            rise = float(args.get("anterior_patellar_rise", 15.0))
            drop = float(args.get("posterior_popliteal_drop", 10.0))
            center_deg = float(args.get("anterior_angle_deg", 0.0))
            relief_deg = float(args.get("medial_relief_deg", 20.0))
            name = args.get("name") or f"{obj.Name}_TrimLine"

            bbox = obj.Shape.BoundBox
            cx, cy = bbox.Center.x, bbox.Center.y
            r_est = max(bbox.XLength, bbox.YLength) / 2.0

            pts = []
            for i in range(n):
                theta = 2 * math.pi * i / n
                deg = math.degrees(theta)
                d_ant = self._angular_delta(deg, center_deg)
                d_post = self._angular_delta(deg, center_deg + 180.0)
                z = z0
                z += rise * math.exp(-(d_ant ** 2) / (2 * relief_deg ** 2))
                z -= drop * math.exp(-(d_post ** 2) / (2 * relief_deg ** 2))
                x = cx + r_est * math.cos(theta)
                y = cy + r_est * math.sin(theta)
                pts.append(FreeCAD.Vector(x, y, z))
            pts.append(pts[0])

            wire = Part.makePolygon(pts)
            feature = doc.addObject("Part::Feature", name)
            feature.Shape = wire
            doc.recompute()
            return json.dumps({"ok": True, "details": {"name": feature.Name, "n_points": n},
                                "message": f"Trim line generado: {feature.Name}"})
        except Exception as e:
            return json.dumps({"ok": False, "details": {}, "message": f"Error: {e}"})

    def rectify_socket(self, args: Dict[str, Any]) -> str:
        """Desplaza vertices de un Mesh a lo largo de su normal local
        dentro de un radio de influencia (relief/build-up).
        Args: doc_name, mesh, zones:[{center,radius_mm,offset_mm}],
        falloff('gaussian'|'linear'), name"""
        try:
            import Mesh
            doc_name = args.get("doc_name")
            doc = FreeCAD.getDocument(doc_name) if doc_name else self.get_document()
            if not doc:
                return json.dumps({"ok": False, "details": {},
                                    "message": f"No document found (doc_name={doc_name!r})"})
            mesh_name = args.get("mesh") or args.get("object_name")
            if not mesh_name:
                return json.dumps({"ok": False, "details": {}, "message": "Missing required argument: mesh"})
            mesh_obj = self.get_object(mesh_name, doc)
            if not mesh_obj or not hasattr(mesh_obj, "Mesh"):
                return json.dumps({"ok": False, "details": {},
                                    "message": f"Object not found or has no Mesh: {mesh_name}"})
            zones = args.get("zones") or []
            if not zones:
                return json.dumps({"ok": False, "details": {}, "message": "Missing required argument: zones"})
            falloff = args.get("falloff", "gaussian")
            name = args.get("name") or f"{mesh_name}_Rectified"

            mesh = mesh_obj.Mesh.copy()
            points, facets = mesh.Topology
            new_points = list(points)
            vertex_normals = self._vertex_normals(mesh)

            for zone in zones:
                center = FreeCAD.Vector(*zone["center"])
                radius = float(zone["radius_mm"])
                offset = float(zone["offset_mm"])
                for i, p in enumerate(new_points):
                    dist = (p - center).Length
                    if dist > radius:
                        continue
                    if falloff == "linear":
                        w = 1.0 - dist / radius
                    else:
                        sigma = radius / 2.0
                        w = math.exp(-(dist ** 2) / (2 * sigma ** 2))
                    new_points[i] = p + vertex_normals[i] * (offset * w)

            rebuilt = Mesh.Mesh((new_points, facets))
            out = doc.addObject("Mesh::Feature", name)
            out.Mesh = rebuilt
            doc.recompute()
            return json.dumps({"ok": True, "details": {"name": out.Name, "zones_applied": len(zones)},
                                "message": f"Socket rectificado: {out.Name}"})
        except Exception as e:
            return json.dumps({"ok": False, "details": {}, "message": f"Error: {e}"})

    @staticmethod
    def _vertex_normals(mesh):
        n_pts = len(mesh.Points)
        acc = [FreeCAD.Vector(0, 0, 0) for _ in range(n_pts)]
        for facet in mesh.Facets:
            fn = FreeCAD.Vector(*facet.Normal)
            for idx in facet.PointIndices:
                acc[idx] = acc[idx] + fn
        return [v.normalize() if v.Length > 1e-9 else FreeCAD.Vector(0, 0, 1) for v in acc]

    def total_surface_bearing_shell(self, args: Dict[str, Any]) -> str:
        """Shell TSB con espesor variable (mas grueso proximal, mas fino
        distal) + flare distal opcional.
        Args: doc_name, shape, thickness_proximal_mm, thickness_distal_mm,
        flare_distal_mm(0), flare_length_mm(20), n_slices(12), name"""
        try:
            doc, obj, err = self._resolve_doc_and_object(args)
            if err:
                return err
            t_prox = float(args["thickness_proximal_mm"])
            t_dist = float(args["thickness_distal_mm"])
            n_slices = int(args.get("n_slices", 12))
            name = args.get("name") or f"{obj.Name}_TSBShell"

            shape = obj.Shape
            bbox = shape.BoundBox
            z_top, z_bot = bbox.ZMax, bbox.ZMin
            height = max(z_top - z_bot, 1e-6)

            solids = []
            for i in range(n_slices):
                z_lo = z_bot + height * i / n_slices
                z_hi = z_bot + height * (i + 1) / n_slices
                frac = 1.0 - ((z_lo - z_bot) / height)
                t = t_dist + (t_prox - t_dist) * frac
                band_box = Part.makeBox(
                    bbox.XLength + 200, bbox.YLength + 200, (z_hi - z_lo),
                    FreeCAD.Vector(bbox.XMin - 100, bbox.YMin - 100, z_lo),
                )
                band = shape.common(band_box)
                if band.Volume <= 1e-6:
                    continue
                
                # Strategy: Intentar makeThickening (más robusto que makeOffsetShape)
                # Si falla, intentar con faces cerradas manualmente
                try:
                    # makeThickening funciona en shells/faces abiertos
                    offset_band = band.makeThickening(t, 1e-3, step=False)
                    if offset_band and offset_band.isValid():
                        # Cut the original to get just the wall thickness
                        wall = offset_band.cut(band)
                        if wall and wall.isValid():
                            solids.append(wall)
                            continue
                except Exception:
                    pass
                
                # Fallback: Si makeThickening falla, intentar offset directo en faces
                try:
                    faces = list(band.Faces)
                    if not faces:
                        continue
                    # Offset cada face individualmente
                    offset_faces = []
                    for face in faces:
                        try:
                            off_face = face.makeOffsetShape(t, 1e-3, fill=False)
                            if off_face and off_face.isValid():
                                offset_faces.append(off_face)
                        except Exception:
                            pass
                    
                    if offset_faces:
                        # Fusionar todos los faces offset
                        result = offset_faces[0]
                        for of in offset_faces[1:]:
                            try:
                                result = result.fuse(of)
                            except Exception:
                                pass
                        solids.append(result)
                        continue
                except Exception:
                    pass
                
                # Last resort: Ignorar esta banda si ambos métodos fallan
                continue

            if not solids:
                return json.dumps({"ok": False, "details": {},
                                    "message": "No se generaron bandas validas (revisar geometria de entrada)"})

            result = solids[0]
            for s in solids[1:]:
                result = result.fuse(s)

            flare = float(args.get("flare_distal_mm", 0.0))
            if flare > 0:
                flare_len = float(args.get("flare_length_mm", 20.0))
                result = self._apply_distal_flare(result, bbox, z_bot, flare, flare_len)

            feature = doc.addObject("Part::Feature", name)
            feature.Shape = result
            doc.recompute()
            return json.dumps({"ok": True, "details": {"name": feature.Name, "n_slices_used": len(solids)},
                                "message": f"TSB shell generado: {feature.Name}"})
        except Exception as e:
            return json.dumps({"ok": False, "details": {}, "message": f"Error: {e}"})

    @staticmethod
    def _apply_distal_flare(shape, bbox, z_bot, flare_mm, flare_len_mm):
        base_section = shape.slice(FreeCAD.Vector(0, 0, 1), z_bot + 0.5)
        top_z = z_bot + flare_len_mm
        top_section = shape.slice(FreeCAD.Vector(0, 0, 1), top_z)
        if not base_section or not top_section:
            return shape
        cx, cy = bbox.Center.x, bbox.Center.y
        scale = 1.0 + (flare_mm / max(bbox.XLength, bbox.YLength, 1.0))
        wires_top = [w.scale(scale, FreeCAD.Vector(cx, cy, top_z)) for w in top_section]
        try:
            loft = Part.makeLoft(base_section + wires_top, True)
            return shape.fuse(loft)
        except Exception:
            return shape

    def liner_offset(self, args: Dict[str, Any]) -> str:
        """Superficie interior efectiva descontando espesor de una pila
        de liners. Args: doc_name, shape, liner_layers_mm(lista), name"""
        try:
            doc, obj, err = self._resolve_doc_and_object(args)
            if err:
                return err
            layers = args.get("liner_layers_mm") or []
            if not layers:
                return json.dumps({"ok": False, "details": {}, "message": "Missing required argument: liner_layers_mm"})
            total_t = sum(float(t) for t in layers)
            name = args.get("name") or f"{obj.Name}_LinerOffset"

            new_shape = obj.Shape.makeOffsetShape(total_t, 0.01, fill=True)
            feature = doc.addObject("Part::Feature", name)
            feature.Shape = new_shape
            doc.recompute()
            return json.dumps({"ok": True, "details": {"name": feature.Name, "total_offset_mm": total_t},
                                "message": f"Liner offset generado: {feature.Name}"})
        except Exception as e:
            return json.dumps({"ok": False, "details": {}, "message": f"Error: {e}"})

    def check_draft_angles(self, args: Dict[str, Any]) -> str:
        """Reporta angulo entre normal de cada cara y direccion de tiro
        (no crea objeto). Args: doc_name, shape, pull_direction([0,0,1]),
        min_draft_deg(3.0)"""
        try:
            doc, obj, err = self._resolve_doc_and_object(args)
            if err:
                return err
            pull = FreeCAD.Vector(*args.get("pull_direction", [0, 0, 1])).normalize()
            min_draft = float(args.get("min_draft_deg", 3.0))

            flagged = []
            worst = 90.0
            for idx, face in enumerate(obj.Shape.Faces):
                u_mid = (face.ParameterRange[0] + face.ParameterRange[1]) / 2.0
                v_mid = (face.ParameterRange[2] + face.ParameterRange[3]) / 2.0
                normal = face.normalAt(u_mid, v_mid).normalize()
                angle_from_pull = math.degrees(normal.getAngle(pull))
                draft_angle = abs(90.0 - angle_from_pull)
                worst = min(worst, draft_angle)
                if draft_angle < min_draft:
                    flagged.append({"index": idx, "angle_deg": round(draft_angle, 2)})

            return json.dumps({
                "ok": True,
                "details": {"n_faces": len(obj.Shape.Faces), "faces_below_min": flagged,
                             "worst_angle_deg": round(worst, 2)},
                "message": f"{len(flagged)} caras por debajo de {min_draft} grados de draft",
            })
        except Exception as e:
            return json.dumps({"ok": False, "details": {}, "message": f"Error: {e}"})


    def build_tsb_shell(self, args: Dict[str, Any]) -> str:
        """Construye shell TSB via wire extraction (band.slice -> offset -> Part.makeLoft)."""
        try:
            socket_name = args.get("socket_name", "")
            thickness_mm = args.get("shell_thickness_mm", 3.5)
            material_zone = args.get("material_zone", "primary_contact")
            
            if not socket_name:
                return json.dumps({"ok": False, "details": {}, "message": "Missing: socket_name"})
            
            import FreeCAD
            doc = FreeCAD.ActiveDocument
            if not doc:
                return json.dumps({"ok": False, "details": {}, "message": "No active FreeCAD document"})
            
            socket_obj = doc.getObject(socket_name)
            if not socket_obj or not hasattr(socket_obj, "Shape"):
                return json.dumps({"ok": False, "details": {}, "message": f"Socket not found: {socket_name}"})
            
            shape = socket_obj.Shape
            faces = shape.Faces
            if not faces:
                return json.dumps({"ok": False, "details": {}, "message": "No faces in socket"})
            
            band_face = max(faces, key=lambda f: f.Area) if faces else None
            if not band_face:
                return json.dumps({"ok": False, "details": {}, "message": "Could not select band"})
            
            shell = self._create_tsb_shell_from_face(band_face, thickness_mm)
            if shell is None:
                return json.dumps({
                    "ok": False,
                    "details": {"band_area_mm2": band_face.Area},
                    "message": "Wire extraction failed"
                })
            
            shell_obj = doc.addObject("Part::Feature", f"{socket_name}_Shell")
            shell_obj.Shape = shell
            
            if material_zone:
                if not hasattr(shell_obj, "MaterialZone"):
                    shell_obj.addProperty("App::PropertyString", "MaterialZone", "Socket")
                shell_obj.MaterialZone = material_zone
            
            doc.recompute()
            
            return json.dumps({
                "ok": True,
                "details": {
                    "socket_name": socket_name,
                    "shell_obj_name": shell_obj.Name,
                    "shell_thickness_mm": thickness_mm,
                    "shell_surface_area_mm2": shell.Area,
                    "material_zone": material_zone,
                },
                "message": f"TSB shell created: {shell_obj.Name}"
            })
        
        except Exception as e:
            return json.dumps({"ok": False, "details": {}, "message": f"Error: {e}"})
    
    def _create_tsb_shell_from_face(self, band_face: "Part.Face", thickness_mm: float):
        """Wire extraction: band_face.slice() -> offset -> Part.makeLoft()."""
        try:
            import Part
            
            if band_face is None or band_face.isNull():
                return None
            
            wires = band_face.slice() if hasattr(band_face, 'slice') else []
            if not wires:
                wires = [band_face.OuterWire] if hasattr(band_face, 'OuterWire') else []
            
            if not wires:
                return None
            
            if not isinstance(wires, (list, tuple)):
                wires = [wires]
            
            wires_offset = []
            for wire in wires:
                if wire is None or wire.isNull():
                    continue
                
                try:
                    temp_face = Part.Face(wire)
                    offset_face = temp_face.makeOffsetShape(thickness_mm, 1e-6, True)
                    
                    if offset_face and not offset_face.isNull():
                        offset_wires = offset_face.Wires
                        if offset_wires and len(offset_wires) > 0:
                            wires_offset.append(offset_wires[0])
                        else:
                            wires_offset.append(wire)
                    else:
                        wires_offset.append(wire)
                except Exception:
                    wires_offset.append(wire)
            
            if not wires_offset:
                return None
            
            if len(wires) == 1 and len(wires_offset) == 1:
                lofted = Part.makeLoft([wires[0], wires_offset[0]], False, False)
                if lofted and not lofted.isNull():
                    return Part.Shell([lofted])
            else:
                faces = []
                for w_orig, w_offset in zip(wires, wires_offset):
                    try:
                        lofted = Part.makeLoft([w_orig, w_offset], False, False)
                        if lofted and not lofted.isNull():
                            faces.append(lofted)
                    except Exception:
                        pass
                
                if faces:
                    return Part.Shell(faces)
            
            return None
        
        except Exception as e:
            print(f"❌ Wire extraction error: {e}")
            return None


    def socket_pylon_transition(self, args: Dict[str, Any]) -> str:
        """Transicion (loft + fillet) entre socket y adaptador/pylon.
        Args: doc_name, shape(socket), pylon_interface, fillet_radius_mm(3.0), name"""
        try:
            doc, socket_obj, err = self._resolve_doc_and_object(args, key="shape")
            if err:
                return err
            pylon_name = args.get("pylon_interface")
            if not pylon_name:
                return json.dumps({"ok": False, "details": {}, "message": "Missing required argument: pylon_interface"})
            pylon_obj = self.get_object(pylon_name, doc)
            if not pylon_obj or not hasattr(pylon_obj, "Shape"):
                return json.dumps({"ok": False, "details": {},
                                    "message": f"Object not found or has no Shape: {pylon_name}"})

            fillet_r = float(args.get("fillet_radius_mm", 3.0))
            name = args.get("name") or "SocketPylonTransition"

            socket_shape = socket_obj.Shape
            pylon_shape = pylon_obj.Shape
            z_socket_bottom = socket_shape.BoundBox.ZMin
            z_pylon_top = pylon_shape.BoundBox.ZMax

            section_socket = socket_shape.slice(FreeCAD.Vector(0, 0, 1), z_socket_bottom + 0.5)
            section_pylon = pylon_shape.slice(FreeCAD.Vector(0, 0, 1), z_pylon_top - 0.5)
            if not section_socket or not section_pylon:
                return json.dumps({"ok": False, "details": {},
                                    "message": "No se pudieron extraer secciones para el loft (revisar solape en Z)"})

            loft = Part.makeLoft(section_socket + section_pylon, True)
            combined = socket_shape.fuse(loft).fuse(pylon_shape)

            try:
                edges_to_fillet = [
                    e for e in combined.Edges
                    if abs(e.BoundBox.ZMin - z_socket_bottom) < 1.0
                    or abs(e.BoundBox.ZMax - z_pylon_top) < 1.0
                ]
                if edges_to_fillet:
                    combined = combined.makeFillet(fillet_r, edges_to_fillet)
            except Exception:
                pass

            feature = doc.addObject("Part::Feature", name)
            feature.Shape = combined
            doc.recompute()
            return json.dumps({"ok": True, "details": {"name": feature.Name},
                                "message": f"Transicion socket-pylon generada: {feature.Name}"})
        except Exception as e:
            return json.dumps({"ok": False, "details": {}, "message": f"Error: {e}"})
