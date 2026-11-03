# Contexto: generación de unifilar y BOM para Dimensionador FV

Documento de contexto para Claude Code. Describe el skill `unifilar-hibrido-ac` (diagrama unifilar de sistemas híbridos acoplados en AC), la lista de materiales (BOM) del proyecto de referencia y cómo unir ambos en el app **Dimensionador FV** (repo `opauly/dimensionador-fv`).

> Cómo usar este documento: léelo completo antes de tocar el repo. Después explora el repo (estructura, backend Supabase, flujos Node-RED / Apps Script, el código de BOM que ya existe) y propón un plan antes de escribir código. Donde este documento diga "verificar", son criterios de ingeniería que el dueño del proyecto (Oscar Pauly Calvo, Pauly & Co) debe confirmar contra datasheets y el código vigente; no los trates como verdades.

---

## 1. Objetivo

Que el app genere, a partir del diseño del sistema, dos entregables coherentes entre sí:

1. **Diagrama unifilar** (PDF de 1 hoja, tamaño 11x17 apaisado, cajetín Pauly & Co) con el calibre y la función de cada conductor en cada tramo.
2. **BOM / solicitud de materiales** (PDF).

La idea central: **una sola estructura de datos por tramo de conductor** (de dónde a dónde, calibre, color, función, longitud, canalización). El BOM es la suma de esos tramos más los equipos y accesorios; el diagrama usa esos mismos tramos como rótulos. Así desaparece el problema actual, donde los comentarios de los cables en la BOM llegan desalineados y hay que interpretarlos a mano.

El dueño ya tiene programada parte de la generación del BOM en el app. Revisa ese código y reutilízalo; no lo reescribas.

## 2. Contexto del proyecto Dimensionador FV (lo que ya existe)

- Repo: `https://github.com/opauly/dimensionador-fv`.
- Backend Supabase; envío de reportes por correo vía Node-RED y Google Apps Script.
- Diseño previo: taxonomía de 5 categorías de carga; la IA solo clasifica, extrae y redacta narrativa; la matemática de energía es determinista (código o APIs). Mantén ese principio: **el unifilar y el BOM deben ser 100 % deterministas** a partir de la configuración; la IA, si participa, solo ayuda a extraer datos de cotizaciones o BOM subidos.
- Existe una especificación de cotización donde el margen se diluye en las líneas de costo (precio unitario fijo por categoría de equipo, tasa fija para costos que escalan con el proyecto, una categoría residual, IVA sobre servicios). El BOM del unifilar no debe mostrar precios ni márgenes; es una lista de compra.
- Idioma de la interfaz y de los documentos: **español** (Costa Rica).

## 3. El skill `unifilar-hibrido-ac`

Entregado como `unifilar-hibrido-ac.skill` (un zip). Estructura:

```
unifilar-hibrido-ac/
├── SKILL.md                      # flujo para Claude: leer cotización y BOM, preguntar, generar, revisar
├── scripts/generate_unifilar.py  # generador (reportlab) — FUENTE DE VERDAD del dibujo
├── references/config.md          # esquema del JSON de configuración
├── references/diseno.md          # criterios de diseño y verificaciones
└── assets/ejemplo_maria_jose.json
```

Uso del script: `python generate_unifilar.py config.json salida.pdf` (requiere `reportlab`). Los campos que faltan en el JSON toman los valores por defecto de `DEFAULTS` dentro del script.

**Copia el contenido del skill dentro del repo** (por ejemplo `docs/unifilar/` o `packages/unifilar/`) para tener el script y el ejemplo como referencia al portar.

### 3.1 Alcance soportado

- Red 120/240 V, 60 Hz.
- **2 × Victron MultiPlus-II 120 V en split-phase**: MP#1 = L1 (maestro), MP#2 = L2 (esclavo).
- **Fronius monofásico 240 V** (1 o 2 MPPT = 1 o 2 strings) conectado en el **AC-OUT** de los Multis, dentro del sub-panel de cargas críticas (acople en AC).
- Baterías de 48 V: 1 a 6; máximo 4 si se usa Lynx Distributor.
- Bus DC: **Lynx Power In solo**, o Lynx Power In + Lynx Distributor.
- Ekrano GX para monitoreo y control ESS.
- Modo de exportación: `grid_zero` (cero inyección) o `inyeccion`.

**Fuera de alcance** (el app debe avisar en vez de dibujar algo incorrecto): trifásico, un solo Multi, Fronius con 3+ strings, acople en DC, off-grid puro sin Fronius, Fronius en el lado de red (antes de los Multis).

### 3.2 Topología que dibuja

Flujo de potencia:

```
Red -> medidor kWh -> Tablero principal (existente) -> Q1 (2P, AC-IN) -> 2 × MultiPlus-II
MultiPlus-II AC-OUT -> Q2 -> bus del sub-panel de cargas críticas -> Q4 -> cargas críticas
Arreglo FV (S1, S2) -> Gabinete DC (QS1, QS2) -> Fronius (MPPT 1, 2)
Fronius AC (L1, L2, T) -> Q3 -> bus del sub-panel (del lado de carga de Q2, nunca antes)
Baterías (FB1..FBn, fusible MEGA c/u) -> Lynx Power In [-> Lynx Distributor con F1/F2] -> MP#1 y MP#2 (DC + / -)
Ekrano GX: alimentado por QDC 2P desde el bus DC; comunicación por VE.Bus, CAN (BMS de la batería maestra), Ethernet (Modbus TCP al Fronius), y VE.Can solo con Distributor
SPD en el sub-panel; tierras a barra de tierras
```

Reglas físicas que el modelo debe respetar:

- El Fronius 240 V inyecta entre L1 y L2: **usa L1, L2 y tierra, sin neutro**. Q3 es 2P.
- El neutro de las cargas de 120 V sale de los Multis (común a ambas unidades) hacia la barra de neutro del sub-panel.
- Enlace neutro-tierra solo en el tablero principal; en modo isla lo da el relé de tierra de los Multis (verificar ajuste).
- Grid Zero: el Ekrano limita la inyección y controla la potencia del Fronius por Ethernet (Modbus TCP). **Hace falta un cable UTP Fronius a Ekrano**.
- Sin red: los Multis forman la red del sub-panel; el Fronius se desconecta por anti-isla, se reconecta y se regula por desplazamiento de frecuencia.
- Con el Fronius en AC-OUT, el propio Multi mide el flujo; un medidor de red no es obligatorio, pero conviene confirmarlo al configurar el límite de inyección.

### 3.3 Esquema de configuración (JSON)

Todos los campos son opcionales; defaults entre paréntesis. Los textos se dibujan tal cual (escribe los calibres con el formato que quieres ver). Usa solo caracteres Latin-1 si sigues con Helvetica/reportlab; al portar a SVG/otra fuente esa restricción desaparece.

```jsonc
{
  "project": {
    "name": "Proyecto María José Castro en Carrillo, Guanacaste",   // cajetín, campo PROYECTO
    "client": "María José Castro",
    "location": "Carrillo, Guanacaste, Costa Rica",
    "date": "2026-10-27",
    "revision": "A (borrador)",                                      // default
    "draft": true,                                                   // default; muestra BORRADOR · REV A en rojo
    "responsible": "Ing. Oscar Pauly Calvo · IE-30111"               // default
  },
  "pv": {
    "strings": 2,                      // 1 o 2 (= MPPT usados)
    "modules_per_string": 8,
    "module_w": 620,
    "module_label": "JA Solar 620 W",
    "roof_m2": 32,                     // opcional
    "string_breaker": "32 A 2P DC",    // texto
    "dc_wire": "#10 SOLAR",            // se dibuja "+ #10 SOLAR" y "- #10 SOLAR"
    "ground_wire": "T #10 AWG verde"
  },
  "fronius": {
    "label": "Fronius Primo 10.0-1 US 240 V", "kw": 10,
    "ac_breaker": "2P 60 A",
    "ac_conductors": ["L1 #4 AWG negro", "L2 #4 AWG rojo", "T #6 AWG verde"],
    "ground_wire": "T #6 AWG verde"
  },
  "multis": {
    "label": "MULTIPLUS-II 48/5000", "model": "MultiPlus-II 48/5000 120 V",
    "ac_in_breaker": "2P 100 A",
    "ac_in_conductors":  ["L1 #4 AWG negro", "L2 #4 AWG rojo", "N #4 AWG blanco", "T #6 AWG verde"],
    "ac_out_conductors": ["L1 #4 AWG negro", "L2 #4 AWG rojo", "N #4 AWG blanco", "T #6 AWG verde"],
    "dc_pos": "+ #2 AWG rojo", "dc_neg": "- #2 AWG negro",
    "ground_wire": "T #6 AWG verde",
    "dc_fuse_labels": ["F1", "F2"]      // solo se dibujan con Distributor
  },
  "battery": {
    "count": 4,                         // 1-6; máx. 4 con Distributor
    "label": "Pylontech Fidus", "short": "Fidus", "kwh_each": 4.8,
    "fuse_prefix": "FB", "can_master": true,
    "lynx": "power_in",                 // o "power_in_distributor"
    "cables_note": ["Cables batería a Power In (+ / -):", "no listados en BOM, por definir"]
  },
  "gx": { "label": "EKRANO GX", "power_breaker": "QDC 2P", "power_note": "+ / - por definir" },
  "export": "grid_zero",                // o "inyeccion"
  "subpanel": {
    "q2": "2P", "q4": "circuitos críticos", "spd": "SPD SDSA 1175",   // spd: null omite el supresor
    "loads": ["iluminación, internet, tomacorrientes,", "refrigerador, etc."]
  },
  "grid": { "voltage": "120/240 V · 60 Hz" },
  "comms_notes": {
    "vebus": "VE.Bus (cable no listado en BOM)",
    "can": "CAN-bus BMS (Fidus #1 a Ekrano GX) · cable no listado en BOM",
    "eth": "Ethernet / Modbus TCP (control de potencia del Fronius) · UTP no listado en BOM"
  }
}
```

Validaciones que ya hace el script: `pv.strings` ∈ {1, 2}; `battery.count` entre 1 y 6 (1 a 4 con Distributor).

### 3.4 Convenciones de dibujo (decisiones del dueño; no las cambies sin preguntar)

- **Una sola hoja**, sin tags numéricos: el calibre y la función de cada conductor van **en letra pequeña junto a su tramo** (DC: `+ / - / T`; AC: `L1 / L2 / N / T`).
- Sin tabla de conductores en el plano. (La tabla por tramo vive en el BOM / documentación.)
- Colores: AC negro; DC fotovoltaico naranja; DC batería rojo (+) y negro (-); tierra verde discontinuo; comunicaciones azul discontinuo.
- Estado **BORRADOR · REV A** en rojo hasta que el dueño indique que se emite.
- Los pendientes y verificaciones **no van dentro del PDF** (el plano debe poder salir al cliente); se entregan aparte (en la UI o en un reporte interno).
- Lo que la BOM no trae se dibuja marcado "no listado en BOM, por definir".
- Cajetín: marca Pauly & Co, cliente, ubicación, fecha, responsable, escala "sin escala", "Hoja 1 de 1".
- Nombre de archivo: `Proyecto_<Cliente>_<Lugar>_Unifilar_RevA.pdf`.
- La leyenda no debe tener símbolos que se pisen (usa espaciado de ~19 pt entre filas).
- El bus DC de baterías se **pregunta siempre** (una vez se asumió Distributor por error).

### 3.5 Geometría del dibujo (para portar a SVG/TypeScript)

Página 1224 × 792 pt (11×17 pulgadas apaisado), origen abajo-izquierda en el script (en SVG invierte Y). Marco a 18 pt del borde. Fuente Helvetica. El script es la fuente de verdad; esta tabla es un atajo.

| Elemento | x, y, ancho × alto |
|---|---|
| Arreglo FV | 40, 590, 240 × 120 (filas de strings en y = 665 y 635; módulos de 20 × 14 con paso 24) |
| Gabinete DC | 340, 600, 130 × 105 (QS1/QS2 en x = 395, sobre las líneas de string) |
| Fronius | 560, 590, 200 × 120 (entradas MPPT en x = 560) |
| Tablero principal | 170, 386, 110 × 100 |
| Línea AC principal | y = 436, de x = 78 a 880 |
| Q1 | x = 325, y = 436 |
| Bloque Multis | 380, 372, 180 × 150; MP#1 = 392, 445, 156 × 45; MP#2 = 392, 382, 156 × 45 |
| Salida AC del Fronius | vertical en x = 690, de y = 590 a 436 |
| Sub-panel cargas críticas | 640, 366, 180 × 140 (Q2 en x = 658; Q3 en y = 466; Q4 en x = 795; SPD en x = 775) |
| Cargas críticas | 880, 406, 170 × 60 |
| Baterías | caja i: x = 40 + 88·i, y = 170, 76 × 55; línea con fusible FBi hasta y = 265 |
| Lynx Power In | 40, 265, 550 × 28 (solo Power In) o 40, 265, 340 × 28 (con Distributor) |
| Lynx Distributor | 400, 265, 190 × 28 (solo si aplica) |
| Pares DC a Multis | x = 446/454 (MP#1) y 516/524 (MP#2), de y = 293 a 372 |
| Ekrano GX | 660, 235, 140 × 60 |
| Cajetín | 744, 18, 462 × 120 |
| Leyenda | filas en y = 104, 85, 66, 47, 28 |

Colores: navy `#12385B`, verde marca `#4CB87E`, naranja `#D9822B`, rojo `#B8322A`, azul `#1F5FBF`, verde tierra `#1E8449`, gris `#666666`, relleno `#EEF1F4`.

Rutas de comunicación (azul discontinuo): VE.Bus desde la base de los Multis (x = 545) hacia el Ekrano; CAN desde la batería #1 por y = 155 hasta el Ekrano (x = 725); Ethernet desde el Fronius (y = 650) por x = 1070 hasta el Ekrano (y = 265); VE.Can solo con Distributor.

## 4. Criterios de diseño y verificaciones (candidatos a validaciones del app)

Son revisiones de ingeniería. El app debe mostrarlas como **advertencias** y no bloquear la generación. Cifras de referencia; confirma con datasheets y con el código aplicable.

- **Breaker de string DC:** ≥ 1.56 × Isc del módulo (1.25 × 1.25), sin pasar el fusible serie máximo del datasheet del módulo, con tensión nominal DC ≥ Voc del string (8 módulos) a la temperatura mínima. Una BOM con 60 A para strings de 8 × 620 W está sobredimensionada; el dueño usó **32 A**.
- **Breaker AC del Fronius (Q3):** ≥ 125 % de la corriente máxima de salida (P / 240 V). Para 10 kW: 41.7 A × 1.25 = 52 A, medida estándar siguiente = 60 A. Medidas estándar de breaker: 15, 20, 25, 30, 35, 40, 45, 50, 60, 70, 80, 90, 100 A.
- **Alimentador AC-IN (Q1):** comparar el breaker contra la ampacidad del conductor y contra el límite de corriente de entrada AC de cada MultiPlus-II (unos 50 A por unidad; verificar manual). En el proyecto de referencia hay una discrepancia: Q1 = 100 A con conductores #4 AWG THHN (85 A a 75 °C).
- **DC de los Multis:** verificar que #2 AWG en ~10 m soporte la corriente DC máxima de cada Multi y definir la protección DC por inversor. **Sin Distributor** los Multis quedan protegidos solo por los fusibles de las baterías (FB1..FBn): confirmar si basta. Revisar también la capacidad de interrupción de los fusibles contra la corriente de falla del banco de baterías.
- **Relación de potencia:** Fronius (kW) vs. 2 × 5 kVA de los Multis en AC-OUT (1:1 en el proyecto de referencia); confirmar el límite de PV acoplada en AC en el manual de Victron.
- **UTP Fronius a Ekrano:** requerido para Grid Zero.

Ampacidad de cobre a 75 °C (referencia, Tabla 310.16 del NEC; verificar edición vigente): #10 = 35 A, #8 = 50 A, #6 = 65 A, #4 = 85 A, #3 = 100 A, #2 = 115 A, #1 = 130 A, 1/0 = 150 A, 2/0 = 175 A, 3/0 = 200 A, 4/0 = 230 A. Los terminales de los equipos suelen limitar a 75 °C aunque el conductor sea de 90 °C.

### 4.1 Tipos de conductor (normativa)

- Código eléctrico oficial de Costa Rica: basado en **NEC 2008** con reformas posteriores. Confirmar la edición vigente con el CFIA antes de citar artículos; la numeración cambia entre ediciones.
- Para cableado DC en canalización metálica se usan los conductores de building wire del Capítulo 3: **THHN/THWN-2** (90 °C, apto mojado; comprar el que lleva la marca THWN-2), XHHW-2 o RHW-2. Strings FV expuestos: cable solar USE-2 / PV wire listado.
- El **cable de soldadura ("porta electrodo")** se consigue en Costa Rica pero no es un tipo permitido por el NEC para alambrado general, salvo que además esté listado RHW/RHH. Se recomienda THHN/THWN-2 de cobre con ojales de compresión (crimpado hidráulico) y termoencogible. El cable de hilado fino requiere terminales identificados para ese tipo de hilado.
- En gabinetes conviene una barrera o separación entre cableado AC, DC y comunicaciones.

## 5. Proyecto de referencia (María José Castro, Carrillo, Guanacaste)

Cotización del 7/7/2026 (Pauly & Co): sistema híbrido solo cargas críticas.

| Equipo | Cant. | Especificación |
|---|---|---|
| Paneles solares | 16 | JA Solar 620 W (9.92 kWp), arreglo 2 × 8 |
| Baterías | 4 | Pylontech Fidus (19.2 kWh a 10 h) |
| Inversores off-grid | 2 | Victron MultiPlus-II 5000 VA |
| Inversor on-grid | 1 | Fronius Primo 10.0-1 US 240 V |
| Monitoreo | 1 | Victron Ekrano GX |

Decisiones tomadas para este proyecto: cero inyección (Grid Zero); bus DC con **solo Lynx Power In** (sin Distributor); breakers de string de 32 A; estructura 2 × 8 módulos; el Fronius se conecta en el sub-panel de cargas críticas. Archivo de configuración correspondiente: `assets/ejemplo_maria_jose.json`.

### 5.1 Tramos de conductor (modelo de datos propuesto)

Esta tabla es el contenido que el app debe producir como estructura de datos; el diagrama y el BOM salen de ella.

| Tramo | De | A | Conductores | Cantidad en BOM | Canalización (a confirmar) |
|---|---|---|---|---|---|
| T1 | Arreglo FV (S1, S2) | Gabinete DC | 2 × #10 AWG SOLAR por string (+ rojo, - negro) | 100 m rojo + 100 m negro (T1 + T2) | PVC SCH-40 1" con conduleta LB (tubería ya disponible) |
| T2 | Gabinete DC | Fronius (MPPT 1, 2) | igual que T1 | incluido en T1 | PVC SCH-40 1" / Biex al equipo |
| T3 | Fronius | Q3 del sub-panel | L1 #4 negro, L2 #4 rojo, T #6 verde (THHN Cu) | #4: 20 m por color, compartidos T3 a T5 | EMT / ducto metálico |
| T4 | Tablero principal, Q1 | Multis AC-IN | L1 #4 negro, L2 #4 rojo, N #4 blanco, T #6 verde | compartido | EMT / ducto metálico |
| T5 | Multis AC-OUT | Sub-panel | L1 #4 negro, L2 #4 rojo, N #4 blanco, T #6 verde | compartido | EMT / ducto metálico |
| T6 | Lynx Power In | cada MultiPlus-II | #2 AWG THHN rojo (+) y negro (-), ojal #2, termoencogible #2 | 10 m rojo + 10 m negro | dentro del gabinete Victron |
| T7 | Baterías Fidus (×4) | Lynx Power In | **no listado en BOM** | - | por definir |
| T8 | Tierra del arreglo FV | Barra de tierras | #10 AWG THHN verde | 30 m | junto a la tubería FV |
| T9 | Tierra de equipos | Barra de tierras | #6 AWG THHN verde, ojal #6 | 30 m | - |
| T10 | Comunicaciones (VE.Bus, CAN, Ethernet) | - | **no listado en BOM** | - | por definir |

Nota histórica sobre la BOM original: la columna de comentarios llegaba desalineada del texto extraído; la asignación de cables #4 / #6 a los tramos AC fue **interpretada** y debe confirmarse con el dueño.

## 6. BOM / solicitud de materiales v2 (proyecto de referencia)

Versión vigente (2026-10-28), agrupada por categoría. Las diferencias con las versiones anteriores fueron aprobadas por el dueño.

**Cables**

| Detalle | Cantidad | Comentarios |
|---|---|---|
| Cable #10 AWG SOLAR negro | 100 m | |
| Cable #10 AWG SOLAR rojo | 100 m | |
| Cable #10 AWG THHN CU verde | 30 m | Tierra paneles |
| Cable #6 AWG THHN CU verde | 30 m | Tierra de equipos |
| Cable #4 AWG THHN CU negro / rojo / blanco | 20 m c/u | AC In / AC Out |
| Cable #2 AWG THHN CU negro | 10 m | Inversores - Lynx |
| Cable #2 AWG THHN CU rojo | 10 m | Inversores - Lynx |

**Protecciones, terminales y tierra**

| Detalle | Cantidad | Comentarios |
|---|---|---|
| Breaker DC riel DIN 32 A 2P | 2 un | Paneles nuevos (uno por string); la BOM anterior decía 60 A |
| Breaker AC 100 A 2P caja moldeada (Schneider Powerpact Q, ref. QBL22100) | 1 un | antes era de riel DIN |
| Supresor de picos SDSA 1175 | 1 un | |
| Conector de ojo #2, #4, #6 AWG | 10 un c/u | (la versión Word decía "10 m": era error de unidad) |
| Termoencogible #2 negro / rojo | 1 m c/u | |
| Kit barra de tierras | 1 un | |

**Canalización (cableado en techo y gabinete)**

| Detalle | Cantidad | Comentarios |
|---|---|---|
| Conector 1" PVC SCH-40 | 6 un | Paneles - Gabinete (tubería PVC 1" ya disponible, no se compra) |
| Curva 1" PVC SCH-40 | 4 un | Paneles - Gabinete |
| Conduleta LB 1" | 2 un | |
| Gasa channel 1" | 12 un | |
| Tubo EMT 1 1/4" | **por definir** | |
| Conector EMT 1 1/4" | 8 un | |
| Ducto metálico cuadrado 4" | 1 un * | |
| Tapas para ducto metálico 4" | 2 un * | |
| Gasas plásticas #8 (negras) | 2 un | Paquetes |

\* Cantidad tomada de la lista v1, por confirmar.

**Gabinetes y montaje**

| Detalle | Cantidad | Comentarios |
|---|---|---|
| Gabinete Schneider 600 × 400 × 250 mm, IP66, puerta lisa con placa de montaje (ref. NSYCRN64250P) | 1 un | uso por confirmar |
| Gabinete metálico 30 × 25 × 15 cm | 1 un | Breaker DC / Cerbo |
| Caja plexo 22 × 17 × 8.5 cm (lisas) | 1 un | Breakers DC |
| Riel DIN perforado 35 × 15 mm | 1 un | |
| Riel strut perfil bajo | 1 un | |

**Misceláneos:** tape rojo, blanco, negro y verde (económico), 1 un c/u.

**Eliminados respecto a la v1 (decisión aprobada):** mueble para baterías a la medida, roscas para Lynx Power In (12 un), silicón 3M, tubería PVC 1" (5 un; ya la tiene), tubería Biex flexible 1" y sus conectores, tomacorriente tipo parche.

**Observación:** la BOM nombra "Cerbo" y la cotización "Ekrano GX"; el diagrama dibuja Ekrano GX.

## 7. Entradas que el wizard debe pedir (preguntas del skill)

Intentar inferir primero; preguntar solo lo que falte:

1. Cliente, ubicación, nombre del proyecto, fecha.
2. Inyección a la red: **cero inyección (Grid Zero)** o inyección permitida.
3. Bus DC de baterías: **solo Lynx Power In** o Power In + Lynx Distributor. Preguntarlo siempre; no suponer.
4. Strings: cantidad (1 o 2), módulos por string y potencia del módulo (validar contra el rango MPPT del Fronius).
5. Breaker DC de string: proponer según Isc del módulo y que el usuario confirme.
6. Modelo de Fronius y kW; modelo y cantidad de baterías (kWh por unidad, cantidad 1-6).
7. Calibres y colores de los conductores por tramo (si hay BOM subida) y calibre de los conductores DC hacia los Multis.
8. Sub-panel de cargas críticas: nombre/uso, si lleva SPD y cuál.

## 8. Plan de integración sugerido (propuesta; ajusta tras ver el repo)

1. **Explorar el repo**: estructura, módulos de BOM ya programados, esquema de Supabase, flujos Node-RED y Apps Script que envían correos. No cambies lo existente sin entender cómo se usa.
2. **Definir un esquema compartido** (TypeScript + validación, p. ej. zod) con: `project`, `pv`, `fronius`, `multis`, `battery`, `gx`, `export`, `subpanel`, y una lista **`segments[]`** (los tramos de la sección 5.1). Persistir en Supabase junto al diseño.
3. **BOM desde los tramos**: sumar longitudes por calibre y color, añadir equipos y accesorios, aplicar el formato de la sección 6. Reutilizar el generador de BOM existente.
4. **Renderer del unifilar**: dos opciones.
   - **Recomendada:** portar el dibujo a **TypeScript generando SVG** (sin infraestructura extra; el SVG se convierte a PDF en el navegador o con una librería). Usa la geometría de la sección 3.5 y el script como referencia.
   - **Alternativa:** microservicio Python (FastAPI) que ejecute `generate_unifilar.py` tal cual; más rápido de montar, pero agrega infraestructura.
5. **Pruebas doradas**: con `assets/ejemplo_maria_jose.json` el resultado debe coincidir con el PDF de referencia (`Proyecto_Maria_Jose_Castro_Carrillo_Unifilar_RevA.pdf`). Añade una variante (1 string de 10 módulos, 3 baterías, con Distributor, con inyección, sin SPD) para cubrir las ramas del dibujo y revisa visualmente que no haya textos que se pisen.
6. **Validaciones de la sección 4** como advertencias visibles en la UI (no dentro del PDF).
7. **Entrega**: reutilizar el flujo existente de correo (Node-RED / Apps Script) para enviar el unifilar y el BOM.

## 9. Pendientes conocidos en el proyecto de referencia

- Q1 (100 A 2P) vs. conductores #4 AWG (85 A a 75 °C) vs. límite de entrada AC por Multi.
- Cables batería a Power In, VE.Bus, CAN y UTP Fronius a Ekrano: no están en la BOM.
- Sub-panel de cargas críticas, Q2 y Q4: no están en cotización ni BOM.
- Fusibles MEGA: calibre por definir (según manual de la batería y del Multi); sin Distributor, confirmar si hace falta protección por inversor.
- Cantidad de tubo EMT 1 1/4", ducto 4" y tapas; uso del gabinete 600 × 400 × 250.
- Relación de potencia Fronius 10 kW / Multis 2 × 5 kVA: confirmar en el manual de Victron.
- Tensión nominal DC de los breakers de string frente a Voc del string a temperatura mínima, y fusible serie máximo del módulo.

## 10. Reglas de trabajo para Claude Code en este tema

- Responde y documenta en español.
- Determinismo: ninguna cifra eléctrica del diagrama o del BOM sale de un LLM; todo sale de la configuración y de reglas explícitas.
- No mezcles pendientes dentro del PDF del plano.
- Antes de cambiar una convención de dibujo (sección 3.4) o un criterio de diseño (sección 4), pregunta al dueño.
- Si una cotización o BOM subida cae fuera del alcance (sección 3.1), avisa y no fuerces el dibujo.
