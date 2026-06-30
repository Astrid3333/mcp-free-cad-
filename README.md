# FreeCAD MCP (mcp-free-cad-)

Servidor MCP que conecta Claude con FreeCAD para modelado paramétrico, operaciones
orgánicas/freeform, CAM, e inspección de geometría — directamente desde el chat.

## Componentes

- **`freecad_mcp_server.py`** (+ `mcp_bridge_framing.py`, `freecad_crash_report.py`):
  el servidor MCP que corre como proceso de Claude Desktop/Code.
- **`AICopilot/`**: el addon que se instala dentro de FreeCAD. Abre un socket Unix
  local y expone la API que usa el bridge para crear/editar geometría.

Ambas mitades son necesarias. Sin el addon instalado en FreeCAD, el bridge no tiene
con quién hablar.

## Instalación

### 1. Addon dentro de FreeCAD

Copiá (o symlinkeá) la carpeta `AICopilot/` a tu directorio `Mod` de FreeCAD:

```bash
# FreeCAD nativo (paquete del sistema)
cp -r AICopilot ~/.local/share/FreeCAD/Mod/AICopilot

# FreeCAD vía Flatpak
cp -r AICopilot ~/.var/app/org.freecad.FreeCAD/data/FreeCAD/v1-1/Mod/AICopilot
```

Reiniciá FreeCAD. Si arrancó bien, en la consola Python de FreeCAD vas a ver:
`AI Socket Server started - Claude ready`.

#### ⚠️ Si usás FreeCAD vía Flatpak

El sandbox del flatpak bloquea por defecto el acceso a `/tmp` y `~/.cache` del
sistema host, donde el addon escribe el socket y el archivo de discovery que el
bridge necesita para encontrarlo. Corré esto una sola vez:

```bash
flatpak override --user --filesystem=/tmp --filesystem=xdg-cache org.freecad.FreeCAD
```

Y reiniciá FreeCAD para que tome el nuevo permiso.

### 2. Bridge en Claude Desktop / Claude Code

Agregá esto a tu `claude_desktop_config.json` (en Claude Desktop: Settings →
Developer → Edit Config):

```json
{
  "mcpServers": {
    "freecad-organic": {
      "command": "python3",
      "args": ["/ruta/absoluta/a/mcp-free-cad-/freecad_mcp_server.py"]
    }
  }
}
```

Reiniciá Claude Desktop.

## Verificar la conexión

Desde Claude, pedile que llame a `check_freecad_connection`. Si todo está bien
configurado debería reportar la instancia de FreeCAD activa con su socket.

## Inspector (DRC checks) — opcional

`run_inspector` requiere [FC-tools](https://github.com/) instalado por separado.
Configurá la ruta con la variable de entorno:

```bash
export FREECAD_INSPECTOR_PATH=/ruta/a/FC-tools
```

o la preferencia de FreeCAD `Mod/AICopilot → InspectorPath`.

## Estado de las herramientas

La mayoría de las operaciones (`part_operations`, `partdesign_operations`,
`surface_operations`, `mesh_operations`, `draft_operations`, `cam_operations`,
`spatial_query`, `execute_python`) están implementadas y probadas.

`organic_operations` (B-splines, NURBS, organic loft/sweep, cross-section stacks)
está en desarrollo activo — el esquema ya está expuesto pero los handlers
todavía se están completando.

## Troubleshooting

- **"Unknown tool" en alguna operación**: el handler correspondiente no está
  implementado aún. Revisá `AICopilot/handlers/` para ver qué módulos existen.
- **`check_freecad_connection` no encuentra nada**: confirmá que FreeCAD está
  abierto con GUI (no en modo `freecadcmd`) y que el addon cargó sin errores
  (revisá la consola Python de FreeCAD al arrancar).
