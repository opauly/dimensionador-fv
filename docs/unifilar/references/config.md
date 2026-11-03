# Esquema del JSON de configuración

Todos los campos son opcionales; los que falten toman el valor por defecto de `DEFAULTS` en `scripts/generate_unifilar.py`.
Los textos se dibujan tal cual, así que escribe los calibres con el formato que quieres ver ("L1 #4 AWG negro").
Usa solo caracteres Latin-1 (acentos, ×, ·, °); evita "−", "→", "≥" y subíndices Unicode: Helvetica no los tiene.

| Clave | Campos | Notas |
|---|---|---|
| `project` | `name`, `client`, `location`, `date`, `revision`, `draft`, `responsible` | `name` va en el cajetín (p. ej. "Proyecto María José Castro en Carrillo, Guanacaste"). `date` en ISO (2026-10-27). |
| `pv` | `strings` (1 o 2), `modules_per_string`, `module_w`, `module_label`, `roof_m2`, `string_breaker`, `dc_wire`, `ground_wire` | `strings` = número de MPPT usados. `string_breaker` p. ej. "32 A 2P DC". `dc_wire` p. ej. "#10 SOLAR" (se dibuja "+ #10 SOLAR" y "- #10 SOLAR"). |
| `fronius` | `label`, `kw`, `ac_breaker`, `ac_conductors` (lista), `ground_wire` | Sin neutro en `ac_conductors`. `ac_breaker` p. ej. "2P 60 A". |
| `multis` | `label`, `model`, `ac_in_breaker`, `ac_in_conductors`, `ac_out_conductors`, `dc_pos`, `dc_neg`, `ground_wire`, `dc_fuse_labels` | Siempre 2 unidades en split-phase. `dc_fuse_labels` solo se usa con Distributor. |
| `battery` | `count` (1-6; máx. 4 con Distributor), `label`, `short`, `kwh_each`, `fuse_prefix`, `can_master`, `lynx` (`power_in` o `power_in_distributor`), `cables_note` (lista de hasta 3 líneas) | `cables_note` se muestra junto al banco; pon los calibres reales si la BOM los trae. |
| `gx` | `label`, `power_breaker`, `power_note` | Alimentación DC del Ekrano. |
| `export` | `grid_zero` o `inyeccion` | Cambia el texto del Ekrano y el subtítulo. |
| `subpanel` | `q2`, `q4`, `spd` (texto o `null`), `loads` (2 líneas) | `spd: null` omite el supresor. |
| `grid` | `voltage` | Texto bajo "RED ELÉCTRICA". |
| `comms_notes` | `vebus`, `can`, `eth` | Rótulos de las líneas azules. |

Ejemplo completo: `assets/ejemplo_maria_jose.json`.
