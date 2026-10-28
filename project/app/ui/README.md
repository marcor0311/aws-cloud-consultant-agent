# Oficina virtual

Vista 3D de la consultora con navegación por áreas. La interfaz inicial muestra únicamente la oficina, el selector de espacios y los controles. Los rótulos están desactivados por defecto.

Seleccionar una oficina muestra un encuadre cercano de su interior, ajustándose al tamaño de la pantalla. La puerta, su marco y la pared de entrada permanecen visibles en todas las vistas. El monitor y el teclado permanecen centrados. La placa compacta de metal cepillado, con texto negro en negrita y base metálica fina, queda más adelante del monitor, con separación entre ambas piezas.

Desde la raíz del repositorio:

```sh
python3 -m http.server 8765 --bind 127.0.0.1 --directory project/app/ui
```

Abrir `http://127.0.0.1:8765/office-dashboard.html` en la vista web del IDE. No requiere iniciar la API ni configurar credenciales. Three.js se carga desde jsDelivr y requiere conexión y WebGL.

## Distribución y circulación

La oficina ocupa una única planta con un pavimento continuo, cerramiento exterior, ventanas y divisiones interiores conectadas. La zona de café y la pizarra se integran en la pared posterior. Los ventanales exteriores son paños continuos, con apoyos en las esquinas. Las oficinas privadas tienen paredes opacas, estanterías y una selección de libros, láminas y objetos propios de cada área. La sala de juntas conserva su cerramiento de vidrio. No hay plataformas por área.

Se conserva el layout aprobado: árbol central de copa compacta y redondeada, bancos curvos alrededor y una mesa comunal longitudinal en orientación vertical. Las seis sillas tapizadas, el roble claro y la alimentación integrada se mantienen. No se añaden plataformas ni piezas que bloqueen los accesos.

Cada oficina tiene una planta de follaje lleno en la esquina interior junto a la entrada, separada de la estantería y de las hojas correderas, una credenza baja, una alfombra de trama fina y una silla de visita compacta frente al escritorio. La silla queda desplazada respecto al acceso. Durante cada visita, la nube se eleva antes de aproximarse a la silla, descansa sobre ella mirando al escritorio y vuelve al punto despejado antes de reanudar el circuito.

Las áreas laterales de concentración y conversación añadidas durante la exploración se han retirado, junto con sus controles y paradas. La fachada de acceso se alinea con el frente de las primeras oficinas; se elimina la franja residual y los tramos bajos junto a la entrada. Las oficinas privadas mantienen paredes, estanterías y personalidad, y la sala de juntas conserva el vidrio.

La cubierta y las partes superiores de las fachadas próximas a la cámara se omiten visualmente para ver el interior; la geometría completa sigue participando en la navegación. Las puertas correderas dobles y los pasillos laterales se mantienen despejados. El agente visita siete destinos sobre rutas A* calculadas desde las geometrías de la oficina. El radio de paso es de 0,8 unidades e incluye paredes, muebles y los paneles de las puertas tanto abiertos como en movimiento. Los segmentos suavizados vuelven a comprobarse con el mismo margen; el agente espera si una hoja todavía obstruye el paso.

El agente es una nube flotante de volumen continuo, con ojos discretos y una expresión suave. No tiene bolso, zapatos, extremidades, tablet ni otros accesorios. Mantiene un movimiento lento y parpadeo ocasional. Se detiene en zonas libres y ajusta su altura de flotación al suelo y las alfombras; no intenta ocupar sillas.

## Archivos

- `office-dashboard.html`, `.css`, `.js`: interfaz, controles y errores.
- `office-scene.js`: distribución, iluminación, puertas y recorrido.
- `assets/office-navigation.js`: planificación y comprobación de circulación.
- `assets/office-assets.js`: materiales, mobiliario, vegetación y pantallas.
- `assets/office-plant.js`: planta de interior con hojas curvas y follaje denso.
- `assets/office-seat-motion.js`: aproximación, descanso y regreso de la nube desde las sillas de visita.
- `assets/commons-space.js`: mesa comunal vertical y bancos alrededor del árbol central.
- `assets/commons-seating.js`: modelos reutilizables de sillas y butacas tapizadas.
- `assets/cloud-agent.js`: modelo y animación del agente.
- `tests/office-navigation.test.mjs`: regresiones de obstáculos, accesos y puertas.

Los controles permiten acercar, alejar, restablecer, mirar desde arriba, alternar rótulos, seguir al agente y pausar. Girar la cámara o seleccionar otra área sale del seguimiento. La ayuda se abre solo al solicitarla. La preferencia de movimiento reducido inicia el agente en pausa; la animación se suspende en pestañas ocultas.

## Verificación

```sh
node --test project/app/ui/tests/*.test.mjs
```

Las pruebas cubren desvíos alrededor de muebles, accesos demasiado estrechos, puertas abiertas y cerradas, límites del suelo, destinos obstruidos y la elevación y el regreso desde las sillas. Los cambios de distribución deben comprobarse también en navegador recorriendo el circuito completo, incluidas las salidas de las oficinas. Durante las visitas a las sillas se comprueba el volumen del agente en 3D, además del margen de circulación en el suelo.

Las referencias visuales seleccionadas se reúnen en [REFERENCIAS.md](REFERENCIAS.md). La búsqueda mantiene como base el árbol central, los asientos alrededor y la mesa vertical; las posibles incorporaciones se estudian en los márgenes del espacio común.
