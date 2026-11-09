# Estructura privada de ejemplo

Esta carpeta es documentación versionable: no se usa como almacén activo.
Los archivos `.example` contienen valores vacíos y nunca deben rellenarse aquí.

La ubicación local predeterminada es:

```text
~/.config/aws-cloud-consultant-agent/dev/
├── secrets.env
├── google/
│   ├── oauth-client.json
│   ├── calendar-token.json
│   ├── gmail-token.json
│   └── workflow-token.json
├── chatgpt/
│   ├── meeting-assistant/
│   │   ├── registration.json
│   │   └── session.json
│   └── plan-demo/
│       └── registration.json
└── backups/
```

Copiar `secrets.env.example` al directorio privado como `secrets.env` y completar
solo las variables utilizadas. El cliente OAuth real se descarga del proveedor;
el JSON de ejemplo ilustra su estructura, no es una credencial funcional.
Los tokens y registros se generan mediante los comandos de autorización existentes.
No copiar tokens de ejemplo ni compartir sesiones entre cuentas.

`project/.env` se copia de `project/.env.example` y contiene configuración no
sensible. `CLOUD_CONSULTANT_SECRETS_DIR` selecciona el directorio privado mediante
una ruta absoluta; admite `~`. Las rutas de archivos OAuth relativas se resuelven
respecto de ese directorio, desde cualquier carpeta de ejecución.

Precedencia: variables del proceso, después `secrets.env`, después `project/.env`.
Los valores se leen literalmente, sin interpolar `$`. Backend y agente tienen
cargadores independientes; el agente de calendario solo incorpora las variables
que necesita. El frontend no carga credenciales.

## Migrar una instalación existente

Desde la raíz, revisar primero el plan (solo muestra rutas y cantidades):

```sh
project/backend/.venv/bin/python scripts/migrate-local-secrets.py
project/backend/.venv/bin/python scripts/migrate-local-secrets.py --apply
```

La migración conserva valores y bytes, respalda los archivos originales fuera del
repositorio, verifica hashes y los dos cargadores, y retira únicamente los archivos
privados migrados. Rechaza destinos con contenido distinto y enlaces simbólicos.
No modifica clientes, citas, bases de datos ni permisos remotos. No autoriza cuentas,
renueva tokens ni ejecuta inferencia. Detener los componentes antes de migrar y
reiniciarlos después para que usen las nuevas rutas.

Permisos locales: directorios `700`, archivos `600`. Los respaldos son privados y
contienen credenciales; no se suben como artefactos de CI ni se comparten.

## Contrato para producción

Este directorio es una solución de desarrollo local. En AWS, guardar secretos por
ambiente e integración en Secrets Manager, con roles IAM de mínimo privilegio y
rotación según el proveedor. La configuración pública solo referencia los secretos.
Las sesiones OAuth requieren persistencia cifrada por cuenta y renovación coordinada.
No desplegar las sesiones personales de desarrollo como identidad de un servicio.

GitHub Actions ejecuta pruebas con proveedores offline. Para un futuro despliegue,
usar OIDC con AWS en lugar de claves permanentes en el repositorio. Esta estructura
no crea recursos cloud ni incorpora infraestructura de despliegue.

Referencias: [Secrets Manager](https://docs.aws.amazon.com/secretsmanager/latest/userguide/best-practices.html)
y [GitHub OIDC con AWS](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws).
