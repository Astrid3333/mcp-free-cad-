"""
finger_segment_operations - generador parametrico de falanges + articulaciones
para dedos protesicos, tipo el mecanismo del paper de UTEZ (falange distal,
articulacion interfalangica, falange proximal, cerrado con hilo/cordon).

Operaciones:
    - create_stump_socket(residual_length_mm, residual_width_mm, residual_height_mm,
        wall_thickness_mm=2.5, cuff_length_mm=8.0, clearance_mm=0.5,
        base_position_mm=(0,0,0), direction_mm=(1,0,0), name=None):
        interfaz que envuelve la falange/muñón residual (lo que queda tras
        la amputacion) y da un punto de anclaje limpio para arrancar la
        cadena protesica. SIN esto, create_finger_chain generaba piezas
        "flotando" sin ningun vinculo mecanico al remanente oseo real.
    - create_phalanx(length_mm, width_mm, height_mm, taper=0.85, name=None):
        un segmento de falange (caja ahusada hacia la punta, via loft).
    - create_finger_chain(segment_lengths_mm=None, width_mm=12.0, height_mm=10.0,
        joint_gap_mm=1.0, base_position_mm=(0,0,0), direction_mm=(1,0,0),
        attach_to_socket=None, name=None):
        encadena N falanges con un gap articular entre cada una. Devuelve,
        ademas de las piezas, los joint_positions_mm de cada articulacion --
        pensados para pasarselos DIRECTO a
        tendon_routing_operations(operation="compute_anchor_points", joint_positions_mm=...)
        o a check_tendon_curvature, sin tener que recalcular nada a mano.
        Si se pasa attach_to_socket=<nombre del objeto de create_stump_socket>,
        base_position_mm/direction_mm se ignoran y se toman del punto de
        anclaje guardado en el socket -- para no tener que copiar coordenadas
        a mano entre ambas llamadas.

No incluye el mecanismo de bisagra en si (pin fisico o living hinge) a
proposito -- para eso ya tenes compliant_operations (create_living_hinge /
create_flexure_array), que se puede aplicar sobre el gap articular que
devuelve create_finger_chain.

Validacion de parametros: length/width/height deben ser > 0 y taper debe
estar en (0, 1] -- taper <= 0 colapsa la punta a una linea/dimension
invertida (loft degenerado), taper > 1 infla la punta mas que la base
(geometricamente valido para makeLoft pero no es "ahusado", asi que se
rechaza para evitar resultados confusos). Los errores de validacion se
devuelven como {"error": "..."} en vez de dejar que Part.makeLoft explote
con una excepcion de OCC dificil de leer.

Sin probar contra FreeCAD real. Part.makeLoft(wires, solid=True) deberia
andar para el ahusado pero si tu version de FreeCAD se queja, la alternativa
mas simple es reemplazar el loft por un Part.makeBox() sin ahusar (taper=1.0
efectivamente) mientras lo depuras.
"""

import json
from typing import Any, Dict

import FreeCAD as App
import Part

from .base import BaseHandler


def _validate_phalanx_params(length_mm, width_mm, height_mm, taper):
    """Valida dimensiones de una falange. Lanza ValueError con mensaje
    legible si algo es geometricamente invalido -- para que el handler lo
    convierta en un {"error": ...} en vez de dejar que Part.makeLoft tire
    una excepcion críptica de OCC."""
    if length_mm <= 0:
        raise ValueError(f"length_mm debe ser > 0 (recibido {length_mm})")
    if width_mm <= 0:
        raise ValueError(f"width_mm debe ser > 0 (recibido {width_mm})")
    if height_mm <= 0:
        raise ValueError(f"height_mm debe ser > 0 (recibido {height_mm})")
    if not (0 < taper <= 1):
        raise ValueError(
            f"taper debe estar en (0, 1] (recibido {taper}); "
            f"taper<=0 colapsa la punta, taper>1 la infla en vez de ahusarla"
        )


def _phalanx_shape(length_mm, width_mm, height_mm, taper):
    base_wire = Part.Wire(Part.makePolygon([
        App.Vector(0, 0, 0), App.Vector(0, width_mm, 0),
        App.Vector(0, width_mm, height_mm), App.Vector(0, 0, height_mm),
        App.Vector(0, 0, 0)]))

    tip_w = width_mm * taper
    tip_h = height_mm * taper
    dw = (width_mm - tip_w) / 2
    dh = (height_mm - tip_h) / 2
    tip_wire = Part.Wire(Part.makePolygon([
        App.Vector(length_mm, dw, dh), App.Vector(length_mm, dw + tip_w, dh),
        App.Vector(length_mm, dw + tip_w, dh + tip_h), App.Vector(length_mm, dw, dh + tip_h),
        App.Vector(length_mm, dw, dh)]))

    return Part.makeLoft([base_wire, tip_wire], True)


class FingerSegmentOpsHandler(BaseHandler):
    _ALLOWED_OPERATIONS = {"create_stump_socket", "create_phalanx", "create_finger_chain"}

    def create_stump_socket(self, args: Dict[str, Any]) -> str:
        """Cuff/socket que envuelve la falange o muñón residual tras la
        amputacion, y expone un punto de anclaje (SocketAttachPoint_mm /
        SocketDirection_mm, guardados como propiedades del objeto) para que
        create_finger_chain pueda continuar la cadena protesica desde ahi
        sin recalcular coordenadas a mano."""
        doc = self.get_document()
        if doc is None:
            return json.dumps({"error": "No hay documento activo"})

        residual_length_mm = args.get("residual_length_mm", 15.0)
        residual_width_mm = args.get("residual_width_mm", 14.0)
        residual_height_mm = args.get("residual_height_mm", 12.0)
        wall_thickness_mm = args.get("wall_thickness_mm", 2.5)
        cuff_length_mm = args.get("cuff_length_mm", 8.0)
        clearance_mm = args.get("clearance_mm", 0.5)
        base_position_mm = args.get("base_position_mm", (0, 0, 0))
        direction_mm = args.get("direction_mm", (1, 0, 0))
        new_name = args.get("name")

        try:
            if residual_length_mm <= 0:
                raise ValueError(f"residual_length_mm debe ser > 0 (recibido {residual_length_mm})")
            if residual_width_mm <= 0:
                raise ValueError(f"residual_width_mm debe ser > 0 (recibido {residual_width_mm})")
            if residual_height_mm <= 0:
                raise ValueError(f"residual_height_mm debe ser > 0 (recibido {residual_height_mm})")
            if wall_thickness_mm <= 0:
                raise ValueError(f"wall_thickness_mm debe ser > 0 (recibido {wall_thickness_mm})")
            if cuff_length_mm <= 0:
                raise ValueError(f"cuff_length_mm debe ser > 0 (recibido {cuff_length_mm})")
            if clearance_mm < 0:
                raise ValueError(f"clearance_mm no puede ser negativo (recibido {clearance_mm})")
        except ValueError as e:
            return json.dumps({"error": str(e)})

        direction = App.Vector(*direction_mm).normalize()
        base = App.Vector(*base_position_mm)

        # Caja hueca que envuelve el residual (con holgura clearance_mm) y
        # se extiende cuff_length_mm mas alla de la punta del residual, para
        # dar largo de agarre mecanico antes de la union con la primera
        # falange protesica.
        outer_w = residual_width_mm + 2 * (clearance_mm + wall_thickness_mm)
        outer_h = residual_height_mm + 2 * (clearance_mm + wall_thickness_mm)
        inner_w = residual_width_mm + 2 * clearance_mm
        inner_h = residual_height_mm + 2 * clearance_mm
        total_len = residual_length_mm + cuff_length_mm

        outer_box = Part.makeBox(
            total_len, outer_w, outer_h,
            App.Vector(0, -outer_w / 2, -outer_h / 2))
        # cavidad interior: arranca desde antes del origen (para que el
        # extremo abierto -- por donde entra el residual -- quede sin pared
        # de cierre) y llega hasta residual_length_mm (deja pared de fondo
        # solo si cuff_length_mm > 0, que es el caso normal)
        inner_box = Part.makeBox(
            residual_length_mm + 1.0, inner_w, inner_h,
            App.Vector(-1.0, -inner_w / 2, -inner_h / 2))
        shape = outer_box.cut(inner_box)
        shape.Placement = App.Placement(
            base, App.Rotation(App.Vector(1, 0, 0), direction))

        obj_name = new_name or "stump_socket"
        new_obj = doc.addObject("Part::Feature", obj_name)
        new_obj.Shape = shape
        self.recompute(doc)

        attach_point = base + direction * total_len
        # Guardar el anclaje como propiedades del objeto para que
        # create_finger_chain(attach_to_socket=...) lo lea directo, en vez
        # de depender de register_output_anchor/AttachExtension -- que segun
        # BaseHandler no funciona de forma confiable sobre objetos
        # Part::Feature resultantes de booleanos en este build de FreeCAD.
        if not hasattr(new_obj, "SocketAttachPoint_mm"):
            new_obj.addProperty("App::PropertyVector", "SocketAttachPoint_mm", "FingerSocket",
                                 "Punto donde debe arrancar la primera falange protesica")
        if not hasattr(new_obj, "SocketDirection_mm"):
            new_obj.addProperty("App::PropertyVector", "SocketDirection_mm", "FingerSocket",
                                 "Direccion de la cadena de falanges desde este socket")
        new_obj.SocketAttachPoint_mm = attach_point
        new_obj.SocketDirection_mm = direction

        return json.dumps({
            "object_name": new_obj.Name,
            "attach_point_mm": [round(attach_point.x, 2), round(attach_point.y, 2), round(attach_point.z, 2)],
            "direction_mm": [round(direction.x, 4), round(direction.y, 4), round(direction.z, 4)],
            "note": "pasar object_name como attach_to_socket a create_finger_chain "
                    "para continuar la cadena directo desde este punto",
        })

    def create_phalanx(self, args: Dict[str, Any]) -> str:
        doc = self.get_document()
        if doc is None:
            return json.dumps({"error": "No hay documento activo"})

        length_mm = args.get("length_mm", 20.0)
        width_mm = args.get("width_mm", 12.0)
        height_mm = args.get("height_mm", 10.0)
        taper = args.get("taper", 0.85)
        new_name = args.get("name")

        try:
            _validate_phalanx_params(length_mm, width_mm, height_mm, taper)
        except ValueError as e:
            return json.dumps({"error": str(e)})

        shape = _phalanx_shape(length_mm, width_mm, height_mm, taper)

        obj_name = new_name or "phalanx"
        new_obj = doc.addObject("Part::Feature", obj_name)
        new_obj.Shape = shape
        self.recompute(doc)

        return json.dumps({
            "object_name": new_obj.Name,
            "length_mm": length_mm,
            "width_mm": width_mm,
            "height_mm": height_mm,
        })

    def create_finger_chain(self, args: Dict[str, Any]) -> str:
        doc = self.get_document()
        if doc is None:
            return json.dumps({"error": "No hay documento activo"})

        segment_lengths_mm = args.get("segment_lengths_mm") or [25.0, 20.0, 15.0]
        width_mm = args.get("width_mm", 12.0)
        height_mm = args.get("height_mm", 10.0)
        taper = args.get("taper", 0.85)
        joint_gap_mm = args.get("joint_gap_mm", 1.0)
        base_position_mm = args.get("base_position_mm", (0, 0, 0))
        direction_mm = args.get("direction_mm", (1, 0, 0))
        attach_to_socket = args.get("attach_to_socket")
        new_name = args.get("name")

        try:
            if not segment_lengths_mm:
                raise ValueError("segment_lengths_mm no puede estar vacio")
            for seg_len in segment_lengths_mm:
                _validate_phalanx_params(seg_len, width_mm, height_mm, taper)
            if joint_gap_mm < 0:
                raise ValueError(f"joint_gap_mm no puede ser negativo (recibido {joint_gap_mm})")
        except ValueError as e:
            return json.dumps({"error": str(e)})

        if attach_to_socket:
            socket_obj = self.get_object(attach_to_socket, doc)
            if socket_obj is None:
                return json.dumps({"error": f"No se encontro el socket '{attach_to_socket}'"})
            if not hasattr(socket_obj, "SocketAttachPoint_mm"):
                return json.dumps({
                    "error": f"'{attach_to_socket}' no tiene SocketAttachPoint_mm -- "
                             f"¿fue creado con create_stump_socket?"
                })
            base = socket_obj.SocketAttachPoint_mm
            direction = socket_obj.SocketDirection_mm
        else:
            direction = App.Vector(*direction_mm).normalize()
            base = App.Vector(*base_position_mm)

        segments = []
        joint_positions_mm = []
        cursor = 0.0
        for i, seg_len in enumerate(segment_lengths_mm):
            pos = base + direction * cursor
            shape = _phalanx_shape(seg_len, width_mm, height_mm, taper)

            obj_name = f"{new_name or 'finger'}_seg{i}"
            new_obj = doc.addObject("Part::Feature", obj_name)
            new_obj.Shape = shape
            new_obj.Placement = App.Placement(pos, App.Rotation())
            segments.append(new_obj.Name)

            cursor += seg_len
            if i < len(segment_lengths_mm) - 1:
                joint_center = base + direction * cursor
                joint_positions_mm.append(
                    [round(joint_center.x, 2), round(joint_center.y, 2), round(joint_center.z, 2)]
                )
                cursor += joint_gap_mm

        self.recompute(doc)
        return json.dumps({
            "segments": segments,
            "joint_positions_mm": joint_positions_mm,
            "note": "pasar joint_positions_mm directo a tendon_routing_operations "
                    "(compute_anchor_points / check_tendon_curvature) para planear el cordon de cierre; "
                    "para el mecanismo de la bisagra en si, usar compliant_operations sobre cada gap",
        })


# --- schema sugerido para registrar en tu server MCP (AICopilot) ---
# {
#   "name": "finger_segment_operations",
#   "description": "Generador parametrico de falanges/dedos protesicos con interfaz de muñón, integrable con tendon_routing_operations.",
#   "parameters": {
#     "properties": {
#       "operation": {"enum": ["create_stump_socket", "create_phalanx", "create_finger_chain"], "type": "string"},
#       "length_mm": {"type": "number"},
#       "width_mm": {"type": "number", "default": 12.0},
#       "height_mm": {"type": "number", "default": 10.0},
#       "taper": {"type": "number", "default": 0.85},
#       "segment_lengths_mm": {"type": "array", "items": {"type": "number"}},
#       "joint_gap_mm": {"type": "number", "default": 1.0},
#       "base_position_mm": {"type": "array", "items": {"type": "number"}, "default": [0, 0, 0]},
#       "direction_mm": {"type": "array", "items": {"type": "number"}, "default": [1, 0, 0]},
#       "attach_to_socket": {"type": "string", "description": "nombre de un objeto creado con create_stump_socket"},
#       "residual_length_mm": {"type": "number", "default": 15.0},
#       "residual_width_mm": {"type": "number", "default": 14.0},
#       "residual_height_mm": {"type": "number", "default": 12.0},
#       "wall_thickness_mm": {"type": "number", "default": 2.5},
#       "cuff_length_mm": {"type": "number", "default": 8.0},
#       "clearance_mm": {"type": "number", "default": 0.5},
#       "name": {"type": "string"}
#     },
#     "required": ["operation"]
#   }
# }
