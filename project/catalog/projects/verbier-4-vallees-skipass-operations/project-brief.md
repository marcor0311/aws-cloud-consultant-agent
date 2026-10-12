# Ficha de proyecto | Plataforma SkiPass e integración operativa de cinco estaciones de Verbier 4 Vallées

**Tipo:** proyecto histórico (`consulting_project_reference`).  
**Producción:** en operación (`in_production`).  
**Versión documental:** 1.1.0.

## Organización y operación

- **Organización:** Verbier 4 Vallées y operadores participantes; patrocinador y gobierno multioperador no registrados en este expediente.
- **Ubicación:** Cantón de Valais, Suiza.
- **Actividad/contexto:** Verbier 4 Vallées es un área conectada con seis estaciones. El alcance documentado cubre cinco estaciones: Verbier, La Tzoumaz, Nendaz, Veysonnaz y Thyon; Bruson no figura en el alcance descrito en este expediente. El gobierno e interfaces reales entre operadores no están detallados en la documentación as-built disponible.
- **Equipo previsto:** 45 personas estimadas en atención, operación central y tecnología; unas 320 personas estacionales/de estación distribuidas en los sitios. Cifra de contexto del expediente; validar con registros históricos de los operadores antes de tratarla como medición real.
- **Usuarios y carga:** Capacidad de planeación: 24.000 visitantes/día entre cinco estaciones; hasta 18.000 reservas digitales/día y 3.000 sesiones simultáneas en apertura/venta. Estas cifras no están respaldadas aquí por registros históricos de los operadores.

## Objetivo

Unificar disponibilidad y reservas SkiPass entre cinco estaciones, conectar la experiencia digital con ticketing/torniquetes locales y mantener operaciones seguras durante cortes de conectividad.

## Requisitos funcionales

- Consultar condiciones, estado de apertura y capacidad por estación/fecha.
- Reservar, emitir, cancelar y reconciliar pases sin sobreventa ni duplicados.
- Sincronizar ticketing, torniquetes y sistemas locales; permitir operación local degradada y reconciliación tras una desconexión.
- Ingerir información meteorológica con ubicación, hora y frescura; personal autorizado decide cierres y alertas.
- Gestionar pagos, devoluciones, notificaciones y reglas por estación según políticas acordadas.

## Alcance de solución

| Componente | Responsabilidad y estado | Motivo | Baseline/perfil documentado |
|---|---|---|---|
| Sitio/app + Amazon CloudFront | Canales públicos de reserva; implementación web/móvil no descrita en este snapshot. | Atender consultas y compras desde las estaciones y fuera de ellas. | CloudFront no está incluido en los baselines del catálogo. |
| Amazon API Gateway HTTP API + AWS Lambda | API de reservas, disponibilidad y sincronización; implementación Lambda, identidad y red no descritas aquí. | Proveer entrada controlada a la lógica central y a las integraciones de estación. | API `throttling_500rps_burst_1000`; Lambda no está en el baseline. |
| Amazon DynamoDB | Referencia para disponibilidad y reservas; transacciones e índices reales no registrados. | Mantener el estado de reserva con escrituras condicionales/idempotencia ante concurrencia y reconexión. | `aws-dynamodb-single-table` / `on_demand`; modelo as-built no registrado. |
| Amazon S3 | Referencia para contenido y objetos privados; política histórica de retención no registrada. | Guardar contenido/documentos sin exposición pública y con retención configurable. | `aws-private-object-storage` / `private_versioned_365d`. |
| Ticketing, torniquetes, remontes y estaciones meteorológicas | Sistemas locales/de terceros; topología e interfaces desplegadas no descritas en este snapshot. | Sincronizar reservas y estado operativo con la infraestructura física de estaciones. | Integraciones fuera de los baselines y Terraform de este catálogo. |
| Proveedor meteorológico | Fuente externa; proveedor y contrato histórico no registrados. | Aportar observaciones/pronóstico para consulta humana durante la operación. | Integración externa, fuera de los baselines del catálogo. |

### Flujo principal

1. Visitante → portal → disponibilidad por estación/fecha → reserva y pase.
2. API de reserva → transacción/idempotencia → confirmación y evento de sincronización.
3. Servicios cloud ↔ conectividad privada redundante ↔ agentes y ticketing/torniquetes locales.
4. Agente local mantiene cola durable durante desconexión y reconcilia con control de duplicados.
5. Fuente meteorológica → adaptador con hora/frescura → panel/alertas; decisión de cierre humana.

## Alcance de esta referencia documental

La composición Terraform 1.1.0 del catálogo modela únicamente API Gateway HTTP API, un bucket S3 privado y una tabla DynamoDB. No es un export del entorno histórico completo; frontend/CDN, funciones Lambda, identidad, integraciones y red no están representados aquí. Consultar inventario as-built antes de usarla para reproducir o modificar producción.

## Requisitos de calidad y datos por recuperar

El expediente as-built disponible no registra gobierno entre operadores, límites de capacidad por estación, topología de red, reconciliación offline, identidad, pagos/impuestos, privacidad, RTO/RPO ni protocolos operativos de montaña.

Recuperar del expediente operativo las cargas medidas, presupuesto, región, controles de privacidad/seguridad, continuidad y responsables. Las cifras de equipo y tráfico aquí incluidas son contexto de planeación y no mediciones confirmadas.

## Fuentes de contexto

- [Verbier 4 Vallées: área y estaciones](https://verbier4vallees.ch/en/about-us) — la zona comprende seis estaciones; la referencia documental cubre cinco estaciones y no incluye Bruson; el as-built disponible no registra el motivo de ese límite.
- [Téléverbier: actividades y operación](https://verbier4vallees.ch/en/about-us) — información oficial sobre el operador y sus sectores. El patrocinador y el gobierno multioperador no están registrados en este expediente.
