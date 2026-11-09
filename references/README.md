# Referencias de proyectos

Catálogo **ficticio académico**, recuperado del historial de este repositorio
en el commit `cdd46e5d9a832f5f0d05dea368b55ef305dfc90d` (2026-10-12).
Original: `project/catalog/`. Se conservan los IDs de empresas y proyectos.
Los nombres de organizaciones se usan como contexto ficticio; las afirmaciones
antiguas sobre producción, usuarios o resultados no constituyen evidencia real.

- `companies/`: perfiles de Inter Miami CF, Mercedes-Benz Canada y Verbier 4 Vallées.
- `projects/`: merchandising, showroom de vehículos y operación de skipass.
- `templates/`: fichas para añadir referencias consistentes.
- `provenance.json`: commit, ruta original y huellas SHA-256 antes y después de
  añadir los avisos de ficción. Permite auditar cada archivo recuperado.

Cada proyecto conserva README, `project.yaml`, brief, changelog, diagramas,
arquitecturas y auditorías de las versiones 1.0.0 y 1.1.0. Los archivos Terraform
ejecutables quedan en el commit original; no se añaden entornos ni despliegues.
Las rutas a Terraform en los documentos recuperados se refieren a ese original.

El README es un índice. El detalle vive en documentos por tema: necesidad,
requisitos, arquitectura, decisiones, costos, operación y lecciones. La búsqueda
local consulta `project-brief.md`, devuelve coincidencias léxicas, evidencia,
ruta y huella; no implica equivalencia arquitectónica ni resultados comprobados.

Para PostgreSQL: importar metadatos y documentos con ID estable, commit, versión,
huella y `is_fictitious`; indexar primero con búsqueda de texto. Añadir embeddings
solo si la recuperación semántica lo justifica. Git conserva las fuentes
versionadas; la base conserva el índice y los estados operativos. No almacenar
transcripciones reales ni datos de clientes en esta carpeta.
