# Revisión del ensayo — Nike Lindora y nube híbrida

Guion simulado: 50 intervenciones y 2599 palabras. Stuart interrumpe con cortesía dos desvíos, usa los documentos previos para la logística y dedica las repreguntas a presupuesto, datos, dependencias y continuidad.

## Duración

Los ritmos son hipótesis de cálculo sobre palabras separadas por espacios. Se añaden tres minutos para pausas, consulta y transiciones; no se grabó voz ni se ejecutó una llamada. La pronunciación de cifras y las aclaraciones adicionales pueden variar el tiempo.

| Ritmo supuesto | Duración total | Margen frente a 30 minutos |
| --- | --- | --- |
| 110 palabras/minuto | 26:59 | 03:01 |
| 120 palabras/minuto | 24:49 | 05:11 |
| 130 palabras/minuto | 23:25 | 06:35 |

## Separación económica del caso

| Partida | Importe USD | Alcance |
| --- | ---: | --- |
| Proyecto digital completo | 180.000 | Techo general con impuestos |
| Desarrollo y puesta en marcha de nube | 45.000 | Honorarios de la primera etapa; AWS operativo y conexiones verificadas |
| Consumo de nube | 6.000 | Límite total del 18 de noviembre al 20 de diciembre, con impuestos |
| Mantenimiento de nube | 4.000 | Cobertura del mismo período, separada del consumo |
| Fases de programación | 105.000 | Trabajo posterior de aplicación |
| Contingencia | 20.000 | Requiere autorización para su uso |

Las cinco asignaciones suman USD 180.000; el techo general no se suma otra vez. Los tractos de la primera etapa son USD 18.000 + USD 13.500 + USD 13.500. Los importes son construcción del caso, no precios AWS cotizados ni una estimación de viabilidad aprobada.

## Ubicación y autoridad de los datos

| Dominio | Ubicación y autoridad | Condición de la reunión |
| --- | --- | --- |
| Textos, rutas, horarios, precios, patrocinio y preguntas frecuentes | Base de datos en nube | Información pública |
| Totales agregados de cupos | Copia informativa en nube | No identifican personas; no autorizan ventas |
| Cupos y reservas de venta | Nike on-premise | Autoridad para reservar y evitar sobreventa |
| Corredores, compradores, contactos, consentimientos, órdenes y estados | Nike on-premise | No persistir en AWS, tampoco en logs, copias, cachés o colas |
| Pagos | EasyPay y Nike, según sus responsabilidades | No guardar números de tarjeta; conservar referencias autorizadas en Nike |
| Tiquetes y envíos de correo, incluidos pendientes | Servicio y registros de Nike | Sin contenido personal almacenado en servicios de correo o colas AWS |
| Facturas y respuestas fiscales | Hacienda y bases financieras on-premise de Nike y Gatorade | Excepción de distribución expresamente autorizada en el caso; no copia en AWS |

La prohibición del caso se refiere a persistencia de datos restringidos en AWS. El diseño posterior debe delimitar su tránsito, procesamiento y observabilidad para evitar que terminen almacenados incidentalmente. La factura autorizada a Gatorade no habilita compartir la base de corredores ni sus contactos.

## Objetivos de recuperación y disponibilidad

| Servicio o información | Objetivo o condición |
| --- | --- |
| Información pública | Disponible 24×7; objetivo del 99,9 % mensual |
| RTO solicitado para el servicio | 30 minutos habituales; 10 minutos en apertura y carrera |
| Dependencia Nike on-premise | Hasta 45 minutos de recuperación; pausa de venta 23:00–23:20 |
| Dependencia EasyPay | Hasta 30 minutos de recuperación según el convenio simulado |
| RPO de contenido público | Hasta 15 minutos de cambios editoriales repetibles |
| RPO de inscripciones confirmadas y pagos aprobados | Cero pérdida tolerada; conciliación desde registros autorizados |
| Confirmación por correo | Dentro de 2 minutos tras confirmar la inscripción en Nike, con servicio de correo disponible |
| Primera atención de incidentes críticos | 5 minutos; no equivale a restablecimiento |

El RTO de ventas de extremo a extremo no puede darse por cumplido en diez minutos si Nike o EasyPay siguen caídos por sus ventanas declaradas. La reunión deja esa tensión para la propuesta y distingue el servicio informativo del transaccional; no inventa una garantía global. El RPO cero de transacciones es un requisito de negocio que debe contrastarse con durabilidad, conciliación y recuperación de Nike y EasyPay.

## Comportamiento ante indisponibilidad

| Caso | Resultado esperado por el cliente | Restricción para el diseño posterior |
| --- | --- | --- |
| Nike on-premise offline antes de comprar | Mantener información; avisar y suspender venta | No cobrar sin verificar y reservar cupo; no guardar pedidos personales en AWS como alternativa |
| EasyPay offline con Nike disponible | Mantener información; suspender pago y explicar el estado | Sin SINPE ni otra pasarela de respaldo fuera del convenio |
| Nike y EasyPay offline | Información pública disponible; ventas suspendidas | Separar dependencia informativa y transaccional |
| Pago aprobado seguido de pérdida de conexión con Nike | Verificar y conciliar con la orden Nike que ya existía; impedir un segundo cobro | Recuperar notificación desde EasyPay; no usar colas AWS con los datos restringidos |
| Correo de Nike offline o con error | Conservar envío pendiente en Nike; permitir reenvío sin nueva compra | No confundir inscripción confirmada con correo entregado; medir la demora cuando vuelva el servicio |
| Hacienda sin respuesta | Nike conserva estado pendiente y aplica su procedimiento fiscal del caso | No declarar aceptación fiscal inexistente; no bloquear el tiquete de una inscripción ya confirmada |
| Base financiera de Gatorade offline | Nike conserva entrega pendiente y reintenta | No convertir AWS en almacén de las facturas personales |

## Condiciones de pago del escenario

EasyPay admite en este guion tarjetas de débito y crédito Visa o MasterCard emitidas por BAC o Banco Nacional, también cuando se usan desde Apple Pay. No se admite SINPE ni transferencia manual. La compatibilidad y el filtrado real deben comprobarse con el proveedor; el guion no prueba que EasyPay ofrezca estas capacidades. Lo mismo aplica al reenvío de notificaciones, a las interfaces fiscales y a las políticas de intercambio entre empresas.

## Decisiones que debe producir Arquitectura, con FinOps

- Cómo separar datos públicos y transacciones sin filtrar datos personales a almacenamiento, observabilidad o mensajería AWS.
- Cómo proteger y dimensionar las conexiones privadas con Nike y los sistemas financieros, incluyendo sus fallas.
- Cómo mantener información pública y detener ventas con seguridad cuando no hay autoridad de cupos o pago.
- Cómo evitar cobros y facturas duplicados y conciliar pagos aprobados con desconexión.
- Cómo alcanzar o renegociar objetivos transaccionales incompatibles con los tiempos declarados de terceros.
- Cómo tramitar correos y facturas pendientes desde sistemas autorizados y medir su entrega.
- Cómo sostener esos requisitos dentro de los límites de honorarios, consumo, mantenimiento y calendario, sin elegir recursos solo por su costo unitario.

## Cobertura de las 15 preguntas de negocio

| Pregunta | Intervenciones con respuesta |
| --- | --- |
| 1 | S02 |
| 2 | S06, S34 |
| 3 | S02, S04 |
| 4 | S09, S11 |
| 5 | S13 |
| 6 | S13 |
| 7 | S44 |
| 8 | S44 |
| 9 | S30, S36, S38, S40 |
| 10 | S30, S32, S34, S36, S38, S40, S42 |
| 11 | S15, S16, S18, S26, S28, S30, S42 |
| 12 | S11, S46 |
| 13 | S46 |
| 14 | S15, S18, S22, S24, S26, S28, S32, S48 |
| 15 | S48 |

El expediente se conserva en `project/backend/fixtures/nike-lindora-stuart/`. No reemplaza el fixture anterior `nike-maraton-cr`. Sus tres documentos se generaron en `insumos temporales de agente 1/` y permanecen pendientes de revisión. No se ejecutaron pruebas de banco, facturación, correo, nube ni infraestructura on-premise.
