# Correo UNS para macOS

## Uso diario

1. Descomprimí `CorreoUNS-macOS-arm64.zip` (Mac con chip Apple).
2. Mové **Correo UNS.app** a **Aplicaciones** y abrila con doble clic. No hace falta instalar Python ni usar Terminal.
3. Se abre el navegador. En **Configuración**, completá tu cuenta y los usuarios POP3 y SMTP, y guardá.
4. Introducí las contraseñas en la aplicación. Marcá **Recordar contraseña** para conservarlas en el Llavero de macOS. Si macOS solicita acceso al Llavero, permitilo para recordar la contraseña.
5. Probá POP3 y SMTP por separado. Después podés recibir correo y activar la actualización automática.

El botón **Salir de Correo UNS** de la barra lateral cierra la aplicación. El menú **✉ UNS** de la barra superior también permite volver a abrir el correo y salir. Cerrar la pestaña deja la aplicación actualizando. Al salir, se pide esperar si hay un envío u otra operación en curso.

Los mensajes y la configuración se guardan en `~/Library/Application Support/CorreoUNS`, separados de la aplicación. Reemplazar la app no elimina el correo. Los respaldos ZIP de la versión Windows se restauran desde **Respaldo y restauración**; después hay que introducir nuevamente las contraseñas.

El paquete está firmado localmente, sin certificado Developer ID ni notarización de Apple. Para distribuirlo a otros equipos sin avisos de Gatekeeper hace falta firmar y notarizar con una cuenta de desarrollador. Esta compilación es para **Apple Silicon (arm64)**; para Intel hay que construir el paquete en un Mac Intel.

## Ejecutar desde el código fuente

Requiere Python 3.11 o superior. Abrí `Iniciar Correo.command`: prepara el entorno automáticamente la primera vez, con conexión a Internet. El paquete `.app` es la opción recomendada para uso diario.

## Construir la aplicación

En macOS y desde la carpeta del repo:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-build-macos.txt
.venv/bin/python -m tools.build_macos
```

La firma se genera en una carpeta temporal limpia; mové la aplicación a Aplicaciones antes de usarla. El resultado queda en `output/Correo UNS.app` y `output/CorreoUNS-macOS-<arquitectura>.zip`. El paquete incluye intérprete, certificados TLS y dependencias. Nunca incluye datos personales ni contraseñas.

## Pruebas

```sh
.venv/bin/python -m pip install -r requirements-dev.txt -r requirements-macos.txt
.venv/bin/python -m pytest -q
```

La prueba del Llavero crea y elimina una credencial ficticia. Los servicios POP3/SMTP de prueba son locales; no envían correo real.
