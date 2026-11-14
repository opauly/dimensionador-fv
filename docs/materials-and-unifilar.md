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
- **Fuera de la lista (se agregan a mano si hace falta):** cajas de registro y empalmes, tubería flexible Biex y canasta (ya no se usan).

### Parámetros de las reglas (ajustables en `materials/engine.py`)

Desperdicio 10 % en cable y tubo; cable redondeado a 5 m (el cable solar también va por metro, según la distancia del techo al centro de carga DC); tubos de 3 m; repuesto
de montaje 5 %; terminales de ojo de 5 en 5; termoencogible 8 cm por terminal (mínimo 1 m); separación de gazas 1.25 m
(PVC) / 1.5 m (EMT); 2 curvas y 0 conduletas LB por canalización. Los conductores de una canalización compartida
(strings FV, AC de los dos inversores) se dimensionan juntos y llevan **una** tierra.

### Calibración pendiente con compras reales (María José)

Reglas que coinciden con lo comprado: rieles 9, tierras de riel 8, MC4 8, UTP 4, VE.CAN 1,
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
- **Tubería:** el cableado solar va en PVC de al menos 1". AC In y AC Out van en PVC dimensionado (la herramienta siempre la pide; si el
  cliente ya la tiene, simplemente no se compra). El cable de batería va por fuera del tubo.
- **Ducto metálico 4x4:** siempre mínimo 1 ducto con 2 tapas; lleva el cableado general de los inversores. De ahí salen 4 tramos
  de unos 50 cm de EMT 1" a cada inversor: 1 tubo de 3 m y 4 conectores de presión por inversor.
- **Siempre van:** gabinete 50x40x20 (comentario «POR CONFIRMAR MEDIDA»), centro de carga Chint DC de 5 espacios (breakers DC),
  supresor de picos (1), 2 prensacables PG-21, silicón 3M (1 tubo por cada 20 patas), toma de monitoreo (breaker 20 A 1P, toma doble, placa inox,
  caja de intemperie, #12 rojo/verde/blanco de 15 m).
- **También siempre:** 1 riel DIN perforado, 1 terminal para riel DIN y 1 riel strut perfil bajo.
- **Cerbo o Ekrano GX:** lo define el selector «Monitoreo» del paso Equipos; la lista pone el que se eligió.
- **Medidor de energía (VM-3P75CT):** se elige en Equipos («Medidor de energía», opcional; híbrido y off-grid). Trae 2 transformadores de
  corriente (comentario «POR VERIFICAR TAMAÑO») y cable de red Ethernet cat6e del largo del tramo gabinete → tablero eléctrico (el de «Red → entrada AC»), del medidor al GX. El catálogo lo guarda en `monitoring_devices` con
  `device_kind = 'meter'` (migración 059, datos del datasheet y PDF guardado) y no sale en la lista de monitoreo.
- **Fusible de batería:** Fidus carga máximo 100 A, así que el fusible Mega es de 125 A (migración 060: `max_charge_a` y `fuse_a` en el catálogo).
- **Techo:** MC4 y la tierra se amarra a los rieles con su accesorio de grounding; de ahí directo a los breakers DC, sin cajas ni empalmes.
- **Grid Zero:** sin Victron, baterías ni Lynx. Lleva paneles, montaje, inversor de strings, centro de carga DC, SPD, riel DIN/strut, silicón y la
  interconexión: base de medidor con interruptor principal (1), breaker compatible (125 % de la corriente máxima del inversor, tamaño comercial
  siguiente; casi siempre el Fronius) y candado (1). Esa base es la de **generación**: se interconecta con la base de medición de consumo
  existente de la distribuidora. El cable de esa interconexión es el mismo que llega a la base de generación (cuarto tramo «Base de generación → base de consumo»,
  largo editable en Técnico, sin breaker propio) y va en la lista.
- **Cableado Grid Zero (NEC):** tres tramos: strings → breakers CC (solar #10 mín., tubo 1"), breakers CC → Fronius (mismo conductor, sin breaker propio:
  lo protege el del string) y Fronius → base de medidor de generación (125 % de la corriente máxima del inversor, tope del fabricante; el breaker va en la base).
  Largos editables en Técnico («Paneles → breakers CC», «Breakers CC → Fronius», «Fronius → base de generación»). Código: `webapp/wizard_steps/gz_wiring.py`.
- **Fronius Smart Meter (Grid Zero):** es una opción de monitoreo del paso Equipos (modelo WR 100-600 V-3, migración 061). Lleva transformadores de corriente («donas»,
  Fronius Smart Meter CT V de 100/250/400 A, 333 mV), uno por fase: 2 en monofásico, 3 en trifásico (`calculations/meter_cts.py`). En la lista salen con el comentario
  «POR VERIFICAR TAMAÑO» y en la cotización como línea «Transformadores de corriente» (precio de `monitoring_devices.ct_cost_usd`, $0 hasta cargarlo).
- **Gabinete en Grid Zero:** el gabinete 50x40x20 es la norma en todos los sistemas, Grid Zero incluido («POR CONFIRMAR MEDIDA»); ahí va el Smart Meter Fronius. La caja plexo solo se usa si no hay gabinete (se edita la línea en la Lista); ya no se usa por defecto. Grid Zero también lleva el ducto 4x4 con sus tapas, los tubos EMT cortos al inversor y el kit de toma de monitoreo, igual que los otros sistemas.
- **Cable del Fronius Smart Meter:** Ethernet cat6e (Modbus RS485 al inversor). Las donas van justo después del medidor de consumo, así que el cable cubre el tramo
  «Fronius → base de generación» + «Base de generación → base de consumo» (largos de Técnico) + 10 % de desperdicio, de a 5 m.
- **Centros de carga Chint DC:** una caja de 5 espacios aloja 2 breakers 2P de strings; van ⌈strings ÷ 2⌉ cajas (el unifilar lo rotula «Chint 5 espacios × n»).
- **Mueble de baterías:** solo con baterías US5000 / UF5000 (de rack): un mueble metálico por cada 6 baterías (comentario «POR CONFIRMAR MEDIDA»). Las Fidus van colgadas en la pared, acostadas, 2 por columna, y no llevan mueble.
- **Centro de carga de desconexión (opcional):** casilla en el panel de cableado (Técnico del proyecto y, en acople AC, también el wizard). Solo con Fronius: Grid Zero y híbrido/off-grid acoplado en AC. Agrega un tablero de 4 espacios junto al Fronius con un breaker de 2 polos del mismo amperaje que el de la base de generación (o el del sub-panel) y, en Grid Zero con Smart Meter, un segundo breaker igual que alimenta el medidor (3 m de #12). No reemplaza la base de generación ni el breaker del sub-panel. Cableado: nuevo tramo «Inversor → centro de carga» (largo editable `disc_m`, 1.5 m) y el tramo siguiente pasa a salir del centro. En el unifilar se dibuja entre el Fronius y la base (Grid Zero) o el sub-panel (híbrido). Estado en `scratch.disconnect` / `tech_spec.disconnect` (`webapp/wizard_steps/disconnect_center.py`).
- **Alimentación del Ekrano/Cerbo:** sin breaker (lleva fusible interno); solo un poco de cable #12 AWG (3 m rojo + 3 m negro) desde la barra Lynx. No va en Grid Zero.
- **Medidor VM en la cotización:** si se elige en Equipos, sale como línea «Medidor de energía» (precio del catálogo; $0 hasta que se cargue el precio en Admin → Monitoreo).
- **Unifilar:** tres dibujos (`unifilar/generate_unifilar.py`): híbrido acoplado en AC, acople DC (off-grid o híbrido: strings → centro de carga DC → controladores MPPT →
  Lynx Power In → Multis → sub-panel) y Grid Zero (strings → centro de carga DC → Fronius → base de medidor de generación, interconectada con la base de medición de consumo → tablero principal). El medidor VM se dibuja en paralelo en
  el tablero principal con sus transformadores de corriente; si el dibujo no tiene tablero principal (sistema aislado), se anota en el sub-panel de cargas críticas.
  El dibujo DC cubre 1-8 inversores, 1-24 controladores (con más de 4 se abrevia: MPPT 1, MPPT 2, «· · ·» y el último, cada uno con su string; hace falta al menos un string por controlador), 1-4 strings (más solo con más de 4 controladores), 1-24 baterías y solo Lynx Power In (sin Distributor).
- **Dibujo abreviado:** con más de 4 baterías o más de 3 inversores se dibujan #1, #2, «· · ·» y el último; el cableado del
  resto se repite igual. El título del Lynx dice cuántas barras en paralelo (⌈entradas ÷ 4⌉).
- **DC acoplado, un breaker por string:** «Paneles → breakers CC» (uno por string, con su breaker) y «Breakers CC → controlador» (strings combinados en una barra,
  sin breaker propio). Largo del segundo tramo editable en Técnico.
- **No se incluyen:** cajas plexo (por ahora), tornillos de techo (las patas en L ya los traen), el sub-panel de cargas críticas (lo pone el propietario o
  constructor) y el conector de varilla de tierra.
- **Mínimos:** un paquete de amarras; las gazas salen de la distancia de la tubería, sin repuesto.

## Revisión lista ↔ unifilar

`scripts/validate_materials.py` compara lo que dibuja el unifilar con la lista en los tres sistemas (híbrido AC, acople DC y Grid Zero): breakers Q1/Q2/Q3 y de strings,
cantidades de baterías, Multis, controladores y barras Lynx, SPD, medidor con sus donas y el cable de interconexión de Grid Zero.

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
