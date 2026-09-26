# Distribución de Utilidad en Cotizaciones — Especificación

**Para:** Dimensionador FV — módulo de generación de cotizaciones
**Origen:** desarrollado y verificado sobre el proyecto Casa Refugio, iterando contra errores reales encontrados en producción

## El problema que resuelve

Las cotizaciones no deben mostrar una línea explícita de "Utilidad" — es el único número que un cliente puede cuestionar o pedir reducir. La utilidad debe repartirse entre las demás líneas visibles. Pero repartirla ingenuamente (pesos manuales elegidos por cotización, o un recargo uniforme recalculado cada vez) produce un problema real y visible: **el mismo producto puede aparecer a precios distintos en cotizaciones consecutivas al mismo cliente**, sin ninguna razón que lo explique. Esto pasó en producción — paneles idénticos a $121.30/unidad en una cotización y $133.34/unidad en la siguiente, por el simple hecho de que el método de reparto había cambiado, no porque el costo real hubiera cambiado.

La solución no es un método más "justo" de repartir cada vez — es dejar de recalcular la distribución en cada cotización. Cada categoría recibe un **ancla fija** (precio unitario o tasa de margen, según el tipo de categoría) decidida una vez y mantenida constante entre cotizaciones. Solo una categoría absorbe la diferencia necesaria para cerrar el total exacto.

## Taxonomía de categorías

No todas las líneas de costo se comportan igual. El sistema requiere clasificar cada línea en uno de cuatro tipos:

### 1. Equipo con precio unitario fijo
Paneles, controladores, baterías, inversores, monitoreo — productos con cantidad y modelo específico.

**Ancla:** precio de venta **por unidad**, en dólares, fijado una vez por modelo de producto. No es un porcentaje — es un monto fijo.

$$\text{Precio mostrado} = \text{Precio unitario ancla} \times \text{Cantidad}$$

El precio unitario ancla se actualiza solo cuando el negocio decide deliberadamente cambiar lo que cobra por ese producto — nunca como efecto secundario de que el total de una cotización distinta necesite cuadrar.

### 2. Costos que escalan con el proyecto (no unitarios)
Materiales eléctricos, estructura de montaje, instalación/mano de obra — su costo real crece con el tamaño del proyecto (más paneles → más estructura; más equipo → más materiales de instalación), así que no tiene sentido un precio fijo en dólares.

**Ancla:** una **tasa de margen** (%) sobre el costo real, fijada una vez y mantenida constante.

$$\text{Precio mostrado} = \text{Costo real} \times (1 + \text{tasa ancla})$$

Esto es lo que se rompió en producción cuando se fijó margen = 0% en una categoría que históricamente llevaba +37.6% de margen: el costo real subió, pero el precio mostrado bajó, porque se removió un margen que el cliente ya había visto implícito en una cotización anterior. La tasa ancla debe reflejar lo que el cliente ya vio, no recalcularse desde cero.

**Nota práctica:** si no existe una cotización anterior de la que anclar la tasa, usar datos reales de proyectos comparables — ver la sección de benchmarking abajo.

### 3. La categoría residual (contenedor de utilidad)
Una sola categoría — típicamente etiquetada como "Diseño y Planos Eléctricos" o equivalente — **no representa un costo real trazable**. Es donde vive la utilidad que no se distribuyó explícitamente en las categorías 1 y 2.

**Verificación importante:** antes de usar esta categoría como residual, confirmar que efectivamente no es un costo real. En el caso de Casa Refugio, se rastreó que esta celda internamente es `Precio_sin_IVA − Costo_real` — es decir, exactamente el monto de utilidad, no un costo de diseño calculado. Si en la implementación real esta categoría *sí* tiene un costo base real (ej. horas de ingeniería facturables), el sistema debe separar esa porción real y usar solo el excedente como residual.

**Fórmula:**

$$\text{Diseño} = \text{Total objetivo} - \text{IVA} - \sum(\text{todas las demás categorías mostradas})$$

Esta es la única categoría cuyo valor mostrado puede variar significativamente entre cotizaciones sin generar una pregunta legítima del cliente, precisamente porque no reclama representar un costo específico y trazable.

### 4. Impuestos (IVA) — reglas fiscales, no de negocio
En Costa Rica, el IVA aplica sobre **servicios**, no sobre bienes/equipo. Las categorías de servicio típicas son Instalación y Diseño (la categoría residual). El IVA debe calcularse sobre lo que realmente se factura al cliente por esas categorías — no sobre una cifra interna que el cliente nunca ve.

$$\text{IVA} = 0.13 \times (\text{Instalación mostrada} + \text{Diseño mostrado})$$

**Advertencia de circularidad:** si Diseño es residual (categoría 3) y depende de "todo lo demás incluyendo IVA", pero IVA depende de Diseño, hay una referencia circular. Ver la siguiente sección para resolverla.

## Resolviendo la circularidad: orden de cálculo

No calcular Diseño e IVA directamente el uno del otro. Resolver primero el total combinado de servicios:

Sea:
- `Conocido` = suma de todas las categorías tipo 1 y tipo 2 (equipo a precio ancla + materiales/estructura a tasa ancla) — **totalmente determinado, no depende de servicios ni IVA**
- `S` = Instalación mostrada + Diseño mostrado (el total combinado de servicios, aún sin dividir)
- `Objetivo` = el total que la cotización debe alcanzar exactamente

Como `IVA = 0.13 × S`:

$$\text{Conocido} + S + 0.13S = \text{Objetivo}$$

$$S = \frac{\text{Objetivo} - \text{Conocido}}{1.13}$$

**Orden de cálculo correcto (sin circularidad):**

1. Calcular todas las categorías tipo 1 (equipo a precio unitario ancla) — independientes.
2. Calcular todas las categorías tipo 2 excepto Instalación (materiales, estructura a tasa ancla) — independientes.
3. Calcular Instalación (tipo 2, a su propia tasa ancla) — independiente, NO depende de S todavía.
4. `Conocido = suma de (1)+(2)+(3)`
5. `S = (Objetivo − Conocido) / 1.13`
6. `Diseño = S − Instalación` (del paso 3) — ahora sí es un residual, pero dentro de S, no directamente contra Objetivo.
7. `IVA = 0.13 × S = 0.13 × (Instalación + Diseño)` — seguro de calcular, ambos componentes ya se conocen.

## Ejemplo verificado (Casa Refugio, cotización de comparación)

Con Objetivo = $101,883.69:

| Paso | Categoría | Fórmula | Resultado |
|---|---|---|---|
| 1 | Paneles (84 × $121.30 ancla) | precio unitario × cantidad | $10,188.86 |
| 1 | Controladores, Baterías, Inversores, Monitoreo | (igual patrón) | $58,388.68 combinado |
| 2 | Materiales (costo real × tasa ancla) | — | $13,311.01 |
| 2 | Estructura (costo real × 1.0985) | — | $3,227.39 |
| 3 | Instalación (costo real × 1.3761) | — | $9,605.66 |
| 4 | Conocido | suma de 1+2+3 | $94,721.60 |
| 5 | S | (101,883.69 − 94,721.60) / 1.13 | $6,338.66* |
| 6 | Diseño | S − Instalación... | *(ver nota)* |
| 7 | IVA | 0.13 × S | — |

*Nota: los números exactos de Instalación/Diseño en la implementación final de Casa Refugio usaron una variante donde S se calculó sobre el conjunto completo Instalación+Diseño como combinado objetivo ($14,839.39 en esa iteración específica) — la fórmula estructural de arriba es la correcta; los valores numéricos dependen de qué tasas ancla se hayan fijado para Instalación y Estructura en esa cotización particular. Verificar siempre que `Conocido + S + IVA = Objetivo` exactamente antes de mostrar la cotización.

## Benchmarking de tasas ancla con proyectos reales

Cuando no hay una cotización anterior de la que anclar una tasa (producto nuevo, o primera vez fijando esta metodología), usar datos de proyectos completados como base:

1. Reunir el desglose de costo real (equipo, materiales, mano de obra) de proyectos pasados similares en tipo (off-grid vs. híbrido) y escala (kWp instalado).
2. Calcular `Materiales_real / Equipo_real` y `Mano_de_obra_real / Equipo_real` como porcentaje, por proyecto.
3. Priorizar proyectos del mismo tipo de sistema (off-grid vs. híbrido) sobre proyectos de escala similar — el tipo de sistema importa más que el tamaño para este ratio específico.
4. Usar el promedio de proyectos comparables como punto de partida para la tasa ancla, no como valor definitivo — es una señal direccional, especialmente con muestras pequeñas (n<5).

## Validaciones que la implementación debe incluir

1. **Reconciliación exacta:** `suma de todas las categorías mostradas + IVA == Objetivo`, verificado por código antes de permitir finalizar una cotización — nunca confiar en que las fórmulas cuadren "a simple vista".
2. **Diseño no negativo:** si el residual (paso 6) da un valor negativo, es una señal de que las tasas ancla de las demás categorías son demasiado altas para la utilidad disponible en esa cotización específica — debe generar una advertencia visible, no fallar silenciosamente.
3. **Persistencia de anclas:** los precios unitarios (tipo 1) y tasas de margen (tipo 2) deben guardarse como configuración del catálogo de productos/servicios, no recalcularse por cotización. Cambiarlos debe ser una acción explícita y deliberada del usuario, con un registro de cuándo y por qué cambiaron (para poder explicar, si algún cliente pregunta, por qué el precio de un producto cambió entre dos fechas).
4. **No usar la categoría residual como costo real:** si en el catálogo real de la implementación la categoría "Diseño" (o la que se use como residual) sí tiene un costo base trazable, separar ese costo base de la porción de utilidad antes de aplicar esta lógica.
