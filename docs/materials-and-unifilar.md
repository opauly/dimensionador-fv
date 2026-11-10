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
- **Layout del techo en el asistente**: el paso Equipos (Off-Grid / Híbrido) pregunta «Techo y montaje» bajo el cableado y lo guarda en
  `scratch.roof_layout` de la versión. La lista lo usa como base; lo que el proyecto guarde en su pestaña Lista gana, clave por clave.
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
patas 47 (compró 45), calibre de tierras (ahora por la T250.122 según el breaker: #10 en strings y Fronius, #8 en AC; compró #10 y #6, que cubren todo).

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

## Reglas de Oscar (de las compras reales de María José)

- **Calibres:** solo los que venden los proveedores. El #3 y el #1 no se piden: se sube al siguiente (#2). La herramienta muestra el
  mínimo seguro; para otro calibre se edita la cantidad de la línea o se agrega una línea a mano.
- **Tubería:** el cableado solar va en PVC de al menos 1". AC In y AC Out van en PVC dimensionado (si el cliente ya tiene la
  tubería, se marca «Sin tubería» en «Datos para calcular»). El cable de batería va por fuera del tubo.
- **Ducto metálico 4x4:** siempre mínimo 1 ducto con 2 tapas; lleva el cableado general de los inversores. De ahí salen tramos
  cortos de EMT 1" a cada inversor (4 por inversor, por confirmar).
- **Siempre van:** gabinete 50x40x20 (comentario «POR CONFIRMAR MEDIDA»), centro de carga Chint DC de 5 espacios (breakers DC),
  supresor de picos (1), silicón 3M (1 tubo por cada 20 patas), toma de monitoreo (breaker 20 A 1P, toma doble, placa inox,
  caja de intemperie, #12 rojo/verde/blanco de 15 m).
- **No se incluyen:** tornillos de techo (las patas en L ya los traen), el sub-panel de cargas críticas (lo pone el propietario o
  constructor) y el conector de varilla de tierra.
- **Mínimos:** un paquete de amarras; las gazas salen de la distancia de la tubería, sin repuesto.

## Validación

`python3 scripts/validate_materials.py` (también `validate_wiring.py`, `validate_coupling.py`).

## Límites del fabricante y valores manuales

- Migración 058: columnas de límites del fabricante en el catálogo (módulo: protección máx. en serie; inversor: W continuos, pico, breaker AC máx., fusible DC; batería: corrientes y fusible) y `datasheet_path` en los 5 equipos; se editan en el catálogo de admin. El diseño lee la fila actual del catálogo, no la copia guardada. `calculations/datasheet_limits.py` queda como respaldo y guarda lo leído de los datasheets (MultiPlus-II 120 V: potencia continua en W a 25 °C, pico, entrada AC máx. 95 A;
  Fronius Primo a 240 V: corriente de salida continua y breaker AC máximo). El tramo batería → Multi usa la potencia continua en **W** (4000 W),
  no los 5000 **VA** del catálogo; el Fronius usa 41.6 A y su breaker máximo (60 A).
- En la pestaña Técnico, «Valores manuales» permite poner un breaker/fusible y/o un calibre propio por tramo (`tech_spec["wiring_manual"]`). El plano,
  el conducto y la lista usan el valor manual; el calculado queda en `branch["calc"]`. Cada campo lleva ✓ (seguro, incluye un calibre mayor)
  o ✗ (peligroso: calibre que no cubre la carga, breaker/fusible sobre lo que protege al cable por NEC 240.4(B) o sobre el máximo del fabricante,
  o bajo la corriente de diseño). En la entrada AC, un breaker menor solo limita la corriente y es seguro.

## Importar datasheets desde Admin → Equipos

Cada tipo de equipo tiene «📄 Extraer de datasheet»: se sube el PDF, Claude (`calculations/datasheet_parser.py`) lee las variantes y los límites del
fabricante (incluye protección máx. en serie del módulo, W continuos, breaker AC máx., fusible y corrientes de la batería), el PDF se guarda en el bucket
privado `solar-tool` (`datasheets/<tipo>/`) y se elige la variante, que abre el formulario normal prefilled. Nada llega al catálogo hasta que se revisa
y se guarda (con el aviso de duplicado de siempre). El diseño del wizard lee la fila actual del catálogo. «PDF» en la lista abre el datasheet guardado.
