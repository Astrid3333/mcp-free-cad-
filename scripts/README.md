# scripts/

Parches puntuales usados para agregar handlers nuevos al bridge sin editar a
mano `AICopilot/handlers/__init__.py`, `AICopilot/freecad_mcp_handler.py` y
`freecad_mcp_server.py` en simultáneo.

Ya fueron aplicados — el código que generan está commiteado en el repo
principal. Quedan como referencia/plantilla por si se agrega otro paquete
de handlers de una sola vez.

- `apply_7_tools_patch.py` — primer parche: agrega los 7 handlers de
  prótesis (compliant, tendon_routing, contact_pressure, growth_socket,
  quick_connect, fitting_history, lightweight).
- `apply_remaining_patches.py` — segundo parche: cierra dos huecos que
  dejó el primero.
