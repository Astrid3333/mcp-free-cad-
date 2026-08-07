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
tiene el core geométrico validado contra una instancia FreeCAD real (incluye
un fix de torsión espuria vía rotation-minimizing frame). Sigue siendo
screening geométrico, no reemplaza una simulación FEA validada.

## Pipeline de prótesis (organic_operations)

Además de las operaciones estándar de FreeCAD, este bridge expone un grupo de
handlers pensados específicamente para diseño de sockets protésicos y
mecanismos asociados (geometría orgánica, encaje con el muñón, mecanismos
articulados).

| Handler | Qué hace | Estado |
|---|---|---|
| `organic_operations` | Loft/sweep orgánico, stacks de secciones transversales (`cross_section_stack`), perfiles circulares/elípticos/poligonales/spline, `organic_sweep` a lo largo de una curva | Core validado en vivo |
| `mesh_repair_operations` | Detección y parcheo de huecos en mallas escaneadas (STL/PLY) | Wireado y validado |
| `print_segmentation_operations` | Segmentación de piezas para impresión 3D | Wireado |
| `cosmetic_shell_operations` | Shells cosméticos (cobertura externa no estructural) | Wireado |
| `finger_segment_operations` | Cadena de falanges protésicas + `create_stump_socket` (interfaz mecánica con el muñón residual) | Wireado y extendido |
| `quadruped_limb_operations` | Prótesis/ortesis de miembro para cuadrúpedos (perro/gato/equino) — bisagra single-axis con ROM por especie | Wireado |
| `materials_operations` | Base de datos de propiedades de materiales, tagging de zonas por cara, recomendación de densidad desde mapa de presión | Wireado y validado end-to-end |
| `growth_socket_operations` | Sockets telescópicos/anidados para uso pediátrico: shell exterior + familia de liners de distintos tamaños para acompañar el crecimiento | En desarrollo activo — validar a ojo |
| `contact_pressure_operations` | Screening geométrico (NO es FEA) del ajuste socket–muñón: muestreo de holgura sobre la superficie interna y agrupamiento en zonas de riesgo | En desarrollo activo — validar a ojo |
| `compliant_operations` | Bisagras vivas / juntas compliant para mecanismos flexibles (dedos segmentados, etc.), con recomendación de espesor derivado de material y ciclos esperados | En desarrollo activo — validar a ojo |
| `tendon_routing_operations` | Planificación de recorrido de tendones: anclajes, radio de curvatura mínimo, chequeo de colisión del cableado con el material sólido | En desarrollo activo — validar a ojo |
| `four_bar_knee_operations` | Síntesis cinemática de rodilla policéntrica de cuatro barras (condición de Grashof, trayectoria del ICR) antes de generar la geometría | En desarrollo activo — validar a ojo |
| `quick_connect_operations` | Conectores rápidos socket↔dispositivo terminal: pares bayoneta o roscados, con retención magnética opcional | En desarrollo activo — validar a ojo |
| `lightweight_operations` | Recomendación de densidad de relleno/lattice guiada por la trayectoria de carga aproximada, para aligerar piezas sin perder resistencia (screening geométrico, no reemplaza un ensayo físico) | En desarrollo activo — validar a ojo |
| `fitting_history_operations` | Bitácora de sesiones de prueba por paciente (identificado solo por código no-PII): snapshot de geometría + notas estructuradas, comparación contra la última sesión | En desarrollo activo — validar a ojo |

Todos estos módulos son **screenings geométricos de primer paso**, no
sustituyen simulación FEA validada ni criterio clínico. `fitting_history_operations`
requiere que `patient_id` sea siempre un código no identificable (iniciales +
número), nunca un dato personal real.

## Troubleshooting

- **"Unknown tool" en alguna operación**: el handler correspondiente no está
  implementado aún. Revisá `AICopilot/handlers/` para ver qué módulos existen.
- **`check_freecad_connection` no encuentra nada**: confirmá que FreeCAD está
  abierto con GUI (no en modo `freecadcmd`) y que el addon cargó sin errores
  (revisá la consola Python de FreeCAD al arrancar).

