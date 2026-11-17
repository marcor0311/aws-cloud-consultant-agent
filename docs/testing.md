# Integraciones que conservamos

La suite tiene cinco recorridos habituales:

1. Registro de cliente → API de verificación → OTP → acceso a agenda, con SQL temporal.
2. Captura de transcripción → HTTP → cola automática → recuperación de una pausa antigua `draft_with_chatgpt` sin tarea activa → OAuth/Responses simulados → LangGraph → revisión humana con identidad de entrada preservada → cinco archivos corporativos → aprobación sin guion → entrega exacta al agente 2; consulta `prepare` por MCP HTTP con Bearer antes y después de generar, sin inferencia duplicada; inicio CLI/MCP sin notas y conciliación exigida al añadir notas a la misma entrada.
3. Transcripción y notas separadas → borrador con citas por fuente y discrepancia pendiente de revisión → archivos de presentación → aprobación → guion → cambio de presentación invalida el guion → aprobación del guion → exportación versionada y persistida en SQL de seis archivos → decisión guiada por MCP → confirmación final → rama documental → PR → issue asignado con manifiesto → handoffs en SQL.
4. Sesión OAuth y SDK simulados → LangGraph → transporte MCP real → resultado guardado; reabrir la ejecución reutiliza el resultado.
5. Agente 1 → conexión STDIO con su servidor MCP → invocación de una herramienta.

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
