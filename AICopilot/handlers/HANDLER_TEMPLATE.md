# Handler Template — Estándar de Profesionalidad

Este template define el estándar mínimo para handlers profesionales en mcp-free-cad-.

## Estructura General

```python
"""module_name.py — Handler description"""
import json
from typing import Any, Dict
import FreeCAD
from .base import BaseHandler

class MyOpsHandler(BaseHandler):
    """One-line summary + multi-line description of what this handler does.
    
    This handler manages X operations across Y domain.
    """
    _ALLOWED_OPERATIONS = frozenset({"operation_1", "operation_2", ...})
    
    def operation_1(self, args: Dict[str, Any]) -> str:
        """One-line summary of the operation.
        
        Longer description explaining what the operation does, its scope,
        and any important limitations or disclaimers (e.g., "NOT a validated
        clinical tool", "approximation only", etc.).
        
        Args:
            param1 (str): Description + expected format/range.
            param2 (float): Description + units (mm, MPa, etc.).
            param3 (bool, optional): Description. Default False.
        
        Returns:
            JSON string: {"ok": bool, "details": {...}, "message": str}
                - ok: True if operation succeeded, False on error.
                - details: Dict with results (empty on error, or error details on fail).
                - message: Human-readable summary or error description.
        """
        try:
            # 1. Validate input: types, required fields, ranges
            param1 = args.get("param1", "")
            if not param1 or not isinstance(param1, str):
                return json.dumps({
                    "ok": False,
                    "details": {},
                    "message": "Missing/invalid required: param1 (string expected)"
                })
            
            try:
                param2 = float(args.get("param2"))
                if param2 < 0 or param2 > 1000:
                    return json.dumps({
                        "ok": False,
                        "details": {},
                        "message": f"param2 out of range: {param2} (expected 0-1000)"
                    })
            except (TypeError, ValueError):
                return json.dumps({
                    "ok": False,
                    "details": {},
                    "message": "Missing/invalid required: param2 (float expected)"
                })
            
            param3 = bool(args.get("param3", False))
            
            # 2. Get context (document, objects) with explicit error handling
            doc = self.get_document()
            if not doc:
                return json.dumps({
                    "ok": False,
                    "details": {},
                    "message": "No active document"
                })
            
            obj = self.get_object(param1, doc)
            if not obj or not hasattr(obj, "Shape"):
                return json.dumps({
                    "ok": False,
                    "details": {},
                    "message": f"Object not found or has no Shape: {param1}"
                })
            
            # 3. Perform operation with granular error handling
            try:
                result_value = obj.Shape.Volume  # Example calculation
            except Exception as e:
                return json.dumps({
                    "ok": False,
                    "details": {},
                    "message": f"Error calculating volume: {e}"
                })
            
            # 4. Return structured JSON response
            return json.dumps({
                "ok": True,
                "details": {
                    "param1": param1,
                    "result": round(result_value, 3),
                    "units": "mm³",
                },
                "message": f"Operation succeeded: {param1} has volume {result_value:.2f} mm³",
            })
        
        except Exception as e:
            # Catch-all for unexpected errors
            return json.dumps({
                "ok": False,
                "details": {},
                "message": f"Unexpected error in operation_1: {e}"
            })
```

## Checklist Mínima

- [ ] Docstring con descripción, Args, Returns (no guesswork)
- [ ] Validación explícita de tipos (int, float, str, bool, list)
- [ ] Rangos de valores documentados y validados
- [ ] Mensajes de error específicos (no genéricos)
- [ ] JSON output siempre: `{"ok": bool, "details": {...}, "message": str}`
- [ ] Try/except solo alrededor de llamadas a FreeCAD (que pueden fallar)
- [ ] Limitaciones explícitas en docstring (approximation, not validated, v1-only, etc.)
- [ ] Reutilización: no duplicar lógica que ya existe en otro handler
- [ ] Logging: usar FreeCADDebugger, no inventar logs nuevos

