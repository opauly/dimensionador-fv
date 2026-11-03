# Criterios de diseño y verificaciones

Cifras de referencia para avisar al usuario; confírmalas siempre con datasheets y con el código aplicable
(en Costa Rica, el Código Eléctrico basado en NEC). Preséntalas como "revisar", no como veredicto.

## Topología

- El Fronius entra al sub-panel de cargas críticas, del lado de carga de Q2 (nunca antes de Q2).
- El neutro de las cargas de 120 V sale de los Multis (común a ambas unidades) hacia la barra de neutro del sub-panel.
  El Fronius 240 V inyecta entre L1 y L2: usa L1, L2 y tierra, sin neutro. Q3 es 2P.
- Enlace neutro-tierra solo en el tablero principal; en modo isla lo da el relé de tierra de los Multis (verificar ajuste).
- Grid Zero: el Ekrano limita la inyección y controla la potencia del Fronius por Ethernet (Modbus TCP), así que hace falta
  un UTP entre Fronius y Ekrano. Con el Fronius en AC-OUT el Multi mide el flujo; un medidor de red no es obligatorio,
  pero conviene confirmarlo al configurar el límite.
- Sin red: los Multis forman la red del sub-panel; el Fronius se desconecta por anti-isla, se reconecta y se regula
  por desplazamiento de frecuencia.

## Cálculos de revisión

- **Breaker de string DC:** ≥ 1.56 × Isc del módulo (1.25 × 1.25), sin pasar el fusible serie máximo del datasheet
  del módulo, con tensión nominal DC ≥ Voc del string a la temperatura mínima. Los 60 A que trae una BOM para
  strings de 8 módulos están sobredimensionados; el usuario usó 32 A para 8 × 620 W por MPPT.
- **Breaker AC del Fronius (Q3):** ≥ 125 % de la corriente máxima de salida (P / 240 V). Para 10 kW: 41.7 A × 1.25 = 52 A, así que 60 A.
- **Alimentador AC-IN:** comparar el breaker Q1 con la ampacidad del conductor (#4 THHN Cu: 85 A a 75 °C) y con el límite
  de corriente de entrada AC de cada MultiPlus-II (95 A por unidad en el 48/5000, manual de Victron: protección de 95 A o
  menos, es decir 90 A estándar; unos 50 A en el 48/3000). Un 100 A 2P con #4 es una discrepancia típica que hay que revisar.
- **DC de Multis:** verificar que #2 AWG en tramos de unos 10 m soporte la corriente DC máxima de cada Multi y
  definir fusible por unidad. Sin Distributor, solo FB1..FBn protegen a los Multis: confirmar si basta.
- **Relación de potencia:** Fronius (kW) vs. 2 × 5 kVA de los Multis en AC-OUT; confirmar el límite de PV acoplada en AC en el manual.

## Faltantes típicos en cotización y BOM

Sub-panel de cargas críticas y sus breakers (Q2, Q4); cables de batería a Power In; fusibles MEGA (calibre según
manual de la batería y del Multi); cables VE.Bus, CAN del BMS y UTP; alimentación DC del Ekrano; el SPD no siempre
indica su ubicación (el script lo dibuja en el sub-panel; confirmar).

## Lecciones de proyectos anteriores

- El bus DC de baterías cambió de "Power In + Distributor" a "solo Power In" por una respuesta mal recordada: pregúntalo siempre.
- El usuario no quiere tags numéricos ni tablas de conductores en el plano: el calibre va junto a cada tramo.
- Revisar la simbología: los símbolos de la leyenda no deben pisarse entre sí (hay espacio de sobra en la hoja).
