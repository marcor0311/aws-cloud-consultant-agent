---
name: prepare
description: Consulta el progreso de preparación de un proyecto de AWS Cloud Consultant y ayuda a revisar y ajustar sus documentos ya generados mediante su MCP conectado.
---

Usa la herramienta `prepare` del MCP de AWS Cloud Consultant. Si todavía no hay
proyecto seleccionado en la conversación, invócala sin `proyecto_id` y ofrece los
proyectos devueltos. Usa el ID exacto de la selección en las consultas siguientes.
Si el servidor no está conectado o no responde, informa esa limitación; no inventes
un estado del proyecto ni generes una preparación sustitutiva en el chat.

Interpreta el estado real:

- `queued`: los documentos están en cola para el worker; aún no están listos.
- `processing`: el worker está generando los documentos. El usuario puede volver a consultar.
- `blocked`: muestra el motivo de la tarea y el paso necesario para recuperarla.
- `paused`: la preparación antigua espera un borrador interactivo; el worker debe
  retomarla con el proveedor configurado. No afirmes que está generando documentos.
- `idle`: no hay generación activa. No afirmes que continúa procesándose.
- `awaiting_review`: muestra estado, identificador, revisión, carpeta y la lista/rutas de los cinco archivos: resumen de reunión PDF, ficha de proyecto PDF, presentación HTML/PDF y transcripción íntegra PDF.
- `ready_for_stage_2`: el paquete ya fue aprobado; muestra su revisión y entrega.

Consultar `/prepare` solo lee: no inicia ni regenera documentos y no activa
inferencia. Evita consultas repetidas en un bucle; vuelve a consultar cuando el
usuario lo pida. La generación ocurre en el worker desde la transcripción.

Cuando el usuario empiece a revisar, usa `comenzar_revision` con la revisión actual.
Lee secciones con `consultar_insumo`. Guarda los cambios solicitados mediante
`actualizar_insumos`, indicando la revisión exacta y explicando qué se cambió.
Los comentarios sin edición se guardan con `comentar_preparacion`.

La transcripción es la fuente completa del procesador. No añadas descubrimiento,
preguntas, comparaciones ni guion. El resumen y la presentación organizan
lo dicho en la reunión, sin inventar hechos ni acuerdos. La aprobación expresa
acepta los cinco archivos como conjunto; no genera otro entregable.
