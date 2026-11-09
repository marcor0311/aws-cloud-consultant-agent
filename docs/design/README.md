# Sistema de documentos No Name

La dirección seleccionada es NODO, con el nombre provisional **No Name**.

`playbook.html` reúne las entregas reales: dos páginas de la ficha del proyecto,
tres del resumen de reunión y diez diapositivas. Las páginas de documentos se
renderizan desde los PDF de ReportLab; la presentación conserva su navegación,
edición local y animaciones. Funciona sin conexión. Los enlaces de descarga
apuntan a los archivos generados en `insumos/`.

Reglas: fondos claros, títulos sin punto final, sin separadores de punto medio,
sin códigos de proyecto inventados y sin cajas decorativas. Los documentos usan
Lato, encabezados discretos, márgenes amplios, líneas finas y tablas sin rellenos.
Las referencias a la transcripción se conservan para revisar la evidencia.

La documentación combina tinta azul oscuro, azul de acento y naranja puntual. La
portada usa un corredor original generado con ImageGen, con grano y disolución
fotográfica. La animación de entrada se implementa en CSS; no requiere nuevas
llamadas a IA al abrir o exportar los materiales. El corredor está asociado solo
al caso ficticio de maratón; otros proyectos no reciben automáticamente esa imagen.

Para reconstruir la vista, desde la raíz:

```sh
make insumos-mock
project/backend/.venv/bin/python scripts/build-playbook.py
```

Para comprobar los documentos y la presentación, solo en escritorio:

```sh
project/backend/.venv/bin/python scripts/verify-insumos.py \
  --directory insumos --qa /private/tmp/no-name-qa
```

Las decisiones de contenido de la reunión ficticia siguen siendo fuentes; la
identidad No Name y el diseño visual responden a la revisión posterior del usuario.
No se usan clientes, credenciales ni inferencia real del agente.

La lectura principal está dirigida a Junta Directiva y vicepresidencias. La ficha
abre con inversión, fecha, recomendación y resultados esperados; el resumen
registra acuerdos y compromisos; la presentación comienza con la síntesis ejecutiva
y el calendario antes del apoyo funcional y técnico. El soporte documental y su
validación son exclusivamente de escritorio.

Los criterios editoriales, las referencias consultadas y el flujo de producción
están documentados en la [skill de diseño del agente 1](../../project/agents/1.%20calendar%20assistant/.agents/skills/design-executive-documents/SKILL.md).
