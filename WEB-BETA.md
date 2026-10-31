# Beta web para Windows · 0.3

## Acceso actual

La entrada pública de la beta es **https://correo-uns-beta.vercel.app**. El archivo y los mensajes siguen en la PC de Windows del propietario.

Ingresá **apellido**, **LU** y la **contraseña del correo institucional**. El formulario muestra la dirección que se construirá: `apellido.LU@alu.uns.edu.ar`. El apellido se pasa a minúsculas y se quitan las tildes; la LU conserva sus ceros iniciales. Usá el apellido tal como aparece en tu dirección. Esta beta admite solamente la cuenta ya configurada en el servidor; no registra usuarios ni abre archivos de otros alumnos.

Se autentica contra POP3 y SMTP en paralelo usando TLS con certificados válidos. Durante el ingreso no se ejecuta RETR ni DATA: no se descargan ni envían mensajes. Si POP3 autentica pero SMTP falla, podés leer, archivar, buscar y guardar borradores; **Enviar ahora queda deshabilitado**. Para volver a comprobar SMTP, cerrá sesión e ingresá nuevamente.

La contraseña ingresada se usa en memoria, sin guardarla en SQLite, cookies, archivos o logs. No modifica las credenciales que ya existieran en el Administrador de Windows. Esas credenciales previas pueden seguir habilitando las actualizaciones automáticas del backend. La contraseña nueva en memoria se descarta cuando termina la última sesión, al comprobar su vencimiento o al detener el proceso.

Las sesiones vencen tras **30 minutos sin actividad del usuario** o **8 horas como máximo**. La consulta automática de estado no prolonga el tiempo de inactividad. Al vencer, la aplicación pide recargar e ingresar nuevamente; no descarta automáticamente texto sin guardar. Las cookies de Internet son Secure, HttpOnly y SameSite=Strict. El cierre de sesión invalida el identificador en el servidor; reiniciar el backend invalida todas las sesiones.

Hay un máximo global de **5 intentos de ingreso en 5 minutos**, sin reintentos automáticos de contraseña. Es una protección deliberadamente conservadora para esta beta de una sola cuenta. No se muestra si otra dirección institucional existe.

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
- El acceso es solo para el propietario en esta etapa. No compartas la contraseña institucional con testers; para mostrarles la interfaz usá la demostración ficticia.
- Quick Tunnel es temporal y para testing, sin garantía de disponibilidad. Si se detiene la PC, el supervisor o el túnel, Vercel no podrá contactar el archivo.
- Las descargas largas se realizan en segundo plano; el proxy no queda esperando toda la sincronización POP3. Deben comprobarse los tamaños y tiempos de los adjuntos reales de cada uso.
- La versión macOS sigue en el repositorio. La beta de Internet y su supervisor se verifican primero en Windows.

## Demostración sin correo real

```powershell
.\.venv\Scripts\python.exe -m tools.demo --web
```

Abrí `http://127.0.0.1:8876`. Credenciales **ficticias exclusivas de la demo**: apellido `perez`, LU `123456`, contraseña `demo-correo`. POP3 y SMTP están reemplazados por simuladores; no se contacta a la UNS ni se usa el Administrador de credenciales. El modo real no incluye esa cuenta ni una contraseña de prueba.

## Fuentes técnicas

- [Rewrites externos de Vercel](https://vercel.com/docs/routing/rewrites).
- [Límites del proxy de Vercel](https://vercel.com/docs/limits).
- [Quick Tunnels de Cloudflare](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/).
- [Gestión de sesiones de OWASP](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html).
