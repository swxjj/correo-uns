# Verificación de la versión 0.1

Fecha: **29 de octubre de 2026**. Entorno: **Windows, Python 3.11.9**.

Resultado final:

```text
58 passed, 1 warning in 31.58s
```

Además se comprobaron la compilación de los módulos Python y la sintaxis de `correo/static/app.js` con Node. La advertencia de pytest corresponde a una futura migración del cliente de pruebas de Starlette de httpx a httpx2; no produjo fallos.

## Pruebas automáticas

| Área | Comprobaciones |
|---|---|
| Recepción | UIDL repetido sin nuevas descargas, UIDL separado por cuenta, servidor sin UIDL, bloqueo de operaciones simultáneas y ausencia de `DELE`. |
| Interrupciones | Corte durante la descarga, corte antes de los metadatos y después de guardar metadatos pero antes de actualizar SQLite; recuperación y deduplicación al reiniciar. |
| Archivo | Reconstrucción del índice desde `.eml` y `.json`, conservación de leído/destacado/archivado y búsqueda con mayúsculas y tildes. |
| MIME y adjuntos | Asuntos y cuerpos internacionales, adjunto binario, mensaje `.eml` adjunto sin mezclar su cuerpo con el principal, nombres peligrosos de Windows y rutas de escape. |
| HTML | Eliminación de etiquetas y atributos activos, formularios, imágenes remotas, SVG y enlaces ejecutables; respuesta con política restrictiva y vista aislada. |
| TLS | Servidores locales con sockets reales para POP3 y SMTP, STARTTLS y TLS implícito; rechazo de certificado no confiable y de nombre incorrecto antes de transmitir las credenciales. |
| Diagnóstico | Autenticación SMTP rechazada, errores POP3 sin revelar respuestas sensibles y prueba SMTP que no ejecuta MAIL/RCPT/DATA. |
| Envío | CCO presente solo en el sobre, referencias de respuesta, copia aceptada en Enviados, rechazo de destinatario antes de DATA, rechazo definitivo de DATA y resultado incierto por desconexión real del socket. |
| Reintentos | Bloqueo de reenvíos del mismo borrador aceptado o incierto, estado incierto al reiniciar durante un envío y actualización automática con espera creciente ante fallos. |
| Secretos | Credencial ficticia guardada y recuperada mediante el Administrador de Windows y eliminada al terminar; alternativa solo en memoria; ausencia del secreto en configuración, ZIP y errores de validación. |
| Seguridad local | Bloqueo de Host externo, Origin externo o null, peticiones cross-site, token incorrecto y preflight externo; cabeceras contra caché y framing. |
| Respaldo | Copia consistente, restauración, conservación de los datos anteriores, metadatos intactos, desactivación de actualización automática y eliminación de credenciales al restaurar. |
| Restauración inválida | Rechazo de rutas de escape y respaldos incompletos sin modificar el archivo activo; exclusión de originales no confirmados de la copia. |
| Lanzamiento | Arranque HTTP con el lanzador real, rechazo de una segunda instancia en otro puerto sobre el mismo archivo y rechazo del puerto ocupado. Escucha observada únicamente en `127.0.0.1`. |

Los certificados de prueba son temporales y únicamente se confían dentro de las pruebas. El código de producción utiliza siempre `ssl.create_default_context()` con validación de certificado y nombre, sin excepciones para la UNS.

Las pruebas detectaron dos problemas específicos de Windows, corregidos y cubiertos: cierre explícito de conexiones SQLite antes de copiar/restaurar y lectura del archivo de bloqueo de una segunda instancia. También se corrigió que el cierre de un socket TLS fallido pudiera ocultar el error original de certificado.

## Recorrido en navegador

Se utilizó Chromium mediante Playwright CLI en **http://127.0.0.1:8876**, con la cabecera visible «DEMOSTRACIÓN · Sin correo real». Los clientes POP3 y SMTP se reemplazaron por simuladores sin acceso de red.

Se verificó manualmente mediante automatización de interfaz:

1. Abrir Entrada y leer un mensaje MIME ficticio con tildes y adjunto.
2. Abrir el HTML aislado: el script se mostró como texto inerte y la imagen remota no se cargó.
3. Responder a todos, editar el cuerpo, completar CCO y guardar el borrador.
4. Seleccionar y guardar un adjunto ficticio mediante el selector de archivos.
5. Presionar Enviar ahora contra el simulador y comprobar la aparición en Enviados con el aviso sobre aceptación SMTP.
6. Descargar el ZIP desde Respaldo y restauración, seleccionarlo, restaurarlo y comprobar la ruta de la carpeta anterior protegida.
7. Abrir Configuración y ejecutar por separado las pruebas POP3/UIDL y autenticación SMTP contra los simuladores.
8. Buscar `INSCRIPCIÓN` y encontrar el texto del mensaje restaurado.

Se inspeccionó visualmente la captura `output/playwright/lectura.png`. El único error de consola inicial fue la solicitud de `favicon.ico`, para la que se agregó una respuesta vacía. El navegador y los servidores de prueba se cerraron al terminar.

## Pendiente con la cuenta real de la UNS

No se introdujeron credenciales reales durante estas verificaciones, no se autenticó una cuenta universitaria y no se envió correo real.

Actualización de diagnóstico: se comprobó la conexión con los servidores reales configurados, **sin leer credenciales, iniciar sesión ni enviar mensajes**. POP3 (110/STARTTLS) y SMTP (25/STARTTLS) establecieron TLS y validaron sus certificados. Esta comprobación puntual no confirma la disponibilidad de la autenticación ni de UIDL. Puede repetirse con `python -m tools.probe_tls`.

Los errores de conexión ahora distinguen servicio y etapa (saludo, STARTTLS, USER, PASS o AUTH). SMTP muestra únicamente códigos numéricos permitidos; POP3 clasifica respuestas temporales o de buzón ocupado usando condiciones conocidas. No se copian respuestas del servidor a la interfaz o los registros. Ocho pruebas adicionales verifican estas distinciones y que no se expongan datos sensibles.

- Confirmar parámetros institucionales: [alu.uns.edu.ar](https://alu.uns.edu.ar/) devolvió 502 al consultarlo; no se pudo acceder al instructivo.
- Introducir las credenciales **en la aplicación local** y ejecutar ambos diagnósticos.
- Confirmar autenticación y disponibilidad de UIDL con la cuenta. STARTTLS, certificados y acceso a los puertos 110 y 25 se comprobaron sin autenticación, según la actualización anterior.
- Probar la primera descarga y, solo cuando el usuario lo decida expresamente en la interfaz, un envío real. Confirmar su entrega por un medio independiente: la respuesta SMTP solo confirma aceptación.
- Comprobar restricciones particulares de la UNS, como tamaños permitidos, cuotas o destinatarios admitidos. La aplicación nunca evita esas restricciones degradando TLS.

Los límites de esta versión están documentados en README.md, especialmente los 25 MB de adjuntos por borrador y los 64 MB por carga HTTP de respaldo.
