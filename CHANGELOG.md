# Cambios

## 0.1 · 2026-10-29

- Cliente personal local para Windows, con FastAPI, SQLite y HTML en español.
- Configuración de una cuenta POP3/SMTP, TLS obligatorio y contraseñas en el Administrador de credenciales de Windows o solo por sesión.
- Descarga incremental por UIDL sin borrado remoto, originales `.eml` y metadatos para recuperar el índice.
- Lectura MIME, HTML saneado y aislado, adjuntos seguros, búsqueda y estados locales.
- Borradores con adjuntos, respuestas con referencias, CCO en el sobre y archivo de enviados aceptados por SMTP.
- Tratamiento persistente de resultados inciertos de envío y bloqueo de reenvíos automáticos.
- Respaldo consistente y restauración con preservación de los datos anteriores.
- Lanzadores de Windows, dependencias verificadas, demostración aislada y paquete de distribución.
- Correcciones específicas de Windows para cierre de SQLite, bloqueo entre instancias y limpieza de sockets tras fallos TLS.
- Diagnóstico por servicio y etapa de conexión, códigos SMTP y clasificación segura de errores POP3.
- Sonda TLS sin lectura de credenciales, autenticación ni envío de mensajes.
- 58 pruebas automáticas con datos ficticios y servidores locales simulados.

El historial inicial se organizó por funcionalidades a partir de la primera versión ya implementada. Los commits registran esta incorporación al repositorio, sin reconstruir fechas anteriores.
