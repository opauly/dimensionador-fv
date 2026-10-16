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
| Registro real (v5 tal como se vendió) | — | pendiente |
| Prospecto original de PC-2026-010 | `7a628f04-1d76-47a4-bbe2-36229d5e48e7` | borrador viejo de ago-2026 |
