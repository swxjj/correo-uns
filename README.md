# Correo UNS · versión 0.1

Aplicación personal para **Windows**, Python 3.11 o superior, FastAPI y SQLite. Se ejecuta en esta PC y abre una interfaz HTML sencilla en español, con barras grises y navegación de correo clásica. No usa hosting, Gmail, servicios pagos ni IA.

## Iniciar en Windows

En esta PC ya quedó preparado el entorno `.venv` del proyecto.

1. Abrí **`Iniciar Correo.cmd`** con doble clic.
2. Se abrirá el navegador en **http://127.0.0.1:8765**.
3. Mantené abierta la ventana de ejecución. Para detener la aplicación, presioná **Ctrl+C** en esa ventana. Cerrar la pestaña no detiene las actualizaciones.

En otra PC o después de extraer el paquete de distribución:

1. Instalá Python 3.11 o superior para Windows desde [python.org](https://www.python.org/downloads/windows/), con el lanzador `py`.
2. Extraé **toda** la carpeta de la aplicación.
3. Ejecutá **`Instalar.cmd`** una vez. Necesita Internet para descargar las bibliotecas gratuitas desde PyPI.
4. Ejecutá **`Iniciar Correo.cmd`**. Podés crear un acceso directo a ese archivo desde el Explorador de Windows.

No se requiere ejecutar como administrador. No hay un ejecutable `.exe` empaquetado en esta primera versión. Una segunda instancia se rechaza mediante el puerto y un bloqueo del archivo local. No cambies la dirección de escucha ni la publiques en una red.

## Configurar la cuenta

Abrí **Configuración** y completá dirección, nombre visible y los usuarios de ambos servicios. Guardá la configuración **antes** de introducir las contraseñas. El usuario generalmente es la dirección completa, incluyendo `@alu.uns.edu.ar`.

Los valores iniciales son los proporcionados por el usuario:

| Servicio | Servidor | Puerto | Seguridad | Autenticación |
|---|---|---|---|---|
| POP3 | `mail.alu.uns.edu.ar` | 110 | STARTTLS obligatorio | Usuario y contraseña |
| SMTP | `mail.alu.uns.edu.ar` | 25 | STARTTLS obligatorio | Usuario y contraseña |

Se intentó consultar [la referencia institucional](https://alu.uns.edu.ar/) el **29 de octubre de 2026**: devolvió un error 502 y la búsqueda no encontró el instructivo. **Estos parámetros no fueron confirmados con la UNS.** Podés editar servidores, puertos y seleccionar STARTTLS o TLS implícito. No existe modo sin cifrado ni se desactiva la validación de certificados o nombres.

Introducí las contraseñas **solo en la aplicación local**, nunca en el chat. Hay campos separados para POP3 y SMTP. La casilla «Guardar en el Administrador de credenciales de Windows» usa directamente la API `CredWriteW`. Si no puede guardarse de esa manera, la aplicación informa que la contraseña queda solo en memoria hasta cerrar. Sin marcar la casilla se utiliza únicamente durante la sesión y se elimina una credencial persistente anterior para esa configuración. «Olvidar contraseña» la elimina de la sesión y del Administrador. Cambiar dirección, servidor, puerto, TLS o usuario requiere volver a introducir la credencial correspondiente.

Probá **POP3 y UIDL** y **autenticación SMTP** por separado. La prueba SMTP **no envía mensajes**. Si POP3 ofrece UIDL, podés activar la actualización automática: inicialmente cada cinco minutos, únicamente mientras el proceso está abierto. Los errores espacian los reintentos hasta una hora; nunca hay un segundo intento automático de envío.

Si no hay UIDL, se informa la limitación y se impiden todas las descargas y la activación automática. Esta versión no incorpora una estrategia alternativa que pueda producir duplicados.

## Uso breve

- **Recibir correo:** descarga solamente los UIDL nuevos de la cuenta. Muestra progreso, última actualización y errores. No ejecuta `DELE` y no borra nada del buzón de la UNS.
- **Bandeja de entrada:** abrí un asunto para leer. Podés destacar, marcar no leído o archivar. Estos estados son **locales** y no se sincronizan con la UNS ni con otros clientes.
- **Buscar:** busca por asunto, remitente o texto del cuerpo dentro de la carpeta seleccionada, sin distinguir mayúsculas, incluidas tildes.
- **Leer:** muestra texto plano inicialmente. «Ver HTML aislado» utiliza saneamiento, una política restrictiva y un iframe sin permisos. No hay imágenes externas, scripts, formularios ni solicitudes remotas automáticas. El HTML se simplifica deliberadamente y las imágenes incrustadas se ofrecen como adjuntos.
- **Adjuntos:** se descargan desde el navegador con nombres seguros y sin rutas elegidas por el mensaje. No se ejecutan ni se abren automáticamente desde la aplicación.
- **Redactar / responder / responder a todos:** admite Para, CC, CCO y adjuntos. Los borradores se guardan tras una pausa breve al escribir y también mediante «Guardar borrador». Las respuestas conservan `In-Reply-To` y `References` y excluyen tu dirección de los destinatarios de respuesta.
- **Enviar ahora:** es la única acción que transmite un mensaje. Guarda un `.eml` sin encabezado CCO para el envío y una copia en Enviados cuando SMTP confirma la aceptación. Los CCO se conservan únicamente como metadatos locales de la copia.
- **Enviados:** significa **aceptado por el servidor SMTP**, no entregado finalmente al destinatario.
- **Envíos pendientes:** registra rechazos y resultados inciertos. Una desconexión durante DATA se trata conservadoramente como incierta. El borrador de un envío aceptado o incierto queda bloqueado para evitar reenvíos accidentales. Verificá el resultado con el destinatario o la UNS antes de crear otro mensaje similar. No se reenvía automáticamente.

**Conservar los originales en esta PC no libera la cuota del buzón universitario.** El servidor sigue almacenando los mensajes.

## Datos, respaldo y restauración

Los datos reales se guardan en **`%LOCALAPPDATA%\CorreoUNS`**, separados del código:

```text
config.json                 Configuración sin contraseñas
sync.json                   Fecha de la última actualización correcta
index.sqlite3               Índice derivado y consultable
messages/<id>.eml           Original de cada mensaje / borrador / envío
messages/<id>.json          UIDL, cuenta, carpeta, estados y metadatos de recuperación
```

El archivo `<id>.json` es la marca de guardado durable: primero se escribe y sincroniza el `.eml`, luego el metadato y finalmente el índice. Los recibidos tienen un identificador determinista por cuenta y UIDL. Al reiniciar se reconstruyen las filas desde los pares `.eml`/`.json`, incluidos los estados locales. Una interrupción antes del metadato deja un archivo no confirmado que vuelve a descargarse sin duplicarse. Una interrupción durante un envío deja un estado incierto al reiniciar. No se debe editar esta carpeta durante la ejecución.

Desde **Respaldo y restauración**:

1. «Guardar copia de seguridad» crea un ZIP consistente usando el respaldo de SQLite y un bloqueo de las escrituras. Incluye configuración sin secretos y todos los pares de originales y metadatos confirmados.
2. Para restaurar, seleccioná un ZIP de esta aplicación y marcá la confirmación informativa. Antes de reemplazar se comprueban rutas, formato y pares de mensajes; se reconstruye el índice desde los originales.
3. La carpeta activa anterior se conserva completa junto a la carpeta de datos, con un nombre como **`CorreoUNS-anterior-20261029-…`**. La interfaz muestra su ruta.
4. Al restaurar se desactiva la actualización automática y se eliminan las credenciales asociadas a las configuraciones actual y restaurada. Volvé a introducirlas y probá las conexiones. El ZIP nunca contiene contraseñas.

El correo y las copias ZIP **no están cifrados**; dependen de la protección del usuario de Windows y del disco. Protegé los respaldos como protegerías tu correo. La aplicación no genera registros de cuerpos, adjuntos ni secretos; el registro de accesos HTTP está desactivado.

Para reconstruir manualmente un índice dañado: detené la aplicación, hacé una copia completa de la carpeta de datos y renombrá `index.sqlite3` a `index.sqlite3.anterior`. Volvé a iniciar. No borres los `.eml` ni los `.json`. Si la carpeta está dañada y la aplicación no inicia, preservala renombrándola con el programa cerrado; iniciá con una carpeta nueva y restaurá un respaldo válido.

## Límites de esta primera versión

- Una sola configuración de cuenta. Si la cambiás, el archivo anterior sigue siendo localmente visible; los UIDL se separan por dirección, servidor POP y usuario.
- Hasta **25 MB de adjuntos por borrador** y **64 MB por solicitud HTTP**, incluida la carga de un ZIP para restaurar. El ZIP se construye en memoria: esta versión está pensada para archivos personales pequeños. Para restaurar copias mayores será necesaria una ampliación del mecanismo de carga; conservá siempre sus originales.
- La búsqueda no indexa el contenido de los adjuntos. No hay filtros, carpetas remotas, sincronización IMAP, calendario, libreta de contactos, borrado remoto ni notificaciones con la aplicación cerrada.
- Se admiten caracteres internacionales en nombres, asuntos y cuerpos MIME. Las direcciones del sobre deben usar caracteres ASCII; no se implementó SMTPUTF8.
- El estado de Envíos pendientes es conservador: algunos fallos de DATA pueden marcarse inciertos aunque el mensaje no haya sido recibido. Esto evita duplicarlo por un reintento automático.
- Una aceptación SMTP seguida de un fallo de disco puede quedar incierta. Revisá el resultado antes de enviar otra copia. La aplicación no puede garantizar la entrega final.

## Pruebas sin cuenta real

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

Las pruebas crean sus archivos temporales y sus propios certificados. Los servidores POP3 y SMTP simulados escuchan exclusivamente en loopback; no contactan a la UNS ni envían correo real. Incluyen una prueba con una credencial **ficticia** en el Administrador de Windows, que se elimina al terminar.

Para explorar una demostración aislada:

```powershell
.\.venv\Scripts\python.exe -m tools.demo
```

Abrí **http://127.0.0.1:8876**. La cabecera dice «DEMOSTRACIÓN · Sin correo real». Usa `output/demo-data`, reemplaza ambos clientes de correo por simuladores y no utiliza el Administrador de credenciales. No introduzcas credenciales reales allí. Detenela con Ctrl+C.

Consultá **`VERIFICACION.md`** para el resultado comprobado y lo pendiente con la UNS.
