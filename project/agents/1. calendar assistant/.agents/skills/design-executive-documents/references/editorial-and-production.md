# Criterios de referencia y producción local

## Referencias consultadas el 7 de noviembre de 2026

- [Governance Institute of Australia — Board papers](https://governanceinstitute.com.au/app/uploads/2023/11/govinst_guidance-board_papers_2021.pdf): priorizar información material para supervisión; declarar propósito y recomendación desde el inicio. Incluye un ejemplo de documento para Junta en su apéndice. Aplicación local: síntesis ejecutiva con inversión, plazo, resultado y responsabilidad antes del soporte operativo.
- [Deloitte — Effective board communications](https://www.deloitte.com/us/en/services/audit/blogs/accounting-finance/effective-board-communications.html): distinguir información de asuntos que requieren decisión. Aplicación local: «Para conocimiento y seguimiento» cuando el encargo ya está definido; no fabricar una solicitud de aprobación.
- [Australian Institute of Company Directors — Board paper](https://www.aicd.com.au/board-of-directors/meeting/board-paper.html): contexto breve, análisis, recomendación y respaldo con lenguaje claro. Aplicación local: conservar evidencia sin convertir la lectura principal en una transcripción técnica.
- [Atlassian — Project poster](https://www.atlassian.com/software/confluence/templates/project-poster): conectar la necesidad con la solución y su justificación. Es una referencia de estructura de proyecto; no usar su dinámica de descubrimiento como guion de la reunión refinada con Stuart.
- [Atlassian — Meeting notes](https://www.atlassian.com/software/confluence/templates/meeting-notes): conservar acuerdos, acciones y responsables. Aplicación local: resumen de reunión verificable y separado de la propuesta.
- [McKinsey — Technology Trends Outlook 2024](https://www.mckinsey.com/~/media/mckinsey/business%20functions/mckinsey%20digital/our%20insights/the%20top%20trends%20in%20tech%202024/mckinsey-technology-trends-outlook-2024.pdf): referencia de jerarquía editorial y lectura por niveles. No copiar su marca, texto ni densidad de informe al documento del cliente.

Estas referencias orientan decisiones de diseño; no son evidencia del proyecto de maratón. La procedencia del contenido del caso debe apuntar a su transcripción y preparación.

## Archivos y responsabilidades

Rutas desde la raíz del repositorio:

| Archivo | Función |
| --- | --- |
| `project/backend/fixtures/nike-maraton-cr/transcript.json` | Reunión ficticia editable solo dentro de la autorización recibida |
| `project/backend/fixtures/nike-maraton-cr/content.json` | Hechos, acuerdos, propuesta de consultoría y lectura ejecutiva |
| `project/backend/app/preparation/insumos.py` | Contratos y validación de evidencia; no diseño visual |
| `project/backend/app/integrations/insumos_export.py` | Maquetación ReportLab y composición HTML |
| `project/backend/app/integrations/insumos_assets/` | Fuentes, imagen del caso, CSS de escenario y plantilla HTML |
| `scripts/build-playbook.py` | Vista integrada de los archivos realmente generados |
| `scripts/verify-insumos.py` | Render y revisión automatizada de escritorio |
| `insumos/` | Salida local, manifiesto y fuentes exportadas |
| `docs/design/playbook.html` | Vista que revisa el usuario |

`facts` y `executive` permiten presentar el contexto de dirección sin extraer fechas o importes mediante expresiones regulares. `proposal` conserva el desarrollo de la consultora con estado `proposed` y referencias a las necesidades que lo motivan. Sus citas no prueban que el cliente haya aprobado la recomendación. Las referencias se validan también dentro de esas estructuras.

## Regeneración

Desde la raíz, con el entorno del backend preparado:

```sh
make insumos-mock
make test-insumos
project/backend/.venv/bin/python scripts/build-playbook.py
project/backend/.venv/bin/python scripts/verify-insumos.py --directory insumos --qa /private/tmp/no-name-qa
```

El navegador de QA puede necesitar permiso del sandbox para arrancar. No confundir ese permiso con autorización para llamadas a modelos o pruebas de nube. El flujo usa el proveedor guionado y datos ficticios; conserva `awaiting_review` y no aprueba etapas automáticamente.

Comprobar el contacto visual y abrir a tamaño real las páginas densas. Revisar también las tres pestañas de la vista integrada, sus descargas y la navegación de documentos. El objetivo actual de referencia es ficha de dos páginas, resumen de tres y diez diapositivas; no ajustar una salida a esos números sacrificando información o legibilidad.

## Fallos de composición observados

- Repetir síntesis, cifras y pendientes en cada sección produce extensión sin aumentar el valor ejecutivo.
- Una nota de fuentes puede crear una página casi vacía. Ajustar el contenido y los espaciados y volver a renderizar; no aceptar la página huérfana.
- Un estilo de encabezado con `spaceBefore` dentro de una celda puede introducir huecos desproporcionados. Usar un estilo de celda explícito.
- Compartir una clase como `metrics`, `split` o `roadmap` entre la diapositiva y su bloque interno aplica la cuadrícula al contenedor equivocado. Prefijar los tipos de diapositiva y revisar geometría y capturas.
- La edición persistida en el navegador puede ocultar una revisión nueva. Vincular la clave local al contenido preparado y verificar con un perfil de QA aislado.
- El diseño del visor puede contaminar la lectura si muestra notas de implementación. Presentar audiencia, propósito y estado editorial; dejar detalles de herramientas en la documentación técnica.
- Al volver de un PDF a la presentación integrada, comprobar que sus controles quedan dentro de la pantalla. El visor actual centra la presentación al seleccionar su pestaña; validar la interacción real, sin forzar clics ni desplazar la página desde el test para ocultar el problema.
