# Phase 25 — Finanzas (reemplazo de QuickBooks)

Estado: **25.1 lista** y **25.2 construida** (2026-11-23; migraciones 070 y 071 corridas). Falta que Oscar revise y guarde la importación. 25.3–25.4 pendientes.

## Objetivo
Tener las finanzas de Pauly & Co dentro del Dimensionador y cancelar QuickBooks:
gastos por proyecto, gastos de empresa, retiros del dueño, ingresos, dashboard,
proyecciones y exportación para un contador.

## Decisiones tomadas (Oscar, 2026-11-23)
| Tema | Decisión |
|---|---|
| Moneda | USD es la moneda principal. Hay cuentas y gastos en CRC; todo se convierte a USD para reportes. |
| Facturación | La factura electrónica de Hacienda se sigue emitiendo en otro sistema. La app solo registra. |
| Historial | Importar varios años de QuickBooks. |
| Usuarios | Solo Oscar por ahora. Todo debe ser exportable (Excel/CSV). |
| Cuentas | 2 por ahora: una en USD y una en CRC. Diseño permite agregar más. |

## Lo que ya existe (migración 020)
- `projects.contract_usd` — precio total del proyecto
- `project_payments` — calendario de pagos del cliente (ONVO, neto depositado)
- `project_expenses` — gastos por proyecto con categoría, presupuesto y recibo
- `project_labor`, `project_extras`, `project_invoice_items`
- `utils/currency.py` — tipo de cambio **actual** (no histórico)

## Diseño propuesto

### Dónde vive cada movimiento (decisión de implementación, 25.1)
En vez de copiar el dinero de los proyectos a un libro aparte (y tener que mantener dos copias
sincronizadas), la página Finanzas **une** las fuentes al leerlas (`calculations/finance.py`):

| Movimiento | Dónde se guarda |
|---|---|
| Pago de cliente | `project_payments` con `paid = true` (monto bruto; la comisión ONVO es su propio gasto Banco) |
| Gasto de proyecto | `project_expenses` con `paid = true` (+ `account_id`, `currency`, `amount_original`, `fx_rate` nuevos) |
| Adelantos de mano de obra | `project_labor.advances` |
| Gasto de empresa, retiro del dueño, otro ingreso, transferencia | `fin_transactions` (nueva) |

Un "Gasto de proyecto" registrado desde Finanzas se guarda en `project_expenses`, así que aparece
también en las pestañas del proyecto. Los pagos de clientes se siguen marcando en el proyecto.

`fin_transactions`: fecha, tipo, cuenta (y cuenta destino si es transferencia), categoría,
descripción, proveedor, moneda, monto original, tipo de cambio, `amount_usd`, notas,
`source` + `external_ref` (para importar sin duplicados).

### Tablas de apoyo
- `fin_accounts` — nombre, moneda, saldo inicial y fecha del saldo inicial.
- `fin_categories` — nombre, tipo (ingreso / gasto proyecto / gasto empresa / retiro), activa.
  Semillas: oficina, software, vehículo, combustible, seguros, contador, banco, impuestos,
  marketing, herramientas, capacitación, otros.
- `fin_recurring` (25.4) — gastos fijos (alquiler, software, seguros…): monto, moneda, frecuencia, día.
  Se usan para proyecciones y para crear el movimiento del mes con un clic.
- `fin_fx_rates` — tipo de cambio por fecha (BCCR venta), guardado para no consultarlo dos veces.
  El endpoint histórico de Hacienda estaba caído (503) el 2026-11-23; el de "hoy" funciona.
  Si falta un día se usa el más cercano guardado y se marca "estimado"; siempre se puede corregir.

### Reglas clave
- **Transferencias** entre la cuenta USD y la CRC no son ingreso ni gasto; solo mueven saldo.
- **Retiros del dueño** no cuentan como gasto de operación: se muestran aparte.
- **Tipo de cambio:** por defecto el de venta del BCCR del día del movimiento
  (API de Hacienda `indicadores/tc/dolar/historico`). Se puede corregir a mano si el banco aplicó otro.
- **Proyectos:** la pantalla de proyecto sigue igual; Finanzas lee sus pagos y gastos pagados directamente.

## Fases

### 25.1 — Base
- ✅ Migración `070_finanzas.sql`: `fin_accounts`, `fin_categories`, `fin_transactions`, `fin_fx_rates`
  + columnas de cuenta/moneda en `project_payments` / `project_expenses`. (`fin_recurring` pasa a 25.4.)
- ✅ Tipo de cambio por fecha: `utils/fx_history.py`.
- ✅ Página **Finanzas** (`/finanzas`): saldos por cuenta, resumen del período, registrar movimiento,
  lista filtrable (fechas, tipo, cuenta, proyecto); `/finanzas/cuentas` para nombres y saldos iniciales.
- ✅ Pagos, gastos y adelantos de proyectos aparecen solos (no se copian).
- ✅ Pruebas: `scripts/validate_phase25_finanzas.py`.

### 25.2 — Importar QuickBooks
Fuente: `Journal.xlsx` del export de QuickBooks (2026-11-23). Los reportes P&L, Balance y
Trial Balance del export salieron en cero; no se usan.

**Qué trae el export (revisado 2026-11-23):**
- 1,243 transacciones, abr-2019 → nov-2026: 971 gastos, 99 facturas, 173 pagos de clientes.
- Ingresos: completos y limpios por cliente (26 clientes, ~$819k cobrados). Cada factura tiene
  líneas con descripción del trabajo ("Sistema solar casona", "Remodelación eléctrica"…).
- Gastos: **no tienen cliente asignado**. El proyecto solo aparece en texto libre del memo
  ("Proyecto FV Lori Pickett", "Cotización 8", "Mantenimiento FV Rahab").
  ~61% del costo de ventas ($461k de $753k) trae "Proyecto…" en el memo; más se puede
  ligar por nombre de cliente dentro del memo.
- Una sola cuenta de efectivo, todo en USD. No hay separación USD/CRC.
- Pagos a "Oscar Pauly" ($115k, 204 movimientos) mezclan retiros personales (pagos de
  tarjetas, cuotas, "ayudas", "ganancia") con costos reales de proyecto ("Diseño eléctrico
  Avolta", "Servicios profesionales"). Casi todo está como *Cost of sales*, lo que infla el costo.

**Cómo se reconstruye:**
1. Proyectos históricos: un proyecto por trabajo facturado (cliente + descripción de la
   factura), no uno por cliente — p. ej. Rebeca Ruiz tiene ~15 trabajos distintos.
   La app propone la agrupación y Oscar la revisa.
2. Gastos: la app sugiere proyecto leyendo el memo (texto "Proyecto…", nombre de cliente,
   palabras clave). Pantalla de revisión rápida para confirmar o corregir en lote.
   Lo que no se asigne queda como gasto de empresa.
3. Pagos a Oscar Pauly: revisión dedicada para separar **retiro del dueño** vs **costo de proyecto**.
   Sugerencia automática por palabras ("Visa", "Promerica", "cuota", "ayuda", "ganancia" → retiro).
4. Categorías QB → categorías de la app (son solo 8, mapeo fijo).
5. Todo el histórico entra a la cuenta USD. Sin duplicados (`external_ref`); se puede deshacer por lote.
6. Cuadre: total cobrado, total gastado y saldo neto deben coincidir con el Journal.

**Construido (2026-11-23):** `/finanzas/importar` — sube el Journal, la app sugiere
(`calculations/qb_import.py`), se revisa por pestañas (Por revisar, Costos sin proyecto,
Retiros, Pagos a Oscar Pauly…), se puede dividir una línea, y «Guardar importación» escribe
(`database/qb_import_db.py`). Todo lo importado lleva `import_batch_id` y se puede deshacer.
- Facturas → proyectos `completed`, `system_type = historico`, `source = quickbooks`, `title` = primera línea
  de la factura, fecha de creación = fecha de la factura. No entran al margen sugerido de cotizaciones.
- Pagos: se reparten a la factura pendiente más antigua del cliente.
- Gastos: una fila por línea, con su parte del IVA (el IVA es costo).
- María José (ya en la app; en QB como Luis Fernando Castro) se salta sola. La línea de Fronius
  compartida con Juan Diego Castro ($5,703) hay que dividirla a mano.
- Prueba completa 2026-11-23: guardar y deshacer con el Journal real; el cuadre da exacto
  ($818,603.53 entradas, $803,701.25 salidas).

### 25.3 — Dashboard
- Ingresos vs gastos por mes (y año contra año).
- Utilidad del mes / año, separando retiros del dueño.
- Margen por proyecto: contrato vs gastado, % ejecutado del presupuesto.
- Cuentas por cobrar: pagos de clientes pendientes, con antigüedad.
- Gastos de empresa por categoría.
- Saldo por cuenta (USD, CRC convertido) y total.

### 25.4 — Proyecciones y exportación
- ✅ (adelantado 2026-11-24) Gastos recurrentes: `fin_recurring` (migración 072), `/finanzas/recurrentes`.
  Al abrir Finanzas se crean solos los del mes que ya tocan (memo con `[mes]`), sin duplicar
  (`recurring_id` + `period` único). Pruebas: `scripts/validate_phase25_recurring.py`.
- Flujo de caja a 1, 3 y 6 meses: saldo actual + pagos pendientes de proyectos activos
  − gastos recurrentes − gastos presupuestados que faltan.
- Escenarios simples: "si cierro X proyectos más al mes".
- Exportar a Excel/CSV: movimientos por rango de fechas, resumen mensual, por proyecto.

## Respuestas (2026-11-23)
- **IVA:** no se separa. Se registra el monto final pagado/cobrado. El contador hace la declaración aparte.
- **Históricos:** se reconstruyen como proyectos históricos por trabajo facturado (ver 25.2).

## Preguntas abiertas
1. ¿Quieres subir foto del recibo desde el teléfono al registrar un gasto?
2. Saldo inicial real de la cuenta USD y la CRC a una fecha de corte (el Journal da un neto de
   ~$14.9k, pero no refleja cuentas bancarias reales).

## Fuera de alcance
Contabilidad de partida doble, nómina, conexión directa con bancos, emisión de facturas electrónicas.
