# Proyecto multiagente para generar Terraform en AWS

Este repositorio contiene una API en FastAPI que recibe solicitudes estructuradas, genera infraestructura como código (IaC) y empaqueta el proyecto resultante en un archivo ZIP.

## Flujo de la API

1. Recibe una solicitud mediante `POST /api/agent`.
2. Valida y normaliza los datos.
3. Ejecuta el flujo de agentes de planificación, recuperación, generación y construcción.
4. Genera los archivos Terraform y copia los módulos locales requeridos.
5. Guarda un ZIP descargable en `project/generated/`.

## Solicitud de ejemplo

El endpoint acepta este formato:

```json
{
  "project_name": "demo-s3-module",
  "cloud_provider": "aws",
  "region": "us-east-1",
  "environment": "dev",
  "resources": [
    {
      "type": "s3",
      "name": "tendencias-bucket"
    }
  ]
}
```

`environment` puede ser `dev`, `qa`, `staging` o `prod`. `cloud_provider` actualmente debe ser `aws` y se requiere al menos un recurso.

## Recursos y módulos

El backend incluye un módulo local para buckets S3 en `project/app/modules/aws/s3-bucket`. Cuando la solicitud incluye un recurso `s3`, el proyecto Terraform generado incorpora ese módulo.

## API

- `GET /`: verifica que el backend está disponible.
- `POST /api/agent`: procesa la solicitud y devuelve el resultado del flujo de generación.
- `GET /api/agent/download/{project_name}`: descarga el ZIP generado para el proyecto solicitado.
- `GET /docs`: abre la documentación interactiva de FastAPI.

## Estructura principal

```text
project/
  app/
    agents/
    kernel/
    models/
    modules/
      aws/
        s3-bucket/
    orchestrator/
    routes/
    services/
    main.py
    requirements.txt
  generated/
  .env.example
```

## Variables de entorno

Copia `project/.env.example` a `project/.env` y configura las credenciales de Azure OpenAI:

```env
AZURE_OPENAI_ENDPOINT="https://your-resource-name.cognitiveservices.azure.com/"
AZURE_OPENAI_API_KEY="YOUR_AZURE_OPENAI_API_KEY"
AZURE_OPENAI_DEPLOYMENT="gpt-5.4-mini"
AZURE_OPENAI_API_VERSION="2024-12-01-preview"
```

No agregues el archivo `.env` real al control de versiones.

## Ejecutar el backend

Desde la carpeta `project`:

```bash
python -m venv venv
source venv/bin/activate
pip install -r app/requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

El backend estará disponible en `http://127.0.0.1:8000` y su documentación interactiva en `http://127.0.0.1:8000/docs`.

## Validar Terraform generado

Desde la carpeta de un proyecto generado:

```bash
cd project/generated/demo-s3-module
terraform init
terraform fmt -check
terraform validate
```

Para inspeccionar el plan:

```bash
terraform plan
```

La validación de Terraform se ejecuta manualmente sobre cada proyecto generado.
