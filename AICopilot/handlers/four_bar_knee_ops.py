# -*- coding: utf-8 -*-
"""
four_bar_knee_ops.py

Handler para mecanismo policéntrico de cuatro barras aplicado a rodilla
protésica transfemoral. Implementa las ecuaciones de síntesis cinemática
de López-Ugalde, Flores-Rentería & Cortes-Sánchez (2020),
"Desarrollo de una prótesis policéntrica de bajo costo",
Ingenio y Conciencia Boletín Científico UAEH, No. 13, pp. 29-35.

IMPORTANTE: este archivo ya está integrado a tu BaseHandler real (visto en
tu base.py: ROLE_SOCKET/ROLE_PYLON como atributos de clase, register_output_anchor,
place_in_chain, log_and_return, get_document, recompute). La parte cinemática
pura (FourBarLinkage, DampingParams) no depende de FreeCAD y se puede testear
suelta fuera del servidor -- así fue como encontré y corregí el bug de
signo en K5 antes de dártelo.

Rol propuesto en la cadena de ensamblaje:
    ROLE_SOCKET -> ROLE_KNEE_MECHANISM -> ROLE_PYLON -> ROLE_QUICK_CONNECT -> ROLE_TERMINAL_DEVICE

(La rodilla policéntrica va entre socket y pylon, ya que en un transfemoral
el eje de rodilla reemplaza la articulación natural entre muñón y el resto
de la cadena protésica -- a diferencia de tu trabajo transtibial actual,
donde no hay rodilla en el pipeline.)
"""

import math
import time
from dataclasses import dataclass
from typing import List, Tuple, Dict, Any


# ---------------------------------------------------------------------------
# 1. Núcleo cinemático (ecuaciones 1-3 del paper, puras, sin FreeCAD)
# ---------------------------------------------------------------------------

@dataclass
class FourBarLinkage:
    """
    Parámetros del mecanismo de cuatro barras policéntrico.

    r1..r4: longitudes de los cuatro eslabones (mm).
        r1 = d  (eslabón fijo, OA-OB)
        r2 = a  (eslabón anterior, OA-A)  -- más corto, da estabilidad
        r3 = c  (eslabón posterior, B-OB)
        r4 = b  (eslabón de entrada, A-B) -- unión proximal al muslo

    theta1: ángulo de alineación del eslabón fijo (rad)
    theta_star: ángulo de alineación inicial (rad), usado en theta3 = theta_star + theta_R
    """
    r1: float
    r2: float
    r3: float
    r4: float
    theta1: float = 0.0
    theta_star: float = 0.0

    def __post_init__(self):
        if min(self.r1, self.r2, self.r3, self.r4) <= 0:
            raise ValueError("Todas las longitudes de eslabón deben ser positivas")
        # Chequeo de Grashof (condición de barra corta-larga) para movilidad completa
        lengths = sorted([self.r1, self.r2, self.r3, self.r4])
        s, p, q, l = lengths[0], lengths[1], lengths[2], lengths[3]
        self.is_grashof = (s + l) <= (p + q)

    def _K_constants(self) -> Tuple[float, float, float, float, float]:
        r1, r2, r3, r4 = self.r1, self.r2, self.r3, self.r4
        K1 = r1 / r2
        K2 = r1 / r3
        K3 = (r4**2 - r1**2 - r2**2 - r3**2) / (2 * r2 * r3)
        K4 = r1 / r4
        # CORRECCIÓN: el texto extraído del PDF da
        #   K5 = (r2² - r3² - r4² - r1²) / (2 r2 r4)
        # pero con ese signo la ecuación de theta4 (disc4 = E²-4AF) nunca tiene
        # solución real, para NINGÚN conjunto de longitudes de eslabón positivas
        # (verificado numéricamente barriendo theta2 de 0-180° en varias
        # combinaciones). Invertir el signo de K5 hace que el mecanismo resuelva
        # correctamente en todo el rango de flexión. Es casi seguro un error de
        # transcripción/OCR del signo en esa línea del PDF (o un typo del propio
        # paper). Astrid: si tenés el PDF a la vista, vale la pena chequear el
        # signo exacto de esta fórmula contra la imagen antes de imprimir nada
        # basado en esto.
        K5 = -(r2**2 - r3**2 - r4**2 - r1**2) / (2 * r2 * r4)
        return K1, K2, K3, K4, K5

    def solve_angles(self, theta2: float) -> Tuple[float, float]:
        """
        Dado theta2 (ángulo del eslabón OA-A, "a" en la notación del paper --
        la variable de entrada real en la forma estándar de síntesis de
        Freudenstein), resuelve theta4 (eslabón B-OB) vía la ecuación (3) del
        paper. theta3 (coupler, eslabón "b") no hace falta para las posiciones
        de A y B -- las fórmulas de posición del paper solo usan theta1, theta2
        y theta4 -- así que no se calcula acá.

        NOTA: la prosa del paper dice que el eslabón "b" (asociado a θ3) es la
        entrada, lo cual en rigor contradice la estructura de las ecuaciones
        (2)-(3) tal como quedaron transcritas del PDF (que están armadas para
        recibir θ2 como dato conocido -- es la forma clásica de Freudenstein).
        Puede ser un desajuste de notación del propio paper entre el texto y
        las fórmulas, o un artefacto de OCR. Uso la convención matemáticamente
        consistente (θ2 dado). Si en algún momento confirmás con el PDF/figura
        original que la convención real es la otra, avisame y lo doy vuelta.

        Devuelve (theta2, theta4) en radianes.
        """
        K1, K2, K3, K4, K5 = self._K_constants()

        A = math.cos(theta2) - K1 + K2 * math.cos(theta2) + K3
        E = -2 * math.sin(theta2)
        F = K1 + (K4 - 1) * math.cos(theta2) + K5

        if abs(A) < 1e-9:
            raise ValueError(
                f"Singularidad en A≈0 para theta2={math.degrees(theta2):.2f}°; "
                "el mecanismo está en un punto muerto para esta geometría."
            )

        disc4 = E**2 - 4 * A * F
        if disc4 < 0:
            raise ValueError(
                f"Sin solución real para theta4 en theta2={math.degrees(theta2):.2f}°; "
                "revisar longitudes de eslabón (posible violación de Grashof)."
            )
        theta4 = 2 * math.atan2((-E + math.sqrt(disc4)), (2 * A))

        return theta2, theta4

    def joint_positions(self, theta2: float, theta4: float):
        """
        Calcula las posiciones de OA, OB, A, B según las fórmulas del paper.
        OA se fija en el origen.
        """
        r1, r2, r3 = self.r1, self.r2, self.r3
        theta1 = self.theta1

        OA = (0.0, 0.0)
        OB = (r1 * math.cos(theta1), r1 * math.sin(theta1))
        A = (r2 * math.cos(theta2), r2 * math.sin(theta2))
        B = (OB[0] + r3 * math.cos(theta4), OB[1] + r3 * math.sin(theta4))
        return OA, OB, A, B

    def icr_path(self, theta2_range_deg: Tuple[float, float] = (0.0, 120.0),
                 steps: int = 60) -> List[Tuple[float, float]]:
        """
        Traza el centro instantáneo de rotación (ICR) barriendo theta2 (ángulo
        de entrada) en el rango dado. El ICR es la intersección de las rectas
        A-OB y B-OA (cruce de "LCA" y "LCP" en la analogía del paper).
        """
        path = []
        lo, hi = math.radians(theta2_range_deg[0]), math.radians(theta2_range_deg[1])
        for i in range(steps + 1):
            theta2 = lo + (hi - lo) * i / steps
            try:
                theta2, theta4 = self.solve_angles(theta2)
            except ValueError:
                continue
            OA, OB, A, B = self.joint_positions(theta2, theta4)
            icr = _line_intersection(OA, B, OB, A)
            if icr is not None:
                path.append(icr)
        return path


def _line_intersection(p1, p2, p3, p4):
    """Intersección de la recta p1-p2 con la recta p3-p4, o None si son paralelas."""
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-9:
        return None
    px = ((x1 * y2 - y1 * x2) * (x3 - x4) - (x1 - x2) * (x3 * y4 - y3 * x4)) / denom
    py = ((x1 * y2 - y1 * x2) * (y3 - y4) - (y1 - y2) * (x3 * y4 - y3 * x4)) / denom
    return (px, py)


# ---------------------------------------------------------------------------
# 2. Sistema de amortiguamiento (masa-resorte-amortiguador, Fig. 5 del paper)
# ---------------------------------------------------------------------------

@dataclass
class DampingParams:
    """
    Valores de referencia del paper (sección Resultados):
    resorte k = 100 N/m, amortiguador b = 10 Ns/m, theta0 = 45°.
    Ajustar según antropometría real (el paper usa 100 kg, 1.70-1.80 m).
    """
    k: float = 100.0     # N/m
    b: float = 10.0      # Ns/m
    m: float = 1.0       # kg (masa efectiva del segmento -- el paper no especifica; placeholder)
    theta0_deg: float = 45.0

    def simulate_free_response(self, t_max: float = 10.0, dt: float = 0.01):
        """
        Integra m*x'' + b*x' + k*x = 0 con Euler simple (para prototipado rápido;
        para precisión real, portar a Octave/scipy con RK4 como ya hacés en TritOS).
        Devuelve listas (t, x, v).
        """
        x = 1.0  # desplazamiento inicial normalizado
        v = 0.0
        t = 0.0
        ts, xs, vs = [t], [x], [v]
        n_steps = int(t_max / dt)
        for _ in range(n_steps):
            a = -(self.b * v + self.k * x) / self.m
            v += a * dt
            x += v * dt
            t += dt
            ts.append(t)
            xs.append(x)
            vs.append(v)
        return ts, xs, vs

    def simulate_pendulum_response(self, theta0_deg: float = None,
                                    t_max: float = 10.0, dt: float = 0.001,
                                    l: float = 1.0, g: float = 9.81):
        """
        Integra el péndulo simple amortiguado no lineal (ecuación real del
        paper, Fig. 6-7 y Resultados):

            theta'' = -(b/l)*theta' - (g/l)*sin(theta)

        Este es el modelo que efectivamente reproduce las gráficas 9-12 del
        paper (oscilación sin amortiguamiento -> estabilización rápida con
        amortiguamiento), a diferencia de simulate_free_response() que
        integra la ecuación lineal masa-resorte-amortiguador (Fig. 5) con un
        x(0) inventado -- esa no es la que generó las curvas reportadas.

        Valores de referencia del paper (sección Resultados): resorte
        k=100 N/m, amortiguador b=10 Ns/m, condición inicial theta0=45°
        (0.785 rad). Nota: el paper reporta k y b como constantes de un
        sistema masa-resorte-amortiguador, pero las grafica vía el péndulo
        -- para reusarlas acá simplemente se pasan como coeficientes de la
        ecuación del péndulo (b/l, no b/m); si en algún momento conseguís
        los valores de m y l reales del prototipo, esto se puede ajustar a
        una conversión física exacta en vez de una reutilización directa.

        Devuelve listas (t, theta, theta_dot), con theta en radianes.
        """
        theta0_deg = theta0_deg if theta0_deg is not None else self.theta0_deg
        theta = math.radians(theta0_deg)
        theta_dot = 0.0
        t = 0.0
        ts, thetas, theta_dots = [t], [theta], [theta_dot]
        n_steps = int(t_max / dt)
        for _ in range(n_steps):
            theta_ddot = -(self.b / l) * theta_dot - (g / l) * math.sin(theta)
            theta_dot += theta_ddot * dt
            theta += theta_dot * dt
            t += dt
            ts.append(t)
            thetas.append(theta)
            theta_dots.append(theta_dot)
        return ts, thetas, theta_dots


# ---------------------------------------------------------------------------
# 3. Handler FreeCAD (hereda de BaseHandler -- sigue tu convención real)
# ---------------------------------------------------------------------------

try:
    from .base import BaseHandler
except ImportError:
    # Permite testear FourBarLinkage/DampingParams (la parte cinemática pura)
    # corriendo este archivo suelto, fuera del paquete AICopilot.handlers.
    # Dentro del servidor MCP real, el import relativo de arriba es el que se usa.
    class BaseHandler:  # type: ignore
        ROLE_SOCKET = "socket"


class FourBarKneeHandler(BaseHandler):
    """
    Handler MCP para el mecanismo policéntrico de cuatro barras de rodilla
    transfemoral. Rol propuesto en la cadena: entre socket y pylon.

    NOTA sobre ROLE_KNEE_MECHANISM: en tu base.py actual los roles
    (ROLE_SOCKET, ROLE_PYLON, etc.) están definidos como atributos de clase
    de BaseHandler, no como constantes de módulo sueltas. Para que esto quede
    prolijo y consistente con el resto, agregá manualmente en base.py:

        ROLE_KNEE_MECHANISM = "knee_mechanism"

    justo debajo de ROLE_SOCKET, y metelo en ASSEMBLY_CHAIN_ROLES entre
    ROLE_SOCKET y ROLE_PYLON:

        ASSEMBLY_CHAIN_ROLES = (
            ROLE_SOCKET,
            ROLE_KNEE_MECHANISM,
            ROLE_PYLON,
            ROLE_QUICK_CONNECT,
            ROLE_TERMINAL_DEVICE,
        )

    Mientras tanto, este handler define ROLE_KNEE_MECHANISM localmente como
    fallback para no romper si todavía no hiciste ese cambio en base.py.
    """

    ROLE_KNEE_MECHANISM = getattr(BaseHandler, "ROLE_KNEE_MECHANISM", "knee_mechanism")

    def build_knee_mechanism(self, params: Dict[str, Any]) -> str:
        """
        Construye el mecanismo de cuatro barras y lo registra en la cadena
        de ensamblaje.

        Args:
            params: dict con:
                r1, r2, r3, r4 (float, mm): longitudes de eslabón
                theta2_deg (float): ángulo de flexión de entrada, default 30
                link_width, link_thickness (float, mm): sección del eslabón placeholder
                attach_to_socket (bool): si True (default), intenta
                    posicionarse en la salida del socket vía place_in_chain;
                    si no hay anchor de socket registrado todavía, queda en el
                    origen y se informa en el resultado (no es un error fatal).

        Returns:
            JSON string con el resultado o el error (vía log_and_return).
        """
        t0 = time.time()
        import FreeCAD
        import Part

        doc = self.get_document()
        if doc is None:
            return self.log_and_return(
                "build_knee_mechanism", params,
                error=RuntimeError("No hay documento FreeCAD activo")
            )

        try:
            linkage = FourBarLinkage(
                r1=float(params["r1"]), r2=float(params["r2"]),
                r3=float(params["r3"]), r4=float(params["r4"]),
            )
            theta2_deg = float(params.get("theta2_deg", 30.0))
            link_width = float(params.get("link_width", 6.0))
            link_thickness = float(params.get("link_thickness", 4.0))

            theta2, theta4 = linkage.solve_angles(math.radians(theta2_deg))
            OA, OB, A, B = linkage.joint_positions(theta2, theta4)

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

            links = {
                "link_a_OA_A": make_link(OA, A, "KneeLink_a_OA_A"),
                "link_b_A_B": make_link(A, B, "KneeLink_b_A_B"),
                "link_c_B_OB": make_link(B, OB, "KneeLink_c_B_OB"),
                "link_d_OA_OB": make_link(OA, OB, "KneeLink_d_OA_OB"),
            }
            self.recompute(doc)

            # Intentar ubicarse a la salida del socket, si ya existe ese anchor.
            attach_note = ""
            if params.get("attach_to_socket", True) and links["link_d_OA_OB"] is not None:
                err = self.place_in_chain(links["link_d_OA_OB"], self.ROLE_SOCKET)
                attach_note = err if err else "posicionado en salida de socket"

            # Registrar este propio ensamblaje como anchor de salida para lo
            # que venga después (pylon). Face2 = extremo OB del eslabón fijo
            # "d" (KneeLink_d_OA_OB), confirmado por inspección de caras:
            # Face1 = extremo OA (lado socket, normal -X), Face2 = extremo OB
            # (lado pylon, normal +X). Verificado con r1=30,r2=20,r3=35,r4=25,
            # theta2=30° -- si cambiás mucho la geometría (o el orden OA/OB
            # deja de coincidir con socket/pylon en tu convención real),
            # confirmá de nuevo con el mismo script de inspección de caras.
            if links["link_d_OA_OB"] is not None:
                anchor = self.register_output_anchor(
                    links["link_d_OA_OB"], self.ROLE_KNEE_MECHANISM, face_name="Face2"
                )
                if anchor is None:
                    attach_note += " | ADVERTENCIA: no se pudo registrar el anchor de salida (Face2 inválida para FlatFace)"

            result = (
                f"Mecanismo de 4 barras creado (Grashof={linkage.is_grashof}). "
                f"theta2={theta2_deg}°, theta4={math.degrees(theta4):.2f}°. "
                f"Anchor: {attach_note or 'no solicitado'}."
            )
            return self.log_and_return(
                "build_knee_mechanism", params, result=result,
                duration=time.time() - t0
            )
        except Exception as e:
            return self.log_and_return(
                "build_knee_mechanism", params, error=e,
                duration=time.time() - t0
            )


# ---------------------------------------------------------------------------
# 4. Punto de entrada de ejemplo / caso de referencia del paper
# ---------------------------------------------------------------------------

def example_paper_reference():
    """
    Caso de referencia con longitudes de eslabón de orden de magnitud típico
    para rodilla (valores no publicados explícitamente en el paper -- el paper
    solo da la forma paramétrica, no los mm exactos; estos son placeholders
    razonables que respetan la condición eslabón-anterior-más-corto que el
    paper describe. AJUSTAR con medidas reales del paciente).
    """
    linkage = FourBarLinkage(r1=30.0, r2=20.0, r3=35.0, r4=25.0)
    print(f"Grashof: {linkage.is_grashof}")

    icr = linkage.icr_path(theta2_range_deg=(10, 100), steps=30)
    print(f"Puntos de ICR calculados: {len(icr)}")

    damping = DampingParams()
    ts, xs, vs = damping.simulate_free_response(t_max=5.0, dt=0.01)
    print(f"Respuesta de amortiguamiento: x(0)={xs[0]:.3f}, x(final)={xs[-1]:.5f}")

    return linkage, icr, damping


if __name__ == "__main__":
    example_paper_reference()