# Decisiones de las tareas 2 y 3 (base de datos y cálculo)

Hay que declararlas en el informe (sección 1) y en el README, y el grupo las confirma antes de la demo.

| Tema | Decisión | Por qué |
|---|---|---|
| Rango de la suma | Columnas 8 a 19 | El HDU divide por la suma de 8 a 19. Con 8 a 16 quedarían fuera las rentas exentas (17 a 19). Con el ejemplo del HDU da igual. |
| Fórmula | factor = monto / suma 8 a 19, 8 decimales, columnas 8 a 33 | Es la de la hoja 3.2. |
| Factores 34 a 37 | No se calculan, se ingresan a mano | El HDU no dice la regla. |
| Redondeo | "Mayor resto": se reparte el 0,00000001 que falte para que la suma sea 1,00000000 | Con redondeo simple, 6 montos iguales suman 1,00000002 y se rompe la regla. |
| Montos y factores | Tablas de detalle, una fila por columna | Evita 60 columnas. |
| Tipo de dato | NUMERIC(9,8) y NUMERIC(18,2), sin float | Ojo: Postgres redondea solo si llegan más de 8 decimales, hay que validar antes (`validar_factores`). |
| Llave de la calificación | corredora + ejercicio + mercado + instrumento + secuencia | La sugirió el docente. |
| CSV con filas inválidas | Se rechaza el archivo completo | Evita datos a medias. Queda en carga_archivo como "rechazado". |
| Corredor vs Bolsa | La Bolsa es una corredora (es_bolsa) y sus datos no se modifican ni eliminan | Lo garantizan los triggers de la base. |
| Log | Solo inserción | Trazabilidad: quién, qué, cuándo y origen. |
| Índices | La llave única y (corredora, instrumento); el log por fecha y usuario | Para la búsqueda por instrumento. |
## Cómo usarlo
1. `psql -U postgres -c "CREATE DATABASE calificaciones"` y luego `psql -U postgres -d calificaciones -f schema.sql`
2. Opcional, datos de ejemplo: `psql -U postgres -d calificaciones -f seed_ejemplo_hdu.sql`
3. Tests: `python -m pip install -r requirements.txt` y `python -m pytest -v`.
4. En la aplicación, guardar calificación, montos, factores y log en UNA transacción (la suma se revisa al confirmar).


## Tareas 4 y 5: seguridad e interfaz del flujo

| Tema | Decisión | Por qué |
|---|---|---|
| Quién ingresa, modifica y elimina | El corredor, solo en su corredora, y el administrador, en cualquier corredora. El analista solo consulta. Lo oficial de Bolsa no lo modifica nadie | Se revisa en el servidor (`requiere_perfil`, `puede_editar`), no solo en pantalla, y el trigger de la base lo respalda. |
| Acceso entre corredoras | Pedir por URL un registro de otra corredora responde 404, sin entregar datos | El corredor no debe saber siquiera si el registro existe. |
| Datos oficiales de Bolsa | El corredor los ve en su mantenedor, bloqueados. Si ingresa la misma llave, se muestra la suya ("Predomina sobre Bolsa") | Reglas del HDU: lo del corredor es local y predomina sobre lo de Bolsa. |
| Calcular, Grabar y Cancelar | Calcular muestra los factores y no guarda nada. Los factores 8 a 33 se pueden editar antes de Grabar; lo que se guarda es lo editado | Historias 3 y 4 del HDU. |
| Montos cambiados después de Calcular | Grabar se rechaza y pide calcular de nuevo | Evita guardar factores que no corresponden a los montos. Se comprueba con una firma HMAC de los montos. |
| Suma visible | La suma de montos 8 a 19 y la de factores 8 a 19 se muestran en el formulario, el detalle y la grilla | Lo pidió el docente en la revisión de la ES2. |
| Secuencia | Debe ser mayor que 10.000 | Validación del flujo ideal del docente. |
| Fuente y fecha | La grilla muestra la fuente (manual, carga masiva o Bolsa) y la última modificación | Historias 5 y 16 del HDU. |
| Claves | Hash PBKDF2-SHA256 con sal; mínimo 8 caracteres | Retroalimentación recibida en la ES2. |
| Bloqueo de cuenta | 5 intentos fallidos seguidos bloquean la cuenta 15 minutos | Estaba comprometido en el informe (4.5.1). Agrega dos columnas a `usuario`. |
| Sesión | Se cierra tras 15 minutos sin actividad; el rol se lee de la base en cada solicitud | Estaba comprometido en el informe (4.5.1). |
| Eliminación | Pantalla de confirmación antes de borrar | Funciona también sin JavaScript. |
| Guía de estilo | Blanco y negro con acento rojo `#C8102E` y gris `#F2F2F2`, Arial | Es la guía del informe (4.3.4). Los códigos están en el README. |
| Formato de números | Montos con punto de miles y factores con coma decimal | Formato chileno. Los factores aceptan coma o punto al escribirlos. |

Cómo instalar, ejecutar y probar: ver `README.md`.


## Carga masiva (CSV) y registro de operaciones

| Tema | Decisión | Dónde está |
|---|---|---|
| Quién carga | Solo el corredor, en su corredora | `app.py`: `cargar_csv` (`solo_corredor`) |
| Formato | Hoja 3.1 del HDU: ejercicio, mercado, instrumento, fecha, secuencia, numero_dividendo, tipo_sociedad, valor_historico y factor_8 a factor_37. Coma o punto y coma, UTF-8, máximo 5.000 filas y 4 MB | `carga_csv.py` |
| Filas inválidas | Se rechaza el archivo completo y no se guarda nada; la carga rechazada queda en `carga_archivo` con su motivo | `app.py`: `registrar_rechazo` |
| Llave y actualización | Si la llave (corredora, ejercicio, mercado, instrumento, secuencia) existe se actualiza; si no, se agrega. Al actualizar con factores se borran los montos anteriores | `app.py`: `aplicar_carga` |
| Transacción | Toda la carga se guarda en una sola transacción: o entra completa o no entra | `app.py`: `aplicar_carga` |
| Log | Una entrada `carga_masiva` por archivo, con agregadas y actualizadas, y origen `carga_masiva` | `app.py`: `insertar_log` |
| Quién lee el log | Analista y administrador, en solo lectura | `app.py`: `ver_log`, `templates/log.html` |
