"""
socket_qa_engine.py
QA automatizado para modelos de socket protésico.
Usa ValidationOpsHandler directamente (sin pasar por el servidor MCP),
pensado para correr dentro de la consola Python de FreeCAD o como macro.
"""

import json
import sys

# Ajustar el path al repo si el script se corre fuera del contexto del plugin
sys.path.insert(0, "/ruta/a/mcp-free-cad-/AICopilot")  # <-- ajustar

from handlers.validation_operations import ValidationOpsHandler


def _call(handler, method_name, args):
    """Invoca un método del handler y parsea el JSON de retorno {ok, details, message}."""
    method = getattr(handler, method_name)
    raw = method(args)
    parsed = json.loads(raw)
    if not parsed.get("ok", False):
        print(f"⚠️  {method_name} falló: {parsed.get('message')}")
    return parsed.get("details", {})


def run_socket_qa(shape_name=None, mesh_name=None, socket_name=None, verbose=True):
    """
    Corre el pipeline de QA sobre un socket:
    validate_solid -> validate_material_zone -> validate_socket_workflow -> report_validation

    shape_name: nombre del objeto Shape (para validate_solid / validate_material_zone)
    mesh_name: nombre del objeto Mesh (opcional, para validate_mesh)
    socket_name: nombre del objeto Socket (para validate_socket_workflow)
    """
    handler = ValidationOpsHandler()
    findings = []

    # 1. Validación geométrica del sólido
    if shape_name:
        solid_details = _call(handler, "validate_solid", {"shape": shape_name})
        findings.extend(solid_details.get("findings", []))

        mat_details = _call(handler, "validate_material_zone", {"shape": shape_name})
        findings.extend(mat_details.get("findings", []))

    # 2. Validación de malla (si aplica)
    if mesh_name:
        mesh_details = _call(handler, "validate_mesh", {"mesh": mesh_name, "check_watertight": True})
        findings.extend(mesh_details.get("findings", []))

    # 3. Validación del flujo completo del socket
    if socket_name:
        workflow_details = _call(handler, "validate_socket_workflow", {"socket": socket_name, "material_zones": True})
        findings.extend(workflow_details.get("findings", []))

    # 4. Reporte agregado (FAIL / PROCEED_WITH_CAUTION / PASS)
    report_details = _call(handler, "report_validation", {"findings": findings})
    status = report_details.get("status", "UNKNOWN")

    if verbose:
        print(json.dumps({"status": status, "findings": findings}, indent=2, ensure_ascii=False))
        icon = {"FAIL": "❌", "PROCEED_WITH_CAUTION": "⚠️", "PASS": "✅"}.get(status, "❓")
        print(f"\n{icon} QA status: {status}")

    return {"status": status, "findings": findings}


if __name__ == "__main__":
    # Ejemplo — ajustar nombres de objeto reales del documento activo
    run_socket_qa(shape_name="Socket", socket_name="Socket")
