# Integraciones que conservamos

La suite tiene cinco recorridos habituales:

1. Registro de cliente → API de verificación → OTP → acceso a agenda, con SQL temporal.
2. Captura de transcripción → HTTP → cola automática → recuperación de una pausa antigua `draft_with_chatgpt` sin tarea activa → OAuth/Responses simulados → LangGraph → revisión humana con identidad de entrada preservada → cinco archivos corporativos → aprobación sin guion → entrega exacta al agente 2; consulta `prepare` por MCP HTTP con Bearer antes y después de generar, sin inferencia duplicada; inicio CLI/MCP sin notas y conciliación exigida al añadir notas a la misma entrada.
3. Transcripción y notas separadas → borrador con citas por fuente y discrepancia pendiente de revisión → archivos de presentación → aprobación → guion → cambio de presentación invalida el guion → aprobación del guion → exportación versionada de seis archivos → validación de hashes → agente 2 → junta simulada → rama documental → PR pendiente → merge → issue con manifiesto → handoffs en SQL. El mismo recorrido cubre junta negativa (rechazo y abstención) → cola → bloqueo si la versión no coincide → Dirección `declined`, con reintento tras reinicio sin duplicar el rechazo ni abrir repo/issue.
4. Sesión OAuth y SDK simulados → LangGraph → transporte MCP real → resultado guardado; reabrir la ejecución reutiliza el resultado.
5. Agente 1 → conexión STDIO con su servidor MCP → invocación de herramienta → backend HTTP simulado deniega registro → oferta de asesor → rechazo sin transferencia o aceptación con SIP REFER simulado → éxito o recuperación tras timeout/rechazo del proveedor. Usa el SDK real con modelo guionado, sin evaluar comprensión del lenguaje.

El recorrido de transcripción también regenera desde una revisión con contenido
comparativo antiguo: comprueba que ese texto no llegue al modelo ni al nuevo
resumen, conservando intacta la revisión histórica y la transcripción.

Solo hay otros dos recorridos, bajo demanda: el circuito completo de voz guionada
hasta el handoff y el E2E de agente 1 a agente 2 sobre PostgreSQL aislado real,
incluidos el diálogo MCP y la publicación simulada en GitHub.
Los proveedores externos son simulados. Ninguna prueba usa tokens de ChatGPT o LiveKit.

```sh
make test           # Los cinco recorridos habituales
make test-backend   # Los cuatro del backend
make test-agent     # Conexión MCP de agente 1
make test-e2e       # Circuito completo offline; requiere ambos entornos
make test-postgres  # Un recorrido; requiere WORKFLOW_TEST_POSTGRES_URL aislada
```

`make test-demo` es alias de `make test-e2e`. Los comandos reutilizan los entornos
instalados y no resuelven dependencias. PostgreSQL y E2E se ejecutan cuando el cambio
los necesita; el E2E de CI sigue siendo manual.

Se eliminaron los casos unitarios, variantes y pruebas individuales de adaptadores,
formatos, UI, archivos y estructura interna. No añadirlos de nuevo para cada cambio:
actualizar el recorrido que ya cubre la integración. Ampliar solo por una conexión
nueva o un fallo real que estos recorridos no detecten.

El recorrido de revisión del informe ya existente en
`tests/test_delivery.py::test_report_revision_approval_and_close` también comprueba
el informe independiente por expediente: workflow y reportes en PostgreSQL aislado,
fuentes congeladas, métricas de intervalos superpuestos, generación sin ingeniería,
corrección de secciones, revisión exacta, descarga MCP y bloqueo del cierre parcial.
Se conserva en el job dedicado de delivery; no añade casos unitarios ni simulaciones
cloud a `make test`. Requiere `DELIVERY_TEST_DATABASE_URL`; una omisión no acredita
la integración. El PDF del recorrido se exporta para inspección visual.

Ese recorrido también solicita enlaces firmados por MCP HTTP y descarga el PDF
y las fuentes JSON sin enviar el Bearer desde el navegador. Verifica los hashes,
rechazo de otro operador, firma alterada, archivo cambiado de URL y caducidad;
el endpoint MCP conserva su autenticación. Usa un origen HTTPS ficticio sobre
TestClient, sin publicar túneles ni contactar servicios externos.

El recorrido existente de FinOps
`tests/finops_agent/test_mcp.py::test_finops_delivers_merged_costs_to_engineering_and_measures_work`
continúa ahora hasta Ingeniería y captura de fuentes #22. Genera publicaciones de
Arquitectura/FinOps con sus servicios, recibe un fixture S3 completo, conserva los
hashes originales, devuelve aceptación y recupera una interrupción entre grafo y
SQL. Rechaza un archivo alterado antes de avanzar e invalida fuentes modificadas
después de recibirlas. Las revisiones GitHub son recibos ficticios; el recorrido
no acredita aprobación real ni aceptación dentro de ChatGPT.

El recorrido existente `tests/test_delivery.py::test_handoff_report_download_and_idempotency`
también cubre la recepción de ingeniería #21: decisiones de Arquitectura/FinOps
aplicadas con LangGraph y persistidas en PostgreSQL, rechazo de archivos alterados,
aceptación de handoff sin aprobación implícita, importación de resultados parciales
con fallo de limpieza, intervalos paralelos y retrabajo explícito, reintento sin
duplicación, recuperación desde otro runtime, consulta MCP y lectura de las mismas
mediciones por #22. Las entradas y corridas son ficticias y no ejecutan Terraform,
emuladores ni servicios externos. Se amplía el recorrido existente, sin añadir
casos unitarios o matrices de comprobaciones.

Ese mismo recorrido continúa desde la recepción #21 hasta el informe #22 por
`intake_id`: captura sin corridas, informe posterior con corrida fallida y medición
de retrabajo, conservación del informe previo, rechazo de recepción de otro caso
y de respaldo alterado, descarga de fuentes/archivos por el MCP del informe,
aprobación parcial y rechazo del cierre. Exporta ambos PDF para inspección visual.

El mismo recorrido también registra una entrega definitiva con dos corridas
exitosas declaradas, comprueba el catálogo y rechaza la entrega antes de la
aprobación exacta de etapa 5. Continúa por MCP con informe definitivo, aprobación,
presentación y cierre del grafo principal. Provoca una interrupción después del
checkpoint y antes de guardar la decisión; otro runtime recupera el cierre sin
duplicarlo. Usa un expediente adicional aislado con metadatos de producción para
ejercitar esa condición, pero todos sus insumos, revisiones y corridas son datos
de prueba: no acredita entregas reales ni ejecuta Terraform/GitHub/AWS. Exporta
`informe-definitivo-prueba.pdf` para inspección visual.

Ese recorrido también usa el adaptador GitHub real con transporte HTTP simulado:
rechaza bytes distintos del commit y una revisión antigua; publica un único PR,
solicita revisión y recupera una respuesta perdida del merge sin repetirlo.
Comprueba baselines, protección, CI, archivos del PR, recibo externo y un único
aviso mediante el worker y Slack simulado. Continúa con una sesión abierta,
conciliación con hash obsoleto rechazada, corrección explícita a espera sin sumar
esfuerzo y generación de otra instantánea, conservando las fuentes anteriores.

El recorrido de revisión existente también usa JSON-RPC sobre Streamable HTTP
con Bearer: inicialización, herramientas, generación, ajustes, aprobación, bloqueo
del cierre parcial y descarga PDF/JSON. Rechaza peticiones sin token en ambas
variantes de la ruta. Esto valida el protocolo, no la cuenta ni la interfaz real
de ChatGPT. Ninguna prueba envía mensajes, publica PRs o ejecuta servicios cloud.
