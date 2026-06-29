# freecad-mcp-organic

Fork de [blwfish/freecad-mcp](https://github.com/blwfish/freecad-mcp) con tres herramientas adicionales orientadas a **geometría orgánica y freeform**: formas que no pueden representarse con primitivos rígidos como cajas, cilindros o esferas.

Casos de uso principales: prótesis, arquitectura biomórfica, ergonomía, escultura paramétrica, mobiliario orgánico, piezas industriales con transiciones suaves.

---

## Herramientas añadidas

### `fillet_chamfer`
Filetes y chaflanes completamente automatizados — **sin selección manual en la GUI**.

**Ventajas sobre el `partdesign_operations` original:**
- Selección de aristas por nombre (`Edge1`, `Edge3`), lista, o filtro topológico (`all_convex`, `all_concave`, `loop_from:Edge3`)
- Radio variable por arista: `{"Edge1": 2.0, "Edge7": 5.0}`
- Chaflán asimétrico: modo `distance_angle` o `two_distances`
- Propagación tangencial automática
- Continuidad G1 o G2 (curvatura continua para formas orgánicas)
- `preview_edges` para listar aristas antes de seleccionar

```json
{
  "operation": "variable_fillet",
  "doc_name": "Socket",
  "object_name": "Body",
  "edges": ["Edge3", "Edge7", "Edge11"],
  "radius_map": {"Edge3": 8.0, "Edge7": 4.0, "Edge11": 2.0},
  "continuity": "G2"
}
```

---

### `organic_operations`
Modelado sólido freeform: curvas B-spline, superficies NURBS, loft orgánico con control de curvatura, sweep sobre spines curvos, y construcción de sólidos desde secciones transversales anatómicas.

**Operaciones:**
- `bspline_curve` / `bezier_curve` / `interpolated_curve`
- `bspline_surface` — superficie NURBS desde grid de puntos de control
- `ruling_surface` — interpolación lineal entre dos curvas
- `filling_surface` — parche G1/G2 que rellena un borde cerrado
- `organic_loft` — loft entre perfiles con spine curvo y continuidad G2
- `organic_sweep` — sweep con corrección de normal a lo largo de B-spline
- `skin_solid` — sólido desde un stack de wires con superficie C2
- `cross_section_stack` — **ideal para formas anatómicas**: define el sólido como una secuencia de secciones transversales con posición, forma (círculo, elipse, rect redondeado) y twist

```json
{
  "operation": "cross_section_stack",
  "doc_name": "Socket",
  "name": "SocketBody",
  "axis": "z",
  "continuity": "G2",
  "sections": [
    {"position": 0,   "shape": "ellipse",       "width": 82, "height": 68},
    {"position": 40,  "shape": "ellipse",       "width": 75, "height": 62},
    {"position": 90,  "shape": "rounded_rect",  "width": 65, "height": 50, "corner_radius": 14},
    {"position": 150, "shape": "rounded_rect",  "width": 55, "height": 42, "corner_radius": 10},
    {"position": 210, "shape": "circle",        "width": 38, "height": 38}
  ]
}
```

- `offset_surface` — offset de shell con espesor variable por zona
- `blend_surface` — superficie de transición G2 entre dos caras existentes
- `point_cloud_surface` — NURBS fitteado a nube de puntos 3D
- `section_profiles` — genera sketches de sección a lo largo de un spine

---

### `surface_operations`
Workbench de superficies y análisis de shell: parches de relleno, análisis de curvatura, ángulo de desmoldeo, espesor mínimo de pared, costura de shells, y reparación topológica.

**Operaciones:**
- `filling` / `geom_filling` — relleno de hueco con continuidad G0/G1/G2
- `sewing` — costura de superficies separadas en shell cerrado
- `thicken` — shell → sólido con espesor uniforme o variable
- `curvature_analysis` — curvatura Gaussiana y media por cara
- `draft_angle_analysis` — verificación de ángulos de voladizo respecto a dirección de impresión
- `thickness_analysis` — mapa de espesor mínimo de pared (crítico para prótesis)
- `repair_shape` — ShapeFix de OCCT: sana intersecciones, aristas malas, wires abiertos
- `close_shell` / `offset_shell` / `simplify_surface`
- `extract_face` / `extract_shell`

```json
{
  "operation": "thickness_analysis",
  "doc_name": "Socket",
  "object_name": "SocketBody",
  "min_thickness": 2.5
}
```

---

## Flujo típico para geometría orgánica

```
1. organic_operations(cross_section_stack)   → sólido base desde medidas
2. fillet_chamfer(variable_fillet)           → transiciones suaves entre zonas
3. surface_operations(draft_angle_analysis)  → verificar imprimibilidad
4. surface_operations(thickness_analysis)    → verificar espesor mínimo
5. mesh_operations(export STL)               → exportar para impresión
```

---

## Instalación

Igual que el original blwfish. Reemplaza `freecad_mcp_server.py` en tu instalación:

```bash
# Clonar este fork
git clone https://github.com/Astrid3333/freecad-mcp-organic
cd freecad-mcp-organic

# Instalar el addon AICopilot en FreeCAD (igual que el original)
# Ver INSTALL.md del repo original
```

En `claude_desktop_config.json`:
```json
"freecad": {
  "command": "/bin/bash",
  "args": ["-c", "python3 /ruta/a/freecad-mcp-organic/freecad_mcp_server.py"]
}
```

---

## Estado

| Tool | Schema | Handler en FreeCAD |
|------|--------|--------------------|
| `fillet_chamfer` | ✅ completo | 🔧 requiere addon AICopilot actualizado |
| `organic_operations` | ✅ completo | 🔧 requiere addon AICopilot actualizado |
| `surface_operations` | ✅ completo | 🔧 requiere addon AICopilot actualizado |

El MCP bridge (este archivo) está completo. Los handlers del lado FreeCAD (addon AICopilot) están en desarrollo — mientras tanto, todas las operaciones son ejecutables vía `execute_python` con el código Python generado por Claude.

---

## Créditos

Basado en [blwfish/freecad-mcp](https://github.com/blwfish/freecad-mcp) (licencia GPL-3.0).
Fork por [@Astrid3333](https://github.com/Astrid3333).
