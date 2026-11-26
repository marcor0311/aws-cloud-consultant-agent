# Aceptación del cliente MCP del Engagement Manager

Cliente recomendado: ChatGPT web. La compatibilidad del protocolo HTTP se prueba
automáticamente; esta aceptación confirma el comportamiento en la cuenta y cliente
reales. Su resultado está **pendiente** hasta realizar el recorrido.

## Preparación

1. Configurar PostgreSQL, `DELIVERY_ENGAGEMENT_MANAGER` con el responsable exacto,
   `WORKFLOW_DATABASE_URL`, `DELIVERY_DATABASE_URL` y el Bearer privado.
   Conservar `WORKFLOW_CHECKPOINT_URL` si el grafo principal usa un checkpoint separado.
   Si el cliente no descarga recursos MCP, configurar además
   `DELIVERY_DOWNLOAD_BASE_URL=https://<origen-HTTPS-del-MCP>` con el origen del
   túnel privado existente, sin ruta. El servidor no crea ni publica un túnel.
2. Iniciar `python -m app.delivery.mcp --transport streamable-http --port 8770`
   desde `project/backend`. Conectar el MCP privado a la cuenta según la
   [guía oficial de ChatGPT](https://help.openai.com/en/articles/12584461-developer-mode-and-full-mcp-connectors-in-chatgpt-beta).
3. Usar primero un expediente de prueba o un informe parcial autorizado. Conservar
   los identificadores y hashes del recorrido, sin exportar credenciales.

## Recorrido de aceptación

| Paso | Acción desde el chat | Evidencia esperada |
| --- | --- | --- |
| 1 | Listar expedientes y seleccionar uno propio | `case_id` correcto; ningún expediente de otro responsable |
| 2 | Consultar conciliación | Faltantes y `state_sha256`, sin inferir tiempos |
| 3 | Generar informe con un `report_id` nuevo | Fuentes congeladas, versión, hash y URI del PDF |
| 4 | Solicitar un ajuste y guardar la revisión | Versión nueva; PDF anterior conservado |
| 5 | Aprobar expresamente la revisión/hash vigente | PDF aprobado e historial con identidad local |
| 6 | Descargar PDF y fuentes desde el cliente; puede usarse `preparar_descarga_informe` | Archivos legibles y SHA-256 iguales al resultado |
| 7 | Intentar presentar el informe parcial | Conflicto; el expediente permanece abierto |
| 8 | Repetir consulta y recuperar el informe | Misma revisión y mismos archivos |

Verificar los recursos `delivery://pdf/...` y `delivery://sources/...`. Para clientes
sin descarga de recursos, `preparar_descarga_informe(entrega_id)` devuelve un enlace
HTTPS al PDF vigente y `sources_download` con un enlace a sus fuentes JSON, si
existen. Cada archivo tiene identificador, tamaño, SHA-256 y caducidad de cinco minutos.
Abrirlo y comprobar el hash del archivo descargado. El enlace permite descargar
únicamente ese archivo y funciona sin enviar el Bearer desde el navegador; cualquiera
que lo reciba puede usarlo durante su vigencia. Mantenerlo en la conversación
autorizada y generar otro si vence. No adjuntar el Bearer a enlaces ni evidencias.
Los respaldos individuales de ingeniería continúan usando recursos MCP privados;
el JSON conserva sus referencias. Registrar cualquier limitación del cliente para
acceder a esos respaldos. Los enlaces no acreditan por sí solos toda la aceptación.

La firma vincula operador, informe, archivo, hash y caducidad. El servidor vuelve
a verificar propiedad e integridad al descargar; los enlaces vencidos o alterados
responden 404. El comando HTTP desactiva el registro de acceso para no guardar
las firmas de descarga. Mantener también los logs del túnel/proxy sin URLs firmadas.
Sin `DELIVERY_DOWNLOAD_BASE_URL`, el servidor conserva sus recursos MCP y la
herramienta de enlace informa que la descarga HTTPS no está configurada.

El recorrido definitivo agrega una entrega #21 real aprobada e integrada,
conciliación respaldada, aprobación de un informe nuevo y `record_presentation`
con fecha, audiencia y acta reales. Confirmar `closed` en el informe y `completed`
en el proceso. El cierre de prueba no sustituye la presentación real a dirección.

## Registro del resultado

Guardar cliente/versión o fecha, cuenta/rol sin secretos, `case_id`, `report_id`,
versión/hash, resultado de cada paso y referencias a las evidencias. Registrar
cualquier limitación de descarga, permisos o conexión. No marcar esta aceptación
como aprobada basándose únicamente en la suite automática o en un cliente MCP
distinto del usado por el Engagement Manager.
