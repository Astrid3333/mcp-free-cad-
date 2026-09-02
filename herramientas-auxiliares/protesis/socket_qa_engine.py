"""
socket_qa_engine.py
QA automatizado para modelos de socket protésico.
Usa ValidationOpsHandler directamente (sin pasar por el servidor MCP),
pensado para correr dentro de la consola Python de FreeCAD o como macro.
"""

import sys
import json
import FreeCAD as App

# Ajustar el path al repo si el script se corre fuera del contexto del plugin
sys.path.insert(0, "/ruta/a/mcp-free-cad-/AICopilot")  # <-- ajustar

from handlers.validation_operations import ValidationOpsHandler


def _call(handler, method_name, args):
    """Invoca un método del handler y parsea su resultado (str -> dict)."""
    method = getattr(handler, method_name)
    raw = method(args)
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        # Si el método no devuelve JSON, lo envolvemos como texto plano
        return {"raw": raw}


def run_socket_qa(doc_name=None, socket_obj_name=None, verbose=True):
    """
    Corre el pipeline completo de QA sobre un socket:
    validate_solid -> validate_material_zone -> validate_socket_workflow -> report_validation
    """
    doc = App.getDocument(doc_name) if doc_name else App.ActiveDocument
    if doc is None:
        raise RuntimeError("No hay documento activo en FreeCAD.")

    handler = ValidationOpsHandler()
    findings = []

    # 1. Validación geométrica del sólido
    solid_result = _call(handler, "validate_solid", {
        "doc_name": doc.Name,
        "object_name": socket_obj_name,
    })
    findings.extend(solid_result.get("findings", []))

    # 2. Validación de zonas de material (si el objeto tiene tags)
    if socket_obj_name:
        mat_result = _call(handler, "validate_material_zone", {
            "doc_name": doc.Name,
            "object_name": socket_obj_name,
        })
        findings.extend(mat_result.get("findings", []))

    # 3. Validación del flujo completo del socket (secciones, materiales, pressure map)
    workflow_result = _call(handler, "validate_socket_workflow", {
        "doc_name": doc.Name,
    })
    findings.extend(workflow_result.get("findings", []))

    # 4. Reporte agregado (FAIL / PROCEED_WITH_CAUTION / PASS)
    report = _call(handler, "report_validation", {
        "findings": findings,
    })

    if verbose:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        status = report.get("status", "UNKNOWN")
        icon = {"FAIL": "❌", "PROCEED_WITH_CAUTION": "⚠️", "PASS": "✅"}.get(status, "❓")
        print(f"\n{icon} QA status: {status}")

    return report


if __name__ == "__main__":
    run_socket_qa()
