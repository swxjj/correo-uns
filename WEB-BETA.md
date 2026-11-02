# Beta web para Windows · 0.4

## Acceso actual

La entrada pública de la beta es **https://correo-uns-beta.vercel.app**. El archivo y los mensajes siguen en la PC de Windows del propietario.

Ingresá **apellido**, **LU** y la **contraseña del correo institucional**. El formulario muestra la dirección que se construirá: `apellido.LU@alu.uns.edu.ar`. El apellido se pasa a minúsculas y se quitan las tildes; la LU conserva sus ceros iniciales. Usá el apellido tal como aparece en tu dirección. Se admite la cuenta propietaria y las cuentas invitadas expresamente en una lista local; no hay registro público. Cada cuenta accede únicamente a su propio archivo. La cuenta activa aparece en el encabezado.

Se autentica contra POP3 y SMTP en paralelo usando TLS con certificados válidos. Durante el ingreso no se ejecuta RETR ni DATA: no se descargan ni envían mensajes. Si POP3 autentica pero SMTP falla, podés leer, archivar, buscar y guardar borradores; **Enviar ahora queda deshabilitado**. Para volver a comprobar SMTP, cerrá sesión e ingresá nuevamente.

La contraseña ingresada se usa en memoria, sin guardarla en SQLite, cookies, archivos o logs. La cuenta propietaria conserva de forma independiente las credenciales que ya existieran en el Administrador de Windows; pueden seguir habilitando sus actualizaciones automáticas. Las cuentas invitadas no utilizan ese almacén ni heredan credenciales de la cuenta propietaria. La contraseña de cada cuenta se descarta cuando termina su última sesión, al comprobar el vencimiento o al detener el proceso. Las actualizaciones automáticas de invitados se pausan sin sesiones activas y se reanudan tras un nuevo ingreso válido, si estaban habilitadas.

Las sesiones vencen tras **30 minutos sin actividad del usuario** o **8 horas como máximo**. La consulta automática de estado no prolonga el tiempo de inactividad. Al vencer, la aplicación pide recargar e ingresar nuevamente; no descarta automáticamente texto sin guardar. Las cookies de Internet son Secure, HttpOnly y SameSite=Strict. El cierre de sesión invalida el identificador en el servidor; reiniciar el backend invalida todas las sesiones.

Hay un máximo de **5 intentos de ingreso por cuenta en 5 minutos**, más un límite global de **30 intentos en 5 minutos**, sin reintentos automáticos de contraseña. Los errores de una cuenta no consumen el cupo individual de otra. Cada cuenta puede mantener hasta 16 sesiones; crear sesiones de invitado no expulsa las del propietario. No se muestra si otra dirección institucional existe.

## Invitar y revocar cuentas desde Windows

Las invitaciones se administran únicamente desde la PC del propietario, sin contraseñas. Ejemplo con una identidad **ficticia**:

```powershell
.\.venv\Scripts\python.exe -m tools.users add --surname gomez --lu 234567
.\.venv\Scripts\python.exe -m tools.users list
.\.venv\Scripts\python.exe -m tools.users remove --surname gomez --lu 234567
```

La lista real está en **`%LOCALAPPDATA%\CorreoUNS-usuarios\access.json`**, fuera del código y excluida de Git. Invitar no crea ni modifica una cuenta de la UNS: el invitado debe introducir su propia contraseña en el formulario y superar la autenticación POP3. No se crea su archivo antes de una autenticación correcta. La lista se comprueba en cada acceso; revocar invalida las sesiones de esa cuenta y pausa sus descargas, sin borrar sus mensajes ni cerrar otras sesiones. Una operación que ya estaba en curso puede terminar.

Tu archivo existente sigue en **`%LOCALAPPDATA%\CorreoUNS`**, sin migración. Cada invitado utiliza su propia carpeta bajo **`%LOCALAPPDATA%\CorreoUNS-usuarios\mailboxes\<identificador>`**, con SQLite, originales, borradores, enviados, estados y credenciales en memoria independientes. Los servidores y puertos se toman de la configuración institucional del propietario; los usuarios POP3 y SMTP siempre corresponden a la dirección autenticada del invitado.

Cada descarga de respaldo incluye únicamente el archivo de quien inició sesión. La copia de la cuenta propietaria no incluye ni elimina las carpetas de invitados. Respaldá por separado los archivos invitados y la lista de acceso cuando hagas mantenimiento de toda la PC. Para localizar las carpetas:

```powershell
.\.venv\Scripts\python.exe -m tools.users list --paths
```

Para restaurar un archivo invitado, detené la beta y abrí el modo local indicando **su** carpeta mediante `python -m correo --data "ruta-del-archivo-invitado"`. Seleccioná un respaldo de esa misma cuenta. No restaures la copia invitada sobre la carpeta de la cuenta propietaria. Los archivos se bloquean entre procesos para impedir que el modo local y la beta los abran simultáneamente.

El aislamiento lo aplica la aplicación; los originales y respaldos siguen sin cifrado. El administrador de Windows puede acceder a los archivos de los invitados en el disco. Informá esto a cada invitado antes de que use la beta. Para probar dos cuentas en una misma PC, usá perfiles de navegador distintos o cerrá sesión antes de cambiar de cuenta.

## Tres formas de iniciar

### Modo local existente

**`Iniciar Correo.cmd`** conserva el funcionamiento anterior, accesible solo en loopback. Usalo para administrar servidores, credenciales y restauraciones. No expongas este modo mediante un túnel.

### Probar el login en la misma PC

**`Iniciar Beta Web.cmd`** abre la interfaz con autenticación en `http://127.0.0.1:8765`. La excepción HTTP existe únicamente para pruebas en loopback. No habilita acceso desde la red.

### Backend y túnel de Internet

Antes de iniciar, cerrá otras instancias que estén usando el mismo archivo local. Ejecutá **`Iniciar Beta Internet.cmd`** o:

```powershell
.\.venv\Scripts\python.exe -m tools.start_web_beta --origin https://correo-uns-beta.vercel.app
```

El supervisor:

1. Usa `cloudflared` instalado, o descarga el binario oficial de Windows en `output/bin` comprobando el SHA-256 publicado en GitHub.
2. Inicia el backend **con login obligatorio**, escuchando únicamente en `127.0.0.1:8875`, y verifica el formulario antes de abrir el túnel. Si la cuenta no está configurada o el archivo ya está abierto, no expone otro proceso por accidente.
3. Abre un Quick Tunnel temporal y genera en `output/vercel-beta` los únicos archivos que deben publicarse en Vercel: configuración del proxy y `robots.txt`.
4. Muestra el destino temporal del proxy y la URL de acceso. `output/web-beta-runtime.json` guarda únicamente URLs, puerto y los identificadores de los procesos, sin credenciales.
5. Al presionar Ctrl+C o al finalizar uno de los procesos, detiene el backend y el túnel. No es un servicio de Windows y no se inicia solo al encender la PC.

**La dirección del Quick Tunnel cambia cada vez que se reinicia.** La dirección de Vercel permanece fija, pero es necesario publicar nuevamente el destino del proxy. Dejar la PC encendida también requiere mantener el supervisor ejecutándose y evitar que Windows entre en suspensión.

## Actualizar el destino en Vercel

El proyecto de Vercel se llama `correo-uns-beta`. Publicá únicamente la carpeta generada `output/vercel-beta`, nunca el repositorio completo ni LOCALAPPDATA.

Con Vercel CLI instalado y autenticado localmente mediante `vercel login`:

```powershell
vercel deploy .\output\vercel-beta --prod --yes
```

La primera vez, asociá esa carpeta al proyecto **existente** `correo-uns-beta` con `vercel link`, para no crear otro proyecto por error. La carpeta `.vercel` contiene metadatos de enlace y está excluida de Git.

Después de enlazarla, podés usar:

```powershell
.\.venv\Scripts\python.exe -m tools.start_web_beta --origin https://correo-uns-beta.vercel.app --publish
```

No compartas tokens de Vercel por chat ni los agregues al repositorio. La sesión de la integración Vercel de Codex es independiente del login de Vercel CLI en Windows. La primera publicación de esta beta se realizó con la integración conectada; eso no inicia sesión automáticamente en el CLI.

Sin CLI, también podés actualizar el destino mediante las reglas de proxy del proyecto en Vercel. El contenido correcto se genera siempre en `output/vercel-beta/vercel.json`.

## Límites y administración

- Vercel funciona como entrada y proxy; **FastAPI, SQLite, los `.eml`, los borradores y las descargas automáticas corren en Windows**.
- El navegador utiliza una sola dirección. No se habilita CORS abierto ni se guardan contraseñas o sesiones en localStorage.
- Toda la API, incluidos HTML de mensajes, originales, adjuntos y respaldos, requiere sesión y token CSRF. También se comprueba el origen de las operaciones.
- Las respuestas privadas incluyen `Cache-Control`, `CDN-Cache-Control` y `Vercel-CDN-Cache-Control` con instrucciones para no almacenar caché.
- El túnel no abre puertos entrantes del router. Sus rutas siguen protegidas por la misma autenticación; conocer la URL del túnel no permite leer el correo.
- Vercel y Cloudflare intervienen en el transporte HTTPS. Los mensajes permanecen almacenados en la PC, pero el tráfico pasa por esos proveedores.
- Desde la web se pueden cambiar nombre visible e intervalo de actualización y descargar respaldos. La cuenta, los servidores, la gestión de credenciales, la restauración y la salida del proceso se administran únicamente en modo local.
- El acceso se limita al propietario y su lista de invitados. Cada persona usa su propia contraseña institucional; no compartas credenciales entre testers.
- Quick Tunnel es temporal y para testing, sin garantía de disponibilidad. Si se detiene la PC, el supervisor o el túnel, Vercel no podrá contactar el archivo.
- Las descargas largas se realizan en segundo plano; el proxy no queda esperando toda la sincronización POP3. Deben comprobarse los tamaños y tiempos de los adjuntos reales de cada uso.
- La versión macOS sigue en el repositorio. La beta de Internet y su supervisor se verifican primero en Windows.

## Demostración sin correo real

```powershell
.\.venv\Scripts\python.exe -m tools.demo --web
```

Abrí `http://127.0.0.1:8876`. Credenciales **ficticias exclusivas de la demo**: propietario `perez`, LU `123456`; invitado `gomez`, LU `234567`; ambos con contraseña `demo-correo`. Cada uno ve un mensaje ficticio distinto en su propio buzón. POP3 y SMTP están reemplazados por simuladores; no se contacta a la UNS ni se usa el Administrador de credenciales. El modo real no incluye estas cuentas ni una contraseña de prueba.

## Fuentes técnicas

- [Rewrites externos de Vercel](https://vercel.com/docs/routing/rewrites).
- [Límites del proxy de Vercel](https://vercel.com/docs/limits).
- [Quick Tunnels de Cloudflare](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/).
- [Gestión de sesiones de OWASP](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html).
