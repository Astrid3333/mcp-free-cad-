# -*- coding: utf-8 -*-
"""
quadruped_limb_ops.py

Handler para prótesis/órtesis de miembro en cuadrúpedos (canino, felino,
equino). Complemento veterinario de four_bar_knee_ops.py -- pero NO reusa su
síntesis de cuadrilátero articulado. La rodilla humana protésica se modela
como policéntrica (4 barras) para reproducir el desplazamiento del ICR de
una rodilla natural; el stifle (rodilla) o el hock (corvejón/tarso) de un
cuadrúpedo protésico casi siempre se resuelve en la práctica veterinaria
real como una bisagra de un solo eje con tope de ROM (rango de movimiento)
ajustable -- no hay literatura clínica veterinaria pidiendo un ICR
desplazable ahí. Por eso este archivo define su propia síntesis (mucho más
simple: un pasador + dos eslabones), en vez de parametrizar
FourBarLinkage con otros números.

IMPORTANTE -- valores placeholder: los rangos de ROM y las proporciones de
segmento por especie en SPECIES_PRESETS son puntos de partida de ingeniería
razonables (orden de magnitud), NO datos clínicos verificados. Cualquier
prótesis real necesita ROM confirmado por el veterinario/ortopedista a
partir de goniometría del paciente real, igual que hiciste con
four_bar_knee_ops (r1..r4 de literatura como placeholder, ajustar con
medidas reales). Tratá SPECIES_PRESETS como default de UI, no como fuente
de verdad.

Sigue tu convención real de BaseHandler (get_document, recompute,
log_and_return, register_output_anchor, place_in_chain) -- mismo patrón que
four_bar_knee_ops.py.
"""

import math
import time
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Tuple


# ---------------------------------------------------------------------------
# 1. Presets por especie / miembro (placeholders de ingeniería -- ver nota arriba)
# ---------------------------------------------------------------------------
# limb: "fore" (delantero: hombro-codo-carpo) o "hind" (trasero: cadera-stifle-hock)
# joint_rom_deg: (flexión_min, flexión_max) del eje que reemplaza la prótesis,
#   0° = extensión completa. Rangos deliberadamente amplios (placeholder).
# segment_ratio: fracción aproximada de la longitud total del miembro que
#   corresponde al segmento proximal vs distal al eje protésico -- útil para
#   escalar organic_operations.cross_section_stack sin adivinar a ojo.

SPECIES_PRESETS: Dict[str, Dict[str, Dict[str, Any]]] = {
    "canine": {
        "fore": {"joint_rom_deg": (20.0, 160.0), "segment_ratio": 0.55, "typical_joint": "carpus (wrist analog)"},
        "hind": {"joint_rom_deg": (40.0, 165.0), "segment_ratio": 0.50, "typical_joint": "stifle/hock (knee/ankle analog)"},
    },
    "feline": {
        "fore": {"joint_rom_deg": (25.0, 155.0), "segment_ratio": 0.55, "typical_joint": "carpus"},
        "hind": {"joint_rom_deg": (35.0, 160.0), "segment_ratio": 0.50, "typical_joint": "stifle/hock"},
    },
    "equine": {
        # Los equinos apoyan el peso mucho más distalmente (falange) y con ROM
        # notablemente más chico -- placeholder aún más conservador, y la
        # mayoría de los casos reales en equinos son órtesis, no prótesis de
        # miembro completo (amputación equina es rara y de pronóstico complejo).
        "fore": {"joint_rom_deg": (10.0, 60.0), "segment_ratio": 0.60, "typical_joint": "carpus/fetlock"},
        "hind": {"joint_rom_deg": (10.0, 55.0), "segment_ratio": 0.55, "typical_joint": "hock/fetlock"},
    },
    "rabbit": {
        # Lagomorfo -- adaptado a salto, ROM mayor y ratio de segmento distal
        # más corto que canine/feline. Placeholder de ingeniería, no dato
        # clínico verificado.
        "fore": {"joint_rom_deg": (30.0, 150.0), "segment_ratio": 0.50, "typical_joint": "carpus"},
        "hind": {"joint_rom_deg": (45.0, 170.0), "segment_ratio": 0.45, "typical_joint": "tarsus (hock adaptado a salto)"},
    },
    "avian": {
        # Casos de prótesis en ave son excepcionales (mayormente pata/tarso,
        # rara vez ala) -- placeholder aún menos validado que el resto,
        # incluido solo como punto de partida geométrico.
        "fore": {"joint_rom_deg": (20.0, 140.0), "segment_ratio": 0.50, "typical_joint": "carpometacarpo (ala, prótesis rara)"},
        "hind": {"joint_rom_deg": (30.0, 155.0), "segment_ratio": 0.40, "typical_joint": "tarsometatarso"},
    },
}

VALID_SPECIES = tuple(SPECIES_PRESETS.keys())
VALID_LIMBS = ("fore", "hind")


def _get_preset(species: str, limb: str) -> Dict[str, Any]:
    if species not in SPECIES_PRESETS:
        raise ValueError(f"species debe ser uno de {VALID_SPECIES}, recibido {species!r}")
    if limb not in VALID_LIMBS:
        raise ValueError(f"limb debe ser uno de {VALID_LIMBS}, recibido {limb!r}")
    return SPECIES_PRESETS[species][limb]


# ---------------------------------------------------------------------------
# 2. Núcleo cinemático: bisagra de un eje con tope de ROM (puro, sin FreeCAD)
# ---------------------------------------------------------------------------

@dataclass
class SingleAxisJoint:
    """
    Bisagra simple de un grado de libertad: dos eslabones (proximal, distal)
    unidos por un pasador en el origen local, con tope mecánico de ROM.

    proximal_len, distal_len: longitudes de los eslabones a cada lado del
        pasador (mm).
    rom_min_deg, rom_max_deg: tope de flexión permitido (0° = extensión
        completa, eslabones colineales).
    """
    proximal_len: float
    distal_len: float
    rom_min_deg: float
    rom_max_deg: float

    def __post_init__(self):
        if self.proximal_len <= 0 or self.distal_len <= 0:
            raise ValueError("proximal_len y distal_len deben ser positivos")
        if self.rom_min_deg >= self.rom_max_deg:
            raise ValueError("rom_min_deg debe ser menor que rom_max_deg")

    def clamp_flexion(self, flexion_deg: float) -> Tuple[float, bool]:
        """Recorta flexion_deg al ROM permitido. Devuelve (valor, fue_recortado)."""
        clamped = max(self.rom_min_deg, min(self.rom_max_deg, flexion_deg))
        return clamped, (clamped != flexion_deg)

    def joint_positions(self, flexion_deg: float):
        """
        Posiciones del pasador (origen), del extremo proximal (P) y del
        extremo distal (D) para un ángulo de flexión dado. El eslabón
        proximal se fija a lo largo de +X; el distal rota `flexion_deg`
        respecto de esa referencia (0° = colineal / extensión completa).
        """
        flexion, _ = self.clamp_flexion(flexion_deg)
        theta = math.radians(flexion)
        pin = (0.0, 0.0)
        P = (-self.proximal_len, 0.0)
        D = (self.distal_len * math.cos(theta), self.distal_len * math.sin(theta))
        return pin, P, D


# ---------------------------------------------------------------------------
# 3. Handler FreeCAD (hereda de BaseHandler -- misma convención que el resto)
# ---------------------------------------------------------------------------

try:
    from .base import BaseHandler
except ImportError:
    # Permite testear SingleAxisJoint / presets sueltos, fuera del paquete
    # AICopilot.handlers, igual que hace four_bar_knee_ops.py.
    class BaseHandler:  # type: ignore
        ROLE_SOCKET = "socket"
        ROLE_PYLON = "pylon"


class QuadrupedLimbHandler(BaseHandler):
    """
    Handler MCP para prótesis/órtesis de miembro en cuadrúpedos. Reusa
    organic_operations (perfiles/loft del muñón), contact_pressure_operations
    (ajuste socket-a-miembro) y growth_socket_operations (si el paciente es
    un cachorro/potrillo aún en crecimiento -- crecen más rápido que un
    humano pediátrico) tal cual, sin cambios; este archivo solo agrega la
    parte que SÍ es específica de cuadrúpedo: la cinemática del eje protésico
    y los presets de especie/miembro.

    NOTA sobre ROLE_LIMB_JOINT: igual que FourBarKneeHandler con
    ROLE_KNEE_MECHANISM, este rol debería vivir como atributo de clase en
    BaseHandler (base.py) para quedar prolijo:

        ROLE_LIMB_JOINT = "limb_joint"

    agregalo junto a ROLE_KNEE_MECHANISM. Es un rol *separado* de
    ROLE_KNEE_MECHANISM a propósito -- ese nombre ya implica la síntesis de
    4 barras humana, y mezclar cuadrúpedo ahí generaría confusión sobre qué
    geometría se está construyendo. Cadena propuesta para cuadrúpedo:

        ROLE_SOCKET -> ROLE_LIMB_JOINT -> ROLE_PYLON -> ROLE_QUICK_CONNECT -> ROLE_TERMINAL_DEVICE

    Mientras tanto, fallback local para no romper si todavía no hiciste el
    cambio en base.py.
    """

    ROLE_LIMB_JOINT = getattr(BaseHandler, "ROLE_LIMB_JOINT", "limb_joint")

    _ALLOWED_OPERATIONS = frozenset({
        "list_species_presets", "check_joint_rom",
        "suggest_segment_lengths", "build_limb_joint",
    })

    # -- read-only / dry-run ------------------------------------------------

    def list_species_presets(self, params: Dict[str, Any]) -> str:
        """Devuelve SPECIES_PRESETS tal cual, para que el cliente MCP pueda
        mostrar defaults razonables antes de pedir medidas reales."""
        t0 = time.time()
        try:
            result = str(SPECIES_PRESETS)
            return self.log_and_return("list_species_presets", params, result=result, duration=time.time() - t0)
        except Exception as e:
            return self.log_and_return("list_species_presets", params, error=e, duration=time.time() - t0)

    def check_joint_rom(self, params: Dict[str, Any]) -> str:
        """
        Valida un ROM candidato contra el preset de especie/miembro (o uno
        custom si se pasan rom_min_deg/rom_max_deg explícitos), y calcula la
        posición resultante del eslabón distal para flexion_deg dado. No crea
        geometría.

        Args:
            params: species, limb (para tomar el preset), flexion_deg
                (default: punto medio del ROM), proximal_len, distal_len (mm),
                rom_min_deg / rom_max_deg (opcionales -- si se pasan,
                sobreescriben el preset).
        """
        t0 = time.time()
        try:
            species = params.get("species", "canine")
            limb = params.get("limb", "hind")
            preset = _get_preset(species, limb)

            rom_min = float(params.get("rom_min_deg", preset["joint_rom_deg"][0]))
            rom_max = float(params.get("rom_max_deg", preset["joint_rom_deg"][1]))
            proximal_len = float(params["proximal_len"])
            distal_len = float(params["distal_len"])

            joint = SingleAxisJoint(proximal_len, distal_len, rom_min, rom_max)
            flexion_deg = float(params.get("flexion_deg", (rom_min + rom_max) / 2.0))
            clamped, was_clamped = joint.clamp_flexion(flexion_deg)
            pin, P, D = joint.joint_positions(clamped)

            result = (
                f"{species}/{limb} ({preset['typical_joint']}): ROM=[{rom_min:.1f}, {rom_max:.1f}]deg. "
                f"flexion_deg={flexion_deg:.1f}"
                + (f" -> recortado a {clamped:.1f} (fuera de ROM)" if was_clamped else " (dentro de ROM)")
                + f". pin={pin}, extremo_proximal={P}, extremo_distal={D}."
            )
            return self.log_and_return("check_joint_rom", params, result=result, duration=time.time() - t0)
        except Exception as e:
            return self.log_and_return("check_joint_rom", params, error=e, duration=time.time() - t0)

    def suggest_segment_lengths(self, params: Dict[str, Any]) -> str:
        """
        Reparte una longitud total de miembro medida en el paciente entre
        segmento proximal y distal al eje protésico, usando segment_ratio del
        preset de especie/miembro. Pensado como input directo para
        organic_operations.cross_section_stack (espaciado de estaciones) sin
        adivinar a ojo la proporción.

        Args:
            params: species, limb, total_limb_length_mm
        """
        t0 = time.time()
        try:
            species = params.get("species", "canine")
            limb = params.get("limb", "hind")
            preset = _get_preset(species, limb)
            total = float(params["total_limb_length_mm"])
            ratio = float(preset["segment_ratio"])
            proximal = total * ratio
            distal = total * (1.0 - ratio)
            result = (
                f"{species}/{limb}: total={total:.1f}mm -> "
                f"proximal={proximal:.1f}mm, distal={distal:.1f}mm "
                f"(segment_ratio preset={ratio:.2f}, ajustar con medida real del paciente)."
            )
            return self.log_and_return("suggest_segment_lengths", params, result=result, duration=time.time() - t0)
        except Exception as e:
            return self.log_and_return("suggest_segment_lengths", params, error=e, duration=time.time() - t0)

    # -- geometry-creating ---------------------------------------------------

    def build_limb_joint(self, params: Dict[str, Any]) -> str:
        """
        Construye la bisagra de un eje (dos eslabones + pasador cilíndrico
        proxy) en el ángulo de flexión dado, y la registra en la cadena de
        ensamblaje como ROLE_LIMB_JOINT -- misma mecánica de anchors que
        build_knee_mechanism en four_bar_knee_ops.py, adaptada a un solo
        pasador en vez de 4 eslabones.

        Args:
            params: species, limb, proximal_len, distal_len (mm),
                rom_min_deg / rom_max_deg (opcional, override del preset),
                flexion_deg (default: punto medio del ROM),
                link_width, link_thickness (mm, proxy placeholder),
                pin_radius (mm, proxy placeholder),
                attach_to_socket (bool, default True): intenta
                    place_in_chain contra el anchor de ROLE_SOCKET; no es
                    error fatal si todavía no existe.
        """
        t0 = time.time()
        import FreeCAD
        import Part

        doc = self.get_document()
        if doc is None:
            return self.log_and_return(
                "build_limb_joint", params,
                error=RuntimeError("No hay documento FreeCAD activo")
            )

        try:
            species = params.get("species", "canine")
            limb = params.get("limb", "hind")
            preset = _get_preset(species, limb)

            rom_min = float(params.get("rom_min_deg", preset["joint_rom_deg"][0]))
            rom_max = float(params.get("rom_max_deg", preset["joint_rom_deg"][1]))
            proximal_len = float(params["proximal_len"])
            distal_len = float(params["distal_len"])
            link_width = float(params.get("link_width", 8.0))
            link_thickness = float(params.get("link_thickness", 5.0))
            pin_radius = float(params.get("pin_radius", 3.0))

            joint = SingleAxisJoint(proximal_len, distal_len, rom_min, rom_max)
            flexion_deg = float(params.get("flexion_deg", (rom_min + rom_max) / 2.0))
            clamped, was_clamped = joint.clamp_flexion(flexion_deg)
            pin, P, D = joint.joint_positions(clamped)

            def make_link(p_start, p_end, name):
                p1 = FreeCAD.Vector(p_start[0], p_start[1], 0)
                p2 = FreeCAD.Vector(p_end[0], p_end[1], 0)
                direction = p2.sub(p1)
                length = direction.Length
                if length < 1e-6:
                    return None
                angle_deg = math.degrees(math.atan2(direction.y, direction.x))
                box = Part.makeBox(length, link_width, link_thickness)
                box.rotate(FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 0, 1), angle_deg)
                box.translate(FreeCAD.Vector(
                    p1.x - link_width / 2 * math.sin(math.radians(angle_deg)),
                    p1.y + link_width / 2 * math.cos(math.radians(angle_deg)), 0))
                obj = doc.addObject("Part::Feature", name)
                obj.Shape = box
                return obj

            proximal_link = make_link(P, pin, "LimbJoint_proximal")
            distal_link = make_link(pin, D, "LimbJoint_distal")

            pin_cyl = Part.makeCylinder(pin_radius, link_thickness * 1.5,
                                         FreeCAD.Vector(pin[0], pin[1], -link_thickness * 0.25))
            pin_obj = doc.addObject("Part::Feature", "LimbJoint_pin")
            pin_obj.Shape = pin_cyl

            self.recompute(doc)

            attach_note = ""
            if params.get("attach_to_socket", True) and proximal_link is not None:
                err = self.place_in_chain(proximal_link, self.ROLE_SOCKET)
                attach_note = err if err else "posicionado en salida de socket"
                # El pasador y el eslabón distal comparten el mismo sistema
                # local que el proximal (todos se construyeron en el mismo
                # frame antes del recompute), así que basta reposicionar el
                # proximal para que el conjunto quede coherente -- NO se
                # llama place_in_chain tres veces con el mismo anchor, para
                # no perder la relación geométrica relativa entre los tres.
                if attach_note.startswith("posicionado"):
                    delta = proximal_link.Placement
                    if pin_obj is not None:
                        pin_obj.Placement = delta.multiply(pin_obj.Placement)
                    if distal_link is not None:
                        distal_link.Placement = delta.multiply(distal_link.Placement)

            rom_note = f" ADVERTENCIA: flexion_deg={flexion_deg:.1f} fuera de ROM, recortado a {clamped:.1f}." if was_clamped else ""

            # Registrar salida para lo que venga después (pylon). Face2 del
            # eslabón distal es el extremo lejos del pasador -- confirmar con
            # inspección de caras si cambian mucho las proporciones, igual
            # nota de cautela que dejó four_bar_knee_ops.py para su Face2.
            if distal_link is not None:
                anchor = self.register_output_anchor(
                    distal_link, self.ROLE_LIMB_JOINT, face_name="Face2"
                )
                if anchor is None:
                    attach_note += " | ADVERTENCIA: no se pudo registrar el anchor de salida (Face2 inválida para FlatFace)"

            result = (
                f"Bisagra de miembro creada ({species}/{limb}, {preset['typical_joint']}). "
                f"flexion={clamped:.1f}deg (ROM=[{rom_min:.1f},{rom_max:.1f}]).{rom_note} "
                f"Anchor: {attach_note or 'no solicitado'}."
            )
            return self.log_and_return(
                "build_limb_joint", params, result=result, duration=time.time() - t0
            )
        except Exception as e:
            return self.log_and_return(
                "build_limb_joint", params, error=e, duration=time.time() - t0
            )


# ---------------------------------------------------------------------------
# 4. Punto de entrada de ejemplo
# ---------------------------------------------------------------------------

def example_canine_hind():
    """Caso de referencia: perro, miembro trasero, prótesis a nivel de stifle/hock."""
    preset = _get_preset("canine", "hind")
    joint = SingleAxisJoint(
        proximal_len=60.0, distal_len=50.0,
        rom_min_deg=preset["joint_rom_deg"][0],
        rom_max_deg=preset["joint_rom_deg"][1],
    )
    clamped, was_clamped = joint.clamp_flexion(90.0)
    pin, P, D = joint.joint_positions(clamped)
    print(f"preset={preset}")
    print(f"flexion={clamped}deg (recortado={was_clamped}), pin={pin}, P={P}, D={D}")
    return joint


if __name__ == "__main__":
    example_canine_hind()
