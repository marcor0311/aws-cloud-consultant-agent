# Reunión ficticia de Nike: maratón en Costa Rica

Escenario completamente guionado para probar generación de documentos. Nike es el
cliente del escenario solicitado; los participantes y sus declaraciones son ficticios.

- `transcript.json`: 22 intervenciones con nombres, tiempos e identificadores.
- `content.json`: preparación guionada ligada al SHA-256 de la transcripción;
  cada cifra y sección identifica su evidencia.
- Los 10.000 usuarios corresponden al día de campaña y los 500 a cada día
  posterior. Los 1.500 son sesiones por semana de una campaña anterior.
- El caso fue refinado con autorización del usuario: el cliente llega a Stuart
  con el encargo definido; la consultora desarrolla y escala la solución.
- Las fechas, sede, inversión máxima de USD 24.000 y escenario de validación
  se incorporaron como hechos de la ficción, no como información real de Nike.
- La concurrencia de 1.000 personas durante quince minutos es un escenario
  declarado; no se infiere de la cifra diaria ni se ejecuta en la demo.
- `proposal` y `executive` conservan recomendaciones de No Name con estado
  `proposed`. Tener evidencia de una necesidad no equivale a tener aprobación
  de la solución. La revisión del flujo permanece en `awaiting_review`.

Desde la raíz: `make insumos-mock`. El comando ejecuta el grafo real de preparación
con proveedor ficticio, se detiene en revisión humana y exporta los tres insumos.
No utiliza credenciales, registros de clientes ni bases de datos del proyecto.

La prueba guionada verifica el flujo y el renderizado; no demuestra la comprensión
de una transcripción nueva por un modelo real.
