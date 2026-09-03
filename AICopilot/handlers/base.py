# Base handler class for FreeCAD MCP operations

import os
import time
from typing import Dict, Any, Optional, Callable

# LAZY IMPORT: FreeCAD se carga solo cuando se necesita (dentro de get_document)
# Esto permite que Opción B (pytest sin FreeCAD) pueda importar los handlers


class BaseHandler:
    """Base class for all FreeCAD operation handlers.

    Provides common utilities and document access patterns.
    """

    def get_document(self):
        """Get the active FreeCAD document.
        
        Lazy-imports FreeCAD here so pytest can import handlers without FreeCAD.
        """
        import FreeCAD  # lazy import
        
        # Conditional GUI import (not available in console mode)
        if FreeCAD.GuiUp:
            import FreeCADGui
        else:
            FreeCADGui = None
        
        return FreeCAD.activeDocument()

    def get_object(self, name: str, doc):
        """Get an object from the document by name."""
        if doc is None:
            return None
        return doc.getObject(name) if hasattr(doc, 'getObject') else None

    def wait_for_server(self, timeout: int = 30) -> bool:
        """Wait for the FreeCAD server socket to be ready."""
        import FreeCAD
        start = time.time()
        while time.time() - start < timeout:
            try:
                socket_path = os.path.expanduser("~/.freecad_mcp_socket")
                if os.path.exists(socket_path):
                    return True
            except Exception:
                pass
            time.sleep(0.1)
        return False
