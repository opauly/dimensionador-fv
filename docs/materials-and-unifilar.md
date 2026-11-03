# Lista de materiales y unifilar (proyectos híbridos acoplados en AC)

Dos entregables que salen del mismo diseño y del mismo dimensionamiento (`calculations/wiring.py` vía
`webapp/wizard_steps/og_wiring.py`), así que un calibre o un breaker no puede diferir entre el plano y la
lista de compra. Todo es determinista; no hay LLM en ninguna cifra.

## Lista de materiales (pestaña «Lista de materiales» del proyecto)

- **Sin precios.** Es la lista que se envía a los proveedores (HCG, Protel, Ditesa, MAZ, Electrocaribe…);
  después de recibir cotizaciones se marcan con «x» en el Excel. Inventario (Bodega) = revisión manual por proyecto.
- **Catálogo** `materials/catalog.py`: las 171 líneas de la hoja «Solicitud de materiales», generado con
  `python3 scripts/gen_materials_catalog.py "<xlsx>"`. No se edita a mano.
- **Reglas** `materials/engine.py`: equipos (conteos del diseño), montaje (layout del techo), cables / terminales /
  termoencogible / cinta (de los tramos dimensionados), protecciones (breakers y fusibles), canalización y accesorios
  (por canalización), barra Lynx y cables de comunicación (por conteo de equipos). Cada línea muestra cómo se calculó.
- Lo que el diseño necesita y la lista maestra no tiene (breaker CC de 25 A, cable #3, Fronius…) sale como línea
  **nueva** marcada, no se fuerza a otra fila.
- **Ediciones del proyecto** en `projects.tech_spec["materials"]`: `layout` (filas, orientación, largo de riel,
  separación de patas), `options` (breaker de string, curvas y LB por canalización, material de cada canalización),
  `overrides` (cantidad/comentario editados) y `extras` (líneas agregadas a mano). Sobreviven a cambios del diseño.
- Excel: `materials/export_xlsx.py`, mismo encabezado y filas de sección/grupo que la hoja maestra; columnas de
  proveedores y Bodega vacías; solo líneas con cantidad.
- **Por definir en cada proyecto** (la lista lo avisa, se agregan a mano): gabinetes y cajas, centro de carga del
  sub-panel, SPD, riel DIN y strut, tornillería de techo, tubería flexible.

### Parámetros de las reglas (ajustables en `materials/engine.py`)

Desperdicio 10 % en cable y tubo; cable redondeado a 5 m (cable solar en rollos de 100 m); tubos de 3 m; repuesto
de montaje 5 %; terminales de ojo de 5 en 5; termoencogible 8 cm por terminal (mínimo 1 m); separación de gazas 1.25 m
(PVC) / 1.5 m (EMT); 2 curvas y 0 conduletas LB por canalización. Los conductores de una canalización compartida
(strings FV, AC de los dos inversores) se dimensionan juntos y llevan **una** tierra.

### Calibración pendiente con compras reales (María José)

Reglas que coinciden con lo comprado: rieles 9, tierras de riel 8, MC4 8, cable solar 100/100 m, UTP 4, VE.CAN 1,
roscas Lynx 12, cables Pylontech 4, 4 cintas. Diferencias abiertas: barras Lynx 2 (compró 3) y fusibles MEGA (compró
12 de 225 A; la regla da 2 de 200 A + 4 de batería por definir), uniones de riel 4 (compró 8), clamps 30/9 (compró 32/10),
patas 47 (compró 45), calibre de tierras (#8 por la regla del Excel; compró #10 y #6).

## Unifilar (pestaña «Unifilar»)

- Dibujo: `unifilar/generate_unifilar.py` (copia del skill `unifilar-hibrido-ac`; documentación en `docs/unifilar/`).
  Único cambio al dibujo: el texto del uso de Q4 pasa sobre la barra para no cruzarse con el SPD.
- Configuración: `unifilar/config_builder.py` arma el JSON del dibujo con los calibres, breakers y colores del
  dimensionamiento; las dos preguntas que el diseño no responde (inyección y bus DC con o sin Lynx Distributor)
  se preguntan siempre y se guardan en `tech_spec["unifilar"]`.
- Alcance (avisa y no dibuja fuera de él): híbrido con acople AC, 2 MultiPlus-II 120 V, 1 inversor FV con 1–2 strings,
  1–6 baterías (1–4 con Distributor), Ekrano GX.
- Las revisiones de ingeniería (Q1 vs. 95 A por Multi, breaker de string vs. 1.56 × Isc, Q3, protección DC sin
  Distributor, fusibles pendientes) se muestran en pantalla, nunca dentro del PDF.

## Validación

`python3 scripts/validate_materials.py` (también `validate_wiring.py`, `validate_coupling.py`).
