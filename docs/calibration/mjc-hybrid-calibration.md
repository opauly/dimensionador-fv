# Calibración teoría vs. realidad — María José Castro (Híbrido, Carrillo)

**Estado:** abierto — esperando puesta en marcha y datos reales de consumo.
**Creado:** 2026-10-16 · **Dueño:** Oscar Pauly
**Pregunta:** ¿qué predicción de consumo de cargas críticas se acercó más a la realidad — la **cotizada (v5, calculadora Excel)** o la del **wizard**?

> Las predicciones de abajo se **congelaron antes de conocer la realidad**. No editarlas después: si el modelo cambia,
> se agrega una sección nueva, no se reescribe esta.

## 0. Checklist del ticket

- [x] Escenario W (wizard) congelado: PC-2026-021, versión bloqueada (`18dcd308-bb53-4b8e-83e6-8836f17425f9`)
- [x] Escenario Q (cotizado v5) documentado desde `Dimensionador Solar OFF GRID (V0.1) - María José Castro v4.xlsx`
- [ ] Registro **real** creado en la herramienta (reproduce v5 tal como se vendió) → ganada → proyecto → pagos → gastos
- [ ] Puesta en marcha
- [ ] Datos medidos (VRM/Ekrano) ≥ 30 días con ocupación → sección 5
- [ ] Puntuación y conclusiones → sección 6

## 1. Contexto del proyecto

- Cliente: María José Castro · Carrillo, Guanacaste · Híbrido, **solo cargas críticas** (sub-panel), 120/240 V split-phase.
- Distribuidora/tarifa asumidas: COOPEGUANACASTE · T-RE.
- Cargas críticas (lista del 11-ago, 13 circuitos): potencia de diseño **13 250 W**, carga simultánea estimada **8 735 W** (FD 65.9 %). Incluye **2 A/C** (1 600 W c/u) y tomacorriente de telecomunicaciones (routers de internet). *No hay servidor de cómputo.*
- Sitio **en construcción** (sin consumo real todavía).
- Cotización vendida: **v5** — 16× JA Solar 620 W (9.92 kWp), 4× Pylontech Fidus (19.20 kWh), 2× Victron MultiPlus-II 5000 VA, 1× Fronius Primo 10.0-1, Ekrano GX. Total **$25 830**.
- Lo realmente comprado (proforma HCG 180-2026, 18-ago): 16× panel bifacial **SUN600 600 W** (no JA 620 W), 2× MultiPlus-II 48/5000/70-95, 4× Pylontech Fidus, Ekrano GX, 3× Lynx Power In, medidor VM-3P75CT, estructura Chiko. **Sin Fronius Primo en esa proforma.**

## 2. Procedencia de las predicciones congeladas

| Escenario | Fuente | Fecha |
|---|---|---|
| Q (cotizado) | Excel de la calculadora (hoja *Dimensionamiento…* y cadena de hojas ocultas) → PDF v5 | ago-2026 |
| W (wizard) | Herramienta Flask `main_jinja`, commit `a60fcfb` **más cambios sin commitear de la Phase 24** (`calculations/design_targets.py`, `goals_check.py`, `s6_objetivos.py`, plantillas `_s6*_equipos.html`, etc.) | 2026-10-16 |

La versión W está **bloqueada** en la base de datos (inmutable) — esa es la fuente autoritativa. El resultado del paso *Objetivos*
(piso / punto óptimo / techo) **no se guarda en el blob**, por eso se transcribe aquí desde la pantalla. El wizard está en desarrollo
activo (Phase 24): re-ejecutarlo más adelante puede dar números distintos.

## 3. Escenario Q — lo cotizado (v5, calculadora Excel)

**Entradas** (hoja *Datos de Entrada*): estas **no** son la lista de cargas críticas de María José.

| Carga | Cant. | kW | h/día | kWh/día al 100 % |
|---|---|---|---|---|
| Tomas generales | 3 | 1.00 | 8 | 24 |
| Refrigerador | 1 | 0.75 | 12 | 9 |
| Iluminación | 1 | 1.00 | 10 | 10 |
| Microondas | 1 | 1.50 | 2 | 3 |
| Servidor de cómputo (24 h) | 1 | 0.75 | 24 | 18 |
| **Total al 100 %** | | 7.0 kW | | **64** |

Sin cantidad (= 0): tomas de cocina, bomba, lavadora, **aire acondicionado**, secadora, equipo de cómputo.

**Cadena de cálculo**

1. Factores de corrección fijos por carga (*CorrCargCons*, hoja *Patrones de consumo inicial*): tomas 0.2, refri 0.2, iluminación 0.1, microondas 0.2, servidor 0.4 → **15.4 kWh/día**.
2. Re-distribución por curvas horarias (suma de la curva, *Curvas de consumo!Y28*): **16.68 kWh/día** (+8 % sobre el paso 1; inconsistencia interna — la energía por carga cambia al repartirla en horas "promedio" vs. horas activas del patrón).
3. Coeficiente de corrección **0.5830** = (DOA 0.4 días × TM 1.0) ÷ (IL 0.97 × WL 0.98 × BE 0.90 × SOC 0.90 × TC 0.90 × CCE 1.00 × DF 0.99).
4. **Carga corregida = 16.68 × 0.583 = 9.72 kWh** ← impreso en el PDF v5 como *"Energía diaria estimada (kWh)"*.

**Lectura correcta del 9.72:** es la energía de batería requerida para **0.4 días de autonomía** (con pérdidas), **no** el consumo diario.
La cantidad comparable con un consumo medido es **16.68 kWh/día**.

| Predicción Q | Valor | Comparable con |
|---|---|---|
| Consumo diario crítico (base calculadora) | **16.68 kWh/día** | kWh/día medido en AC-out del MultiPlus |
| Energía corregida 0.4 días autonomía | 9.72 kWh | (no es consumo diario) |
| Potencia máxima (CEILING(7 kW × 1.3, 0.5)) | **9.5 kW** | pico medido AC-out |
| Ahorro estimado en factura (PDF v5) | **85 %** | reducción real de factura de la casa |
| Equipo vendido | 9.92 kWp · 19.20 kWh · 2× MP-II 5000 VA | SoC mínimo / noches de respaldo |

**Defectos conocidos de Q (documentados, no corregidos aquí)**
- Sin A/C (el wizard los estima en ~8 kWh/día) y con un servidor 24 h de 7.2 kWh/día (43 % de su carga) que no existe.
- La hoja de dimensionamiento da **6× 540 W (3.24 kWp)** y 4 baterías AGM de 2.76 kWh; el equipo vendido (16× 620 W, 4× Pylontech 4.8 kWh) **no se deriva de ella** — la procedencia del arreglo FV de v5 no está documentada en el libro.
- Etiqueta engañosa en el PDF (9.72 no es energía diaria).

## 4. Escenario W — lo que dice el wizard

Lista cargada (13 circuitos, importada por texto) → perfil del wizard (paso Demanda). Cada circuito entra como **potencia de diseño × horas**.

| Carga | Categoría | kW conectado | h/día | kWh/día | FD | kWh/día diversif. |
|---|---|---|---|---|---|---|
| Tomacorriente para microondas | Electrodomésticos | 0.80 | 0.5 | 0.40 | 55% | 0.22 |
| Iluminación principal | Uso general | 1.15 | 5 | 5.75 | 70% | 4.02 |
| Tomacorriente para refrigeradora | Cíclica fija | 0.50 | 2.4 | 1.20 | 95% | 1.14 |
| Tomacorrientes de sala y exterior | Uso general | 1.50 | 3 | 4.50 | 70% | 3.15 |
| Tomacorrientes de cocina 1 | Electrodomésticos | 1.50 | 0.3 | 0.45 | 55% | 0.25 |
| Tomacorriente de baño | Uso general | 1.50 | 3 | 4.50 | 70% | 3.15 |
| Tomacorrientes de cocina 2 | Electrodomésticos | 0.50 | 0.9 | 0.45 | 55% | 0.25 |
| Tomacorrientes del cuarto principal | Uso general | 1.00 | 3 | 3.00 | 70% | 2.10 |
| Tomacorrientes de cuartos | Uso general | 1.00 | 3 | 3.00 | 70% | 2.10 |
| Tomacorriente para portón eléctrico | Uso general | 0.50 | 3 | 1.50 | 70% | 1.05 |
| Tomacorrientes de telecomunicaciones | Uso general | 0.10 | 24 | 2.40 | 70% | 1.68 |
| A/C Dormitorio Principal | Climatización | 1.60 | 3.84 | 6.14 | 65% | 3.99 |
| A/C Dormitorio Secundario 1 | Climatización | 1.60 | 3.84 | 6.14 | 65% | 3.99 |
| **Total** | | | | **39.43** | | **27.09** |

Total del perfil: **39.43 kWh/día** bruto · **27.09 kWh/día** diversificado (× factor de demanda).
Por categoría (bruto): Uso general 24.65 · Climatización 12.28 · Electrodomésticos 1.30 · Cíclica fija 1.20.

**Paso Objetivos — recomendación sin equipo** (metas por defecto, preset *Recomendado*, noches de respaldo 1.5, reserva SoC 35 %, carga nocturna 40 %):

| | Piso | Punto óptimo | Techo |
|---|---|---|---|
| Paneles (DC) | 9.7 kWp | **11.1 kWp** | 12.6 kWp |
| Batería (nominal) | 15.8 kWh | **22.8 kWh** | 34.6 kWh |
| Inversor (AC, isla) | 10.4 kW | **11.8 kW** | 13.0 kW |
| Reducción de kWh | 30 % | 45 % | 45 % |

Carga crítica 27.1 kWh/día, **pico 8.8 kW**; batería definida por *ciclado diario*, paneles por *cobertura FV*.

**Paso Equipos — escenarios automáticos (modelo de confiabilidad anterior, aún no derivado de Objetivos).** Se guardó el escenario 2 por defecto:
28× 620 W (17.36 kWp) · 18× Fidus (89.46 kWh) · 4× MultiPlus-II 3 kW · 3 controladores · SoC mín. simulado 44 % · generación 57.48 kWh/día.
(Escenario 1: 24 paneles / 13 baterías / 64.6 kWh · Escenario 3: 32 paneles / 32 baterías / 159 kWh.)

| Predicción W | Valor | Comparable con |
|---|---|---|
| Consumo diario crítico bruto | **39.43 kWh/día** | kWh/día medido AC-out |
| Consumo diario crítico diversificado | **27.09 kWh/día** | idem |
| Demanda pico | **8.82 kW** (13.25 kW instalados) | pico medido AC-out |
| Carga nocturna 18:00–06:00 | 40 % del día (supuesto, mediana de 9 sitios) | fracción nocturna medida |
| Reducción de factura | **47.4 %** (₡46 427 de ₡98 019/mes) | reducción real |
| Recomendación sin equipo | 11.1 kWp · 22.8 kWh · 11.8 kW | equipo vendido (9.92 kWp · 19.2 kWh · 10 kVA) |

**Salvedades de W:** (a) la "factura actual" asume que la casa completa = cargas críticas (alcance `primary`), así que el 47 % no es una estimación de la factura real de toda la casa;
(b) factores de demanda v1 sin calibrar; (c) los circuitos de tomacorrientes entran por su *asignación de circuito*, no por carga conectada real — se sospecha sobreestimación
(p. ej. iluminación 1.15 kW × 5 h = 5.75 kWh/día vs. 1.0 kWh/día en Q).

**Observación ya disponible (sin esperar datos):** el equipo vendido (9.92 kWp · 19.2 kWh) cae entre el *piso* y el *punto óptimo* de la recomendación del wizard, aunque los kWh/día
declarados difieren ~2.3×–2.4× (16.68 vs. 39.43). Es decir: el hardware coincide más que el consumo declarado.

## 5. Datos medidos (completar tras la puesta en marcha)

**Fuente:** VRM del **Ekrano GX**. En un híbrido con sub-panel de críticas, la **salida AC del MultiPlus** *es* el consumo de cargas críticas — comparable 1:1 con ambos escenarios.
(La casa completa NO es comparable salvo para el ahorro en factura; para eso usar el medidor de red VM-3P75CT / la factura.)

**Condiciones de validez**
- ≥ 30 días **consecutivos con la casa ocupada**; excluir días de pruebas/puesta en marcha y cortes de red.
- Registrar el rango de fechas y la estación: los A/C dominan y dependen del clima (Guanacaste: época seca dic–abr es la más calurosa). Idealmente repetir en época lluviosa.
- Resolución diaria de VRM es suficiente; pico y fracción nocturna requieren la serie de 15 min.

| Métrica | Medido | Rango de fechas | Notas |
|---|---|---|---|
| kWh/día AC-out — media | | | |
| kWh/día AC-out — mediana / p90 | | | |
| Pico AC-out (kW, p99 de 15 min) | | | |
| Fracción nocturna 18:00–06:00 | | | |
| SoC mínimo de la batería | | | |
| Generación FV media (kWh/día) | | | |
| Factura real vs. antes (₡/mes, reducción %) | | | |

## 6. Puntuación (regla fijada de antemano)

- **Métrica primaria:** error relativo de kWh/día crítico = (predicho − medido) ÷ medido, comparando **Q = 16.68** contra **W = 39.43 (bruto)** y **27.09 (diversificado)**. Gana el de menor |error|.
- **Secundarias:** pico kW (Q 9.5 · W 8.82) · fracción nocturna (W 40 %) · reducción de factura (Q 85 % · W 47.4 %, con la salvedad de arriba) · adecuación del equipo (SoC mínimo, noches de respaldo).
- **Interpretación orientativa** (medido ÷ predicho):
  - Si el medido cae cerca de Q → la calculadora acertó el *nivel*; revisar por qué el wizard sobreestima (circuitos como carga conectada).
  - Si el medido cae cerca de W-diversificado → el wizard acertó y la calculadora subestimó (A/C omitidos); revisar el dimensionamiento de v5.
  - Si cae entre ambos → ajustar horas/factores del wizard (categorías *uso general* y *climatización*) hacia el medido y anotar el factor de calibración.
  - Con un solo sitio la conclusión es **una observación, no una calibración**: vale como el punto 10 de la flota (ver `docs/design-calibration-2026-08.md`).

## 7. Hallazgos de la creación de este ticket (independientes del resultado)

1. Paso 1 del wizard no permite re-vincular a un **prospecto** existente → duplica prospectos (el buscador solo mira clientes).
2. **Siguiente** queda deshabilitado tras acciones en la página (PVGIS en el paso 3, importar cargas en el paso 4) hasta recargar.
3. El modelo de carga del wizard espera aparatos reales; los circuitos de diseño se sobreestiman (ver arriba).
4. Paso Equipos: los escenarios automáticos (modelo anterior) contradicen la recomendación del paso Objetivos (89 kWh vs. 22.8 kWh) — Phase 24 en curso.
5. El PDF v5 rotula "Energía diaria estimada" a una cifra que es energía de batería a 0.4 días de autonomía.
6. Varios equipos del catálogo no tienen precio → el costeo del gemelo W queda incompleto (total $21 139 no representativo).
7. El diálogo `hx-confirm` de "Bloquear versión" se descarta en el navegador embebido (no afecta a un navegador normal).

## 8. Registros en la herramienta

| Registro | Id | Estado |
|---|---|---|
| Gemelo W — PC-2026-021 | propuesta `6afa2ef1-b210-43e1-a77b-32a4a27a1d63` · versión `18dcd308-bb53-4b8e-83e6-8836f17425f9` | bloqueada, **no enviada**, nunca ganada/promovida |
| Registro real (v5 tal como se vendió) — PC-2026-022 | propuesta `c3610166-cd26-47a2-aa67-2cff1a6e0622` · versión `20170855-6aa6-43f7-851a-22241eaacabd` · prospecto `7396ea36-6156-4058-801e-7a0370e82132` | bloqueada → PDF generado → enviada → **ganada** (2026-10-16) → promovida a proyecto `88cec95d-cc3a-4347-9a55-6a80b59daeb9` (contrato $25 830, pagos 80/20 = $20 664 + $5 166, presupuesto = costo real Sheet12 $21 648.40) |
| Prospecto original de PC-2026-010 | `7a628f04-1d76-47a4-bbe2-36229d5e48e7` | borrador viejo de ago-2026 |

## 9. Calibración de precio — hoja `Sheet12` vs. wizard (añadido 2026-10-16, no forma parte de las predicciones congeladas)

Objetivo (Oscar): que el wizard se acerque a **$25 770** (precio de la hoja "Dimensionamiento paneles y baterías (HCG) – Oscar", C35). El PDF v5 ($25 830) lleva ajustes de conversación con la clienta; la hoja es la referencia.

**Costo real (C17:C32): $21 648.40** — paneles 1 760 · baterías 4 600 · monitoreo Victron 565 · inversor off-grid 1 800 · inversor on-grid Fronius 3 220.50 · accesorios 1 502.90 · estructura 800 · mueble baterías 300 · materiales 1 500 · mano de obra 3 500 · transporte 600 · estadía 1 500 · controladores/diseño/autotransformador 0. IVA 0 % en todas las líneas (D34 = 0).

| Convención | Fórmula | Resultado |
|---|---|---|
| Hoja (utilidad 16 % **sobre precio**) | `MROUND(costo ÷ (1 − 0.16), 10)` | **$25 770** |
| Wizard, margen 16 % (**sobre costo**) | `costo × 1.16` | $25 112 |
| Wizard, margen 19 % (el paso de 0.5 impide 19.04) | `costo × 1.19` | **$25 761.59** (−$8 vs. hoja, −$68 vs. v5) |

Hallazgos:
1. La "utilidad 16 %" de la hoja equivale a **19.04 % de recargo sobre costo**; el wizard (Phase 23) usa recargo sobre costo. Con la misma cifra nominal el wizard queda ~$660 por debajo. Decisión pendiente: etiquetar claramente la convención o ofrecer "margen sobre precio".
2. El campo de margen tiene `step=0.5`: no permite el 19.04 exacto.
3. Para reproducir la hoja hubo que **editar a mano** 11 de 15 líneas: catálogo de baterías $1 100 (hoja $1 150), monitoreo $500 (hoja $565), "Diseño $300 @13 %" y "Permiso de interconexión $1 000" sembrados que la hoja no tiene, y 4 líneas inexistentes en el wizard (Fronius on-grid, accesorios, mueble de baterías, estadía).
4. **Topología AC-acoplada no soportada:** el v5 vendido es MultiPlus + Fronius on-grid en la salida AC de cargas críticas; el wizard solo modela FV por controladores MPPT DC (exige 2 MPPT aunque v5 no lleva ninguno) y marca «Reducción estimada ~0 %» al ser paquete de cargas críticas.
5. Los precios de catálogo de paneles ($110 × 16) y MultiPlus ($900 × 2) ya coinciden con la hoja.

Notas del paso a proyecto (2026-10-16):
6. El quote del wizard cierra en **$25 761.59** pero el contrato real es **$25 830**: se capturó el contrato real en «Mover a Proyecto» (campo editable).
7. «Mover a Proyecto» pre-llena el presupuesto por rubro con los **precios mostrados** (con margen), así que la suma del presupuesto = el contrato ($25 761.59) y la utilidad proyectada sale 100 %. Para que el seguimiento de gastos sea útil se sustituyó por el costo real (Sheet12). Debería pre-llenarse con `costo_real`.
8. Con el wizard, un clic en «Generar PDF» del paso 9 (bloqueada) navega a la lista en vez de mostrar el enlace (el PDF se generó bien desde la lista).

## 10. v2 — cotización con costos de catálogo y proformas (añadido 2026-10-17)

La hoja Excel/PDF deja de ser la referencia: el objetivo es que el **wizard** sea la cifra oficial y el proyecto real la contraste. Pasos:

1. **Catálogo corregido** a costo neto de proforma + condición de IVA: JA Solar 620 $110 (exento) · MultiPlus-II 48/5000 $900 (exento) · Pylontech Fidus $1 150 (exento; antes $1 100) · Fronius Primo 10.0-1 $2 850 + 13 % (antes $3 350 sin IVA) · Ekrano GX $550 + 13 % (antes $500). Panel realmente comprado añadido: Sunergy SUN600-66MDH12RS (600 W, Voc 48.15 · Vmp 40.46 · Isc 15.86 · Imp 14.95 V/A, −0.30 %/°C, 2.382 × 1.134 m, 33 kg), $110 exento. Fuentes: HCG proforma 180-2026 (2026-08-18), Nundi N021-2026 (2026-07-14).
2. **Wizard:** las líneas de equipo de Costos (Off-Grid/Híbrido y Grid Zero) toman ahora su IVA por defecto de `cost_iva_rate` del catálogo (antes fijo en 0 %).
3. **v2 de PC-2026-022** (versión `1fe000a1-4d1e-46c6-bacc-7aebc8fa75c8`, bloqueada): 16 × SUN600 (9.60 kW), 2 × MultiPlus-II, 4 × Fidus, Ekrano, Fronius como fila personalizada; estructura $529.50 y accesorios $910 tomados de la proforma HCG; resto de líneas sin proforma (mano de obra 3 500, materiales 1 500, transporte 600, estadía 1 500, mueble 300) = **marcadores de posición de Sheet12** hasta reemplazarlos por gastos reales. Margen 19 %. Resultado: subtotal **$24 275.41** + IVA $748.68 = **$25 024.09** (v1: $25 761.59; contrato real: $25 830).
4. Supuestos a vigilar: sin línea de permiso de interconexión (wizard la sembraría con $1 000); sin diseño ($300 por defecto); servicios con IVA 0 % como en el contrato; 2 controladores MPPT forzados por el wizard con costo 0 (el v5 es AC-acoplado); el estimado de generación del wizard cae de 32.85 a 31.79 kWh/día por pasar de 620 a 600 W.
5. **Lectura:** las líneas de servicio estándar del wizard (estructura, mano de obra, materiales, transporte) están en $0 por defecto — la cotización «pura» del wizard no se puede costear hasta que esos valores se estandaricen con datos reales (ver importador de proformas, pendiente).

## 11. Importador de proformas y tarifas por Wp (añadido 2026-10-18)

- **Migración 050**: `price_updated_at` / `price_source` en las cinco tablas de catálogo y en `service_defaults`; `service_defaults.cost_per_wp`; tabla `price_imports` (bitácora de cada importación). Aplicada en Supabase.
- **Importador** (`/proformas/importar`, desde Admin → Equipos/Servicios y desde el paso Costos): lee el PDF (cantidad, unitario sin IVA, etiqueta EXEV / IVA 13), valida que las líneas sumen el subtotal impreso, sugiere destino por línea (equipo del catálogo, «Estructura de montaje», «Accesorios», ignorar) y solo escribe tras confirmar. Probado con HCG 180-2026 y Nundi N021-2026.
- **Tarifas por Wp** que pre-llena el paso Costos (× kWp cotizados): estructura **$0.0552/Wp** (proforma HCG, $529.50 / 9.6 kWp), mano de obra **$0.3528/Wp** y materiales **$0.1512/Wp** (marcadores de la hoja de María José: $3 500 y $1 500 a 9.92 kWp). Accesorios $910 fijo (proforma HCG). Transporte, estadía y mueble de baterías en $0 (opcionales).
- Las dos tarifas de mano de obra/materiales son un solo punto de dato. Se corrigen en Admin → Servicios (campo USD/Wp) cuando haya gastos reales de proyectos cerrados.

## 12. Ciclo de vida real: pagos y gastos (añadido 2026-10-18)

**Cobros** (proyecto `88cec95d-…`): $10 000 (2026-08-16) + $10 000 (08-17) + $664 (08-18) = **$20 664 = el 80 %**, transferencia a BAC USD; pendiente $5 166 (20 % contra entrega).

**Gastos reales** (de los comprobantes de transferencia, no de las proformas):

| Proveedor | Pagado | Fecha | Detalle |
|---|---|---|---|
| HCG 180-2026 | **$9 991.81** | 2026-08-31 | lista $10 149.50 − descuento $416.33 + IVA $258.64 (sobre lista) |
| Nundi N021-2026 | $5 700.00 (+$3 comisión) | 2026-07-14 | 2 × Fronius **sin IVA** (sin factura electrónica); 1 aplicado aquí ($2 850), el otro reservado para el proyecto de Juan Diego Castro |

Presupuesto (costo Sheet12) vs. real a la fecha, sin IVA: Equipo $12 245.50 → $11 143.67 · Materiales $3 802.90 → $1 439.50 (solo estructura y accesorios; faltan materiales eléctricos) · Mano de obra, viáticos aún sin gasto. El panel real (SUN600, $110) coincide con el precio de catálogo del JA Solar; la diferencia fuerte es el Fronius ($2 850 real vs. $3 220.50 presupuestado con IVA) y los accesorios/estructura ($1 439.50 reales vs. $2 302.90 presupuestados).

Hallazgos:
1. El Fronius figura en catálogo con IVA 13 % (la proforma lo etiqueta así) pero la compra real se hizo **sin factura → sin IVA**. El indicador de catálogo refleja la etiqueta de la proforma, no si se pidió factura.
2. El descuento global de HCG no cabe en una línea: se registró como gasto negativo «Descuento HCG» para que el total cuadre con la transferencia.
3. La comisión SINPE ($3 por transferencia) no se carga a ningún proyecto.

## 13. Precio final vs. cotizado (añadido 2026-10-18)

El precio vendido ($25 830) no es el de ninguna cotización de la herramienta: salió de v4 ($26 130, primera oferta a la clienta) menos **$300** de precio especial tomados de materiales eléctricos (v5). Para no tener que decidir *qué línea* cambiar cuando un cliente negocia, el proyecto ahora guarda la cotización de referencia (`projects.quoted_usd`) y el motivo (`price_adjustment_reason`, migración 051); el descuento ($ y %) se deriva siempre de `quoted_usd − contract_usd` y las líneas/versiones de la cotización no se tocan. «Mover a Proyecto» muestra el descuento en vivo y el proyecto lo muestra en el encabezado y bajo Utilidad; se puede editar después en «Ajuste de precio». Este proyecto: cotizado $26 130 → final $25 830 (−1.15 %); utilidad bruta sin el descuento sería $13 546.83 frente a $13 246.83 con él (a la fecha de registro, con costos parciales).
