# Cambios del repositorio (para revisar y subir como commits)

Todos los cambios están en la carpeta `Ev_Sumativa_03_PI/`. Con la base de pruebas creada, `python -m pytest -q` pasa las 110 pruebas (72 sin base de datos y 38 de integración con PostgreSQL 16).

## 1. El administrador puede ingresar, modificar y eliminar
- `app.py`: nuevo `requiere_perfil(...)`; `solo_corredor` (carga CSV) y `puede_modificar` (corredor y administrador) salen de él. `puede_editar` deja editar al administrador en cualquier corredora (nunca lo oficial de Bolsa). `nueva_calificacion` toma la corredora del formulario cuando la crea un administrador y rechaza la Bolsa.
- `templates/formulario.html`: lista de corredoras para el administrador; `templates/calificaciones.html`: botones según perfil.
- `test_integracion_pg.py`: el analista sigue de solo lectura; pruebas nuevas del administrador.

## 2. Carga masiva por CSV completa
- `carga_csv.py` (nuevo): formato de la hoja 3.1 del HDU, validación fila por fila, rechazo del archivo completo, coma o punto y coma, UTF-8, máximo 5.000 filas.
- `app.py`: `cargar_csv` con previsualización (agrega o actualiza), confirmación en una sola transacción, registro en `carga_archivo` y en el log; `ejemplo_csv` (descarga de ejemplo); error 413 para archivos grandes.
- `templates/cargar_csv.html` (nuevo; reemplaza a `cargar-csv.html`, cuyo nombre no coincidía con el que pedía el código).
- `ejemplos/`: `carga_valida.csv`, `carga_con_error.csv`, `carga_formato_incorrecto.csv` y `generar_csv_estres.py`.

## 3. Registro de operaciones (log)
- `templates/log.html` (nuevo): la ruta `/log` existía pero la plantilla no.
- `templates/base.html` y `static/app.css`: menú por perfil (Carga masiva para el corredor; Registro de operaciones para analista y administrador).

## 4. Pruebas y documentos
- `test_csv.py` (nuevo, 33 pruebas) y pruebas de integración nuevas (administrador, log, menú y CSV, incluida la de 1.000 filas).
- `README.md` y `DECISIONES.md`: perfiles, flujo ideal con CSV y log, seguridad, decisiones del caso y problemas frecuentes.

## Antes de la demostración
- Ejecutar `python -m pytest -q` en su computador y guardar la captura para el informe de pruebas.
- Crear un corredor y un analista con `python crear_usuario.py` para recorrer los tres perfiles.
- Revisar cada archivo cambiado: Programación y Preguntas son individuales y cada uno debe poder explicar lo que sube.
