# Nike Lindora 5K, 10K y 15K — Reunión con Stuart

Caso de demostración con participantes, cifras y condiciones simuladas. Las restricciones legales, bancarias y de integración pertenecen al escenario; no describen normativa general ni capacidades verificadas de EasyPay, Hacienda, Nike o Gatorade.

7 de noviembre de 2026 — Hora de Costa Rica

Duración estimada: 24:49 a 120 palabras por minuto, con tres minutos para pausas. Las marcas se calculan sobre el texto; no provienen de audio.

**Participantes:** Stuart, Engagement Manager; Valeria Rojas, líder de Marketing del cliente; Diego Solano, coordinador del proyecto del cliente.

**00:00 — Stuart**

Gracias por estar. Tenemos media hora y ya revisé el material previo. Quiero confirmar el encargo y las condiciones que pueden cambiar el costo o la continuidad del servicio. Valeria, empecemos por lo que necesita el público.

**00:23 — Valeria Rojas**

Es la carrera Nike del 13 de diciembre, con salida y meta en Terrazas Lindora: 5K, 10K y 15K. Gatorade es el patrocinador. Queremos un sitio oficial para informarse, comprar la inscripción y recibir su tiquete por correo. Nos dirigimos principalmente a corredores en Costa Rica, aunque también vienen de otros países de Centroamérica. La gente entra desde el teléfono. Hay que mostrar rutas, horarios y precios, no solo poner un botón de comprar. El otro día me preguntaron por WhatsApp dónde podían parquear y después por la camiseta, y ahí se nos fue...

**01:14 — Stuart**

Eso nos ayuda a entender el uso. Para cuidar el tiempo, tomaremos los detalles logísticos del material de Nike. ¿Qué información debe quedar visible junto a la venta?

**01:32 — Valeria Rojas**

Las tres rutas descargables, cada una con sus retornos y puntos de hidratación; las salidas son a las cinco y media para 15K, cinco cuarenta y cinco para 10K y seis para 5K. Los mapas finales salen todos de Terrazas y vuelven ahí. También reglamento, precios, qué incluye el paquete, preguntas frecuentes y presencia de Nike y Gatorade. Nosotros organizamos la entrega de paquetes, la señalización y la carrera. Ustedes publican la información aprobada; no les estamos encargando coordinar la logística del evento.

**02:18 — Stuart**

¿Cuántas inscripciones habrá, a qué precio y cómo sabrán que el proyecto dio resultado?

**02:29 — Diego Solano**

Tres mil cupos: mil quinientos de 5K, mil de 10K y quinientos de 15K. Precios finales de 18.000, 22.000 y 26.000 colones, respectivamente. Nike asume las comisiones de cobro; no se agregan al final. Incluyen camiseta, chip, número, medalla e hidratación. Hay doscientas cortesías dentro de esos cupos: cien de 5K, setenta de 10K y treinta de 15K. Nuestra meta es completar los tres mil confirmados y poder cuadrar inscritos con dinero recibido. Una visita o un formulario incompleto no cuentan como una venta.

**03:15 — Valeria Rojas**

Y la confirmación por correo es importantísima. Si alguien paga y no le llega, nos escribe a nosotros y cree que perdió el dinero. Queremos que el correo traiga el tiquete de cada corredor. Una compra puede incluir hasta cinco personas. Lo de las cortesías también tiene que verse en los reportes, porque Gatorade...

**03:46 — Stuart**

Retomo ese punto cuando hablemos del correo y los datos. Para precisar esta primera etapa: el resultado final del proyecto es el producto funcionando en AWS. Hoy necesitamos cerrar las condiciones de la plataforma de nube y sus conexiones; la programación de las funciones tiene su fase posterior. ¿Qué presupuesto tienen para el proyecto completo?

**04:18 — Valeria Rojas**

El techo aprobado para el proyecto digital es de 180.000 dólares, impuestos incluidos. Eso cubre la plataforma para esta edición y las ampliaciones que siguen; no es el presupuesto de organizar la carrera. Queremos llegar al sitio publicado y funcionando. Cómo se reparten ustedes el trabajo no lo conozco; yo necesito ver qué vamos recibiendo por ese monto.

**04:51 — Stuart**

Claro. Entonces, dentro de ese total, ¿cuánto pueden destinar ahora a desarrollar y poner en marcha la infraestructura de nube, cuánto a su consumo y cuánto al mantenimiento durante el mes del evento?

**05:12 — Diego Solano**

Para preparar y dejar operativa la nube reservamos 45.000 dólares de honorarios. Para servicios de nube, hasta 6.000 durante el período del 18 de noviembre al 20 de diciembre; para mantenimiento y atención de esa plataforma, 4.000 más. Son tres partidas distintas. Tenemos 105.000 para las fases de programación y 20.000 de contingencia; con esas cinco partidas completamos los 180.000. No queremos consumir la contingencia sin autorizarlo. La infraestructura debe quedar en AWS a nombre de Nike y conectada a nuestros sistemas, no solo dibujada.

**05:59 — Stuart**

¿Cómo pueden pagar esos 45.000 y qué fechas esperan para los avances de esta etapa?

**06:11 — Diego Solano**

Cuarenta por ciento al iniciar con contrato, treinta al aceptar el diseño y los costos y treinta con la infraestructura operativa aceptada en AWS: 18.000, 13.500 y 13.500 dólares. La operación se paga aparte contra el consumo y el mantenimiento contratado, dentro de sus límites. Queremos iniciar el 9 de noviembre, ver el primer avance el 12 y recibir la plataforma el 16. El producto completo se revisa el 17, se publica el 18 y abre venta el 20 a las seis de la mañana. La carrera es el 13 de diciembre. La fecha del anuncio no se mueve. Ustedes deben confirmarnos la viabilidad antes de comprometernos.

**07:09 — Stuart**

Vamos a las conexiones, porque condicionan ese calendario. ¿Dónde deben quedar los datos de las personas y las compras? ¿Qué puede guardarse en la base de datos en nube?

**07:28 — Diego Solano**

En nube pueden guardar textos, mapas, distancias, precios, patrocinio, preguntas frecuentes y cifras agregadas de cupos. Los corredores, compradores, órdenes y pagos van al sistema que Nike tiene en sus propias instalaciones. Legal exige que esos datos no queden almacenados en AWS, aunque el sitio tenga su propia base de datos. Necesitamos que la página los envíe directamente a Nike y consulte lo que corresponda desde ahí.

**08:06 — Valeria Rojas**

Eso lo tenemos firmado. No puede terminar una lista de nombres en una copia del sitio porque después es más cómodo bajarla. Nike debe poder buscar una inscripción y reenviar su correo. A Marketing nos bastan los totales para seguir las ventas; los datos de emergencia los maneja la organización.

**08:35 — Stuart**

¿La restricción incluye copias, registros de actividad y mensajes guardados? ¿Y dónde queda la información necesaria para enviar el correo?

**08:49 — Diego Solano**

Sí, tampoco en respaldos ni registros ni mensajes pendientes en la nube. Nombre, documento, correo, teléfono, fecha de nacimiento, talla, consentimiento y contacto de emergencia quedan en Nike, junto con la orden y sus estados. Nuestro servicio de correo toma de ahí el tiquete y lo envía; los envíos pendientes también quedan en Nike. La tarjeta la maneja EasyPay, no queremos guardar sus números. El contenido público y los totales en nube no deben permitir identificar a una persona. Las políticas y las autorizaciones están en la documentación que ya les compartimos.

**09:39 — Stuart**

¿Quién lleva el control real de cupos? Si la nube muestra una cifra desactualizada, ¿podría vender de más?

**09:52 — Diego Solano**

El control está en Nike. La cifra pública es informativa. Antes de aceptar una venta hay que verificar y reservar ahí el cupo de cada distancia. Se reserva diez minutos mientras se paga; una cortesía usa un código autorizado y también descuenta cupo. Nunca queremos pasar de tres mil. Si no se puede comprobar el cupo, no se debe cobrar usando el último número que aparecía en la página.

**10:31 — Stuart**

Hablemos de EasyPay. ¿Qué bancos y medios de pago permite el convenio que debemos respetar?

**10:43 — Valeria Rojas**

Tenemos convenio con EasyPay para BAC y Banco Nacional. Débito, crédito y Apple Pay, con Visa o MasterCard. No queremos abrir SINPE ni transferencias manuales para esta edición; la revisión de comprobantes nos consumió demasiado. El precio publicado tiene que ser lo que pague la persona.

**11:10 — Stuart**

Para que no haya confusión: ¿aceptan solo tarjetas emitidas por esos dos bancos, también dentro de Apple Pay, o cualquier tarjeta que la pasarela pueda procesar?

**11:27 — Diego Solano**

Solo las emitidas por BAC o Banco Nacional. Apple Pay no elimina esa condición; la tarjeta asociada también debe cumplirla. Visa y MasterCard son las marcas admitidas. Si el medio no cumple, se informa antes de cobrar. El contacto de EasyPay entregará las condiciones y las pruebas del convenio; no les estamos pidiendo integrar otros bancos.

**11:59 — Stuart**

¿Qué debe ocurrir con la factura, además del tiquete y la confirmación del pago?

**12:10 — Diego Solano**

La facturación debe comunicarse con Hacienda y enviar el comprobante y su respuesta a las bases financieras de Nike y de Gatorade. La factura también se envía al comprador por correo. Nada de esa información se almacena en la base de datos del sitio en AWS. Nike tiene el sistema que controla la emisión y guarda los estados. Si Hacienda no responde, se sigue el procedimiento de contingencia aprobado por nuestro equipo fiscal; no se marca como aceptada una factura que todavía no tiene esa respuesta.

**12:57 — Stuart**

La factura puede identificar al comprador. ¿Esa copia a Gatorade está expresamente autorizada, aunque la base de corredores deba permanecer en Nike?

**13:12 — Diego Solano**

Sí, la copia fiscal completa es una excepción autorizada para Hacienda y los sistemas financieros de ambas empresas. Las bases financieras son de sus instalaciones, no de la nube del sitio. Gatorade no recibe la base de corredores ni sus contactos de emergencia. Si su sistema financiero está fuera de servicio, Nike conserva el envío pendiente y reintenta. El patrocinio por sí solo no les da acceso a todos los datos personales.

**13:52 — Stuart**

Ahora un caso que puede afectar las ventas: si la base de Nike está fuera de servicio, ¿prefieren pausar las compras o permiten guardar temporalmente esos datos en nube para completarlas después?

**14:12 — Valeria Rojas**

No, guardarlos en nube no está permitido ni temporalmente. En ese caso seguimos mostrando la información de la carrera y avisamos que no se puede completar la compra. Me preocupa perder ventas, claro, pero no podemos saltarnos esa restricción. La persona debe poder volver a intentar sin que aparezcan dos cobros. No me gustaría que por un problema de inscripción desaparezcan también los mapas y los horarios.

**14:50 — Stuart**

¿Y si Nike está funcionando pero EasyPay está offline? ¿Qué pasa si el pago se aprobó justo antes de perder la conexión con Nike?

**15:06 — Diego Solano**

Si EasyPay está caído, no cobramos por otra vía: dejamos consultar la carrera y avisamos que el pago no está disponible. Si falla también Nike, se mantienen esas dos restricciones. Si el banco ya aprobó un pago, hay que recuperarlo desde el registro de EasyPay y relacionarlo con la orden pendiente que ya existía en Nike. No cobrar otra vez porque no llegó la respuesta. EasyPay conserva y reenvía las notificaciones según el convenio; ustedes deben comprobar ese comportamiento con ellos. Hasta registrar la confirmación en Nike, el caso sigue en verificación y no se manda un tiquete como si estuviera resuelto.

**16:01 — Stuart**

Para el correo: ¿qué demora toleran y cómo se atiende al comprador si el envío falla?

**16:13 — Valeria Rojas**

La confirmación debe salir dentro de dos minutos de quedar confirmada la inscripción. Si el correo falla, Nike debe poder reenviarlo sin otra compra. El tiquete no debería esperar a que Hacienda o Gatorade vuelvan a estar disponibles; la factura puede llegar después, siguiendo lo que indicó Fiscal. Si una integración deja algo pendiente, nuestro equipo tiene que verlo y saber qué falta. No queremos enterarnos por un patrocinador reclamando.

**16:51 — Stuart**

Quiero separar dos compromisos. Primero, cuánto pueden esperar para volver a usar el servicio después de una falla: ¿qué máximo aceptan normalmente y durante la apertura o la carrera?

**17:09 — Valeria Rojas**

Treinta minutos en un día normal y diez en la apertura de inscripciones y la mañana de la carrera. La información debe estar disponible todo el día, con el objetivo del 99,9 % mensual que se habló antes. Queremos evitar mantenimientos durante las horas de campaña. Si el problema es de Nike o de EasyPay, no esperamos que nos digan simplemente que su parte está bien. Necesitamos que nos ayuden a coordinar y expliquen qué sigue disponible.

**17:51 — Stuart**

Ese es el tiempo de recuperación, RTO. ¿Sus dependencias pueden volver en esos diez minutos? Lo pregunto porque recuperar AWS no reabre ventas si Nike o la pasarela siguen caídos.

**18:09 — Diego Solano**

Nike tiene un compromiso interno de recuperación de hasta cuarenta y cinco minutos; EasyPay nos da hasta treinta en ese tipo de incidente. Y Nike hace mantenimiento de once a once veinte de la noche, sin aceptar ventas. La página informativa debe seguir disponible. Entendemos que el tiempo de recuperar una venta completa queda condicionado por ellos; queremos verlo separado en su propuesta, no escondido dentro del porcentaje de la página.

**18:48 — Stuart**

Entonces el objetivo de la información pública se medirá separado de las ventas. Si dependemos de una recuperación de cuarenta y cinco minutos, no puedo prometer que la compra vuelva en diez. ¿Aceptan esa pausa de venta, manteniendo información disponible y sin guardar datos restringidos en nube?

**19:15 — Valeria Rojas**

Sí, que quede explícito. Preferimos suspender la venta y explicarlo antes que arriesgar datos o cobrar mal. Si pueden mejorar esos tiempos con nuestros proveedores, presenten la alternativa y su costo; no la den por acordada.

**19:36 — Stuart**

La segunda pregunta es sobre pérdida de información. Si hay que recuperar el sistema, ¿qué trabajo reciente podrían repetir y qué operaciones ya confirmadas no pueden desaparecer? A ese límite lo llamamos RPO.

**19:56 — Diego Solano**

Podríamos repetir hasta quince minutos de cambios en contenidos de la carrera. Pero ninguna inscripción confirmada ni ningún pago aprobado puede perderse: para esas operaciones el límite es cero. Un formulario que la persona apenas estaba llenando puede tener que completarse otra vez. Un cargo del banco no. Los datos de las operaciones están en Nike y en los registros autorizados de los proveedores, no queremos una copia de emergencia en AWS como solución.

**20:36 — Stuart**

Para dimensionar esa continuidad, ¿qué uso normal y qué picos prevén?

**20:45 — Valeria Rojas**

Quinientas personas al día normalmente, unas ochocientas al acercarse la carrera. El 18 de noviembre calculamos dos mil en el día y doscientas al mismo tiempo durante diez minutos. El anuncio del 20 puede traer diez mil en el día y mil simultáneas durante quince minutos. El 13 de diciembre serían veinte mil en el día y dos mil simultáneas durante media hora. Es el cálculo de la agencia, no son inscripciones. En la carrera buscarán principalmente mapas y horarios. Y hablando de mapas, había una discusión por dónde iba el acceso de acompañantes...

**21:35 — Stuart**

La dejamos con el mapa aprobado de Nike para no consumir el cierre. Nos faltan el mantenimiento y la aceptación de esta etapa. ¿Qué atención necesitan durante ese período de operación?

**21:54 — Diego Solano**

Dentro de los 4.000 reservados, atención inicial de un incidente crítico en cinco minutos a cualquier hora, y de consultas normales dentro de una hora, de ocho a seis, hora de Costa Rica. La atención inicial no es lo mismo que haber recuperado el servicio. Necesitamos cobertura especial en el anuncio y la carrera, hasta el cierre del servicio el 20 de diciembre. Nike atiende preguntas de corredores, logística y operación de sus sistemas; ustedes coordinan la plataforma de nube y el escalamiento con nuestros contactos.

**22:40 — Stuart**

¿Qué nos entregarán para verificar las conexiones y quién confirma la entrega?

**22:49 — Diego Solano**

El 9 de noviembre entrego mapas, contenidos y reglamento; también las políticas de datos y los contactos autorizados de Nike, Gatorade, EasyPay y Fiscal. Nuestros responsables facilitan los entornos de prueba y accesos por los canales acordados. Yo centralizo las consultas. Valeria valida la información y el recorrido del usuario; Tecnología de Nike valida la infraestructura y las conexiones; Finanzas valida costos y trazabilidad de cobros y facturas. Para esta etapa necesitamos AWS operativo, conectividad verificada y evidencia de que no se guardan datos restringidos. Las pruebas del producto terminado deberán incluir compra, correo y los casos de falla que hablamos. La conformidad se da por escrito, no por silencio.

**23:47 — Stuart**

Voy a separar en la propuesta el proyecto completo de esta primera etapa de nube, con sus 45.000 de honorarios, 6.000 de consumo y 4.000 de mantenimiento. También el RTO de nuestros servicios de los tiempos de Nike y EasyPay, y el RPO de contenidos del de pagos e inscripciones. Mantendremos la información pública cuando se suspendan ventas y no usaremos nube para guardar las operaciones restringidas. ¿Eso refleja lo que quieren que evaluemos?

**24:27 — Valeria Rojas**

Sí. Y no perdamos lo principal: información clara de Nike y Gatorade, vender bien y que la persona reciba su confirmación. La logística nos corresponde a nosotros. Necesitamos su recomendación para que esas condiciones funcionen juntas, con sus costos y límites a la vista.
