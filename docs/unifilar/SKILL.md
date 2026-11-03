---
name: unifilar-hibrido-ac
description: Genera el diagrama unifilar (PDF de 1 hoja, 11x17 apaisado, con cajetín Pauly & Co) de un sistema solar híbrido acoplado en AC - inversor Fronius en el AC-OUT de dos Victron MultiPlus-II en split-phase 120/240 V, baterías en Lynx Power In (con o sin Lynx Distributor) y Ekrano GX - a partir de la cotización y la lista de materiales (BOM) del proyecto, haciendo al usuario solo las preguntas que no se puedan inferir. Úsalo siempre que el usuario pida un diagrama unifilar, "unifilar", single-line diagram, diagrama eléctrico o plano de un sistema FV híbrido / AC-coupled / respaldo con baterías Victron + Fronius, o suba una cotización y una lista de materiales de Pauly & Co y quiera el diagrama, aunque no nombre este skill.
---

# Unifilar híbrido acoplado en AC (Pauly & Co)

Produce un unifilar de una hoja que muestra, para cada tramo, el calibre y la función de cada conductor
(DC: + / - / tierra; AC: L1 / L2 / N / tierra). El dibujo lo hace `scripts/generate_unifilar.py` a partir de
un JSON de configuración; tu trabajo es leer los documentos, completar el JSON con criterio de ingeniero,
preguntar lo que falta, revisar el render y entregar.

## Flujo

1. **Lee los insumos.** Normalmente: cotización (PDF) + lista de materiales (PDF). Usa los skills `pdf-reading` /
   `file-reading` si el contenido no está en contexto. Extrae: cliente, ubicación, fecha, paneles (cantidad y W),
   baterías (modelo, cantidad, kWh), inversores (Victron y Fronius, modelo y kW), monitoreo (Ekrano o Cerbo),
   y de la BOM todos los cables (calibre, color, metros) y protecciones (breakers, fusibles, SPD).
2. **Confirma que el sistema cabe en el alcance** (abajo). Si no cabe, dilo y propón adaptar el script
   a mano en vez de forzar el dibujo.
3. **Pregunta lo necesario** (sección "Preguntas"). No preguntes lo que ya está en los documentos ni en la conversación.
4. **Arma el JSON** (`references/config.md` tiene el esquema; `assets/ejemplo_maria_jose.json` es un ejemplo real) y ejecuta:
   `python scripts/generate_unifilar.py config.json salida.pdf`
5. **Revisa el render**: `pdftoppm -r 110 -png salida.pdf prev` y mira la imagen. Busca textos que se pisan,
   rótulos que cruzan líneas y cualquier cosa que no coincida con la cotización. Corrige y vuelve a generar.
6. **Entrega** con `present_files` y, en el chat, un resumen corto de lo interpretado y de los puntos a verificar
   (sección "Verificaciones"). Los pendientes van en el chat, no dentro del PDF: el plano debe poder salir al cliente.

Nombre del archivo: `Proyecto_<Cliente>_<Lugar>_Unifilar_RevA.pdf`. El campo PROYECTO del cajetín va como
"Proyecto <Cliente> en <Lugar>".

## Alcance

Soportado: red 120/240 V 60 Hz; **2 × MultiPlus-II 120 V en split-phase** (MP#1 = L1 maestro, MP#2 = L2);
Fronius monofásico 240 V (1 o 2 MPPT = 1 o 2 strings) conectado en el **AC-OUT** de los Multis, dentro del
sub-panel de cargas críticas; baterías de 48 V (1 a 6, o 1 a 4 con Distributor); Ekrano GX.

Fuera de alcance (avisa al usuario): trifásico, un solo Multi, Fronius con 3 strings o más, acople en DC,
sistemas off-grid puros sin Fronius, Fronius en el lado de red (antes de los Multis).

## Preguntas

Primero intenta inferir. Para lo que quede, usa `ask_user_input_v0` (máximo 3 preguntas, opciones cortas)
o pregunta en prosa si necesitas texto libre. Estas son las que casi siempre hacen falta porque la cotización
no las responde:

- **Inyección a la red:** cero inyección (Grid Zero) o inyección permitida. Cambia el texto del Ekrano y el subtítulo.
- **Bus DC de baterías:** solo Lynx Power In, o Power In + Lynx Distributor. Con Distributor se dibujan los
  fusibles F1/F2 hacia cada Multi; sin él, los Multis cuelgan del bus del Power In y quedan protegidos solo por
  los fusibles de las baterías. El usuario ya corrigió esto una vez: no lo supongas.
- **Breakers DC de string:** la BOM suele traer un valor sobredimensionado. Pregunta o propón uno según la
  corriente del string (ver Verificaciones) y dibuja el que confirme el usuario.
- **Strings:** si la cotización no dice cuántos módulos van por string, deduce con el MPPT del Fronius
  (el usuario ya confirmó 8 × 620 W por MPPT en el Primo 10.0-1) y confírmalo.
- **Cables ambiguos de la BOM:** si no puedes asignar un cable a un tramo con seguridad, pregunta en vez de adivinar.

El formato de entrega es siempre PDF de una hoja; no lo preguntes salvo que pidan otro.

## Cómo leer la BOM de cables

La columna de comentarios de las BOM de Pauly & Co suele salir desalineada del texto extraído. Asignación habitual
(confírmala si hay dudas):

| Cable en la BOM | Tramo |
|---|---|
| #10 AWG SOLAR rojo y negro | strings FV (+ / -), arreglo a gabinete DC y gabinete DC a Fronius |
| #10 AWG THHN verde | tierra del arreglo FV |
| #6 AWG THHN verde | tierra de equipos (principal, Multis, sub-panel, Fronius) |
| #4 AWG THHN negro / rojo / blanco | L1 / L2 / N de AC-IN, AC-OUT y salida del Fronius (el Fronius no usa N) |
| #2 AWG THHN rojo y negro | DC + / - entre Lynx y cada Multi |

Lo que la BOM no trae se dibuja marcado "no listado en BOM, por definir": cables batería a Power In,
alimentación del Ekrano, VE.Bus, CAN del BMS y UTP Fronius-Ekrano.

## Verificaciones (van en el chat, tras entregar)

Calcula y avisa solo lo que aplique; son revisiones de ingeniería, no verdades: pide al usuario confirmar con datasheets.
Detalle y cifras en `references/diseno.md`. Resumen:

1. Breaker de AC-IN (Q1) vs. calibre del alimentador vs. límite de entrada AC de cada Multi.
2. Breaker de string vs. Isc del módulo (≈1.56 × Isc), máximo fusible serie del módulo y tensión DC nominal del breaker.
3. Breaker AC del Fronius (125 % de su corriente máxima de salida).
4. Ampacidad de los #2 AWG contra la corriente DC máxima de cada Multi; protección DC por inversor si no hay Distributor.
5. Elementos que no están en cotización/BOM: sub-panel de cargas críticas, Q2/Q4, UTP Fronius-Ekrano (necesario para Grid Zero),
   cables de batería y de comunicación.
6. Inconsistencias de nombres (p. ej. la BOM dice "Cerbo" y la cotización "Ekrano").
7. Relación de potencia: Fronius vs. potencia de los Multis en AC-OUT (confirmar el límite en el manual de Victron).

## Reglas de dibujo (ya implementadas; no las rompas al editar el script)

- Una sola hoja; sin tags numéricos: el calibre y función de cada conductor van en letra pequeña junto a su tramo.
- Positivo en rojo, negativo en negro, tierra en verde discontinuo, comunicaciones en azul discontinuo.
- Estado BORRADOR / REV A en rojo hasta que el usuario diga que se emite.
- Cajetín: marca Pauly & Co, cliente, ubicación, fecha, responsable (Ing. Oscar Pauly Calvo · IE-30111), "Hoja 1 de 1".
