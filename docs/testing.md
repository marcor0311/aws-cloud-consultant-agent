# Integraciones que conservamos

La suite tiene cinco recorridos habituales:

1. Registro de cliente → API de verificación → OTP → acceso a agenda, con SQL temporal.
2. Captura de transcripción → HTTP → cola → LangGraph → estado persistido tras reinicio.
3. Preparación aprobada → agente 2 → junta simulada → rama documental → PR pendiente → merge → issue → handoffs en SQL.
4. Sesión OAuth y SDK simulados → LangGraph → transporte MCP real → resultado guardado; reabrir la ejecución reutiliza el resultado.
5. Agente 1 → conexión STDIO con su servidor MCP → invocación de una herramienta.

Solo hay otros dos recorridos, bajo demanda: el circuito completo de voz guionada
hasta el handoff y la preparación/apertura con PostgreSQL aislado real.
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
