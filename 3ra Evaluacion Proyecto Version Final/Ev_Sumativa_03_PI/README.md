# Ev_Sumativa_03_PI

Mantenedor de Calificaciones Tributarias (caso Nuam). Prototipo del flujo ideal:
inicio de sesión, mantenedor con búsqueda, ingreso de calificación, montos,
Calcular, factores editables, Grabar, modificar y eliminar, con log de cada operación.

Tecnología: Python 3 con Flask, PostgreSQL 16, HTML, CSS y JavaScript sin frameworks.

## Instalar y ejecutar

Requiere Python 3.10 o superior y PostgreSQL 16 (probado también en la 18). Los comandos se ejecutan en la
carpeta del proyecto.

1. Crea la base y las tablas:
   ```
   psql -U postgres -c "CREATE DATABASE calificaciones"
   psql -U postgres -d calificaciones -f schema.sql
   ```
   Si la base ya existía con el `schema.sql` anterior, no la borres: ejecuta
   `psql -U postgres -d calificaciones -f migracion_seguridad.sql` (agrega las
   columnas del bloqueo de cuenta).
2. Carga los datos de ejemplo (crea las corredoras "Bolsa" y "Corredora Demo" y
   la calificación del ejemplo del HDU):
   ```
   psql -U postgres -d calificaciones -f seed_ejemplo_hdu.sql
   ```
3. Instala las dependencias:
   ```
   python -m pip install -r requirements.txt
   ```
4. Configura la conexión y la clave de sesión. Cambia `TU_CLAVE` por la clave de
   tu usuario de PostgreSQL.

   PowerShell (Windows):
   ```powershell
   $env:DATABASE_URL = "postgresql://postgres:TU_CLAVE@localhost:5432/calificaciones"
   $env:FLASK_SECRET_KEY = python -c "import secrets; print(secrets.token_hex(32))"
   ```
   Bash (Linux o macOS):
   ```bash
   export DATABASE_URL="postgresql://postgres:TU_CLAVE@localhost:5432/calificaciones"
   export FLASK_SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
   ```
5. Crea el primer administrador:
   ```
   python crear_admin.py
   ```
6. Crea un corredor. El corredor es el único perfil que puede cargar archivos CSV
   y es el que recorre el flujo ideal; el administrador también ingresa, modifica
   y elimina calificaciones, pero eligiendo la corredora.
   Primero mira el ID de la corredora:
   ```
   psql -U postgres -d calificaciones -c "SELECT id_corredora, nombre FROM corredora"
   ```
   Luego ejecuta `python crear_usuario.py`, ingresa con el administrador, elige
   el perfil `corredor` y escribe el ID de "Corredora Demo". Las claves tienen
   un mínimo de 8 caracteres.
7. Inicia el servidor y abre `http://127.0.0.1:5000/login`:
   ```
   python app.py
   ```

Para probar que un corredor no ve lo de otro, crea una segunda corredora con
`psql -U postgres -d calificaciones -c "INSERT INTO corredora (nombre) VALUES ('Corredora Dos')"`
y un segundo corredor con `python crear_usuario.py`. Para cambiar una clave usa
`python cambiar_clave.py`.

Variables opcionales: `MINUTOS_INACTIVIDAD` (15 por defecto) y `COOKIE_SECURE=1`
cuando se publique con HTTPS. La clave de PostgreSQL y la de Flask van en
variables de entorno, nunca en el código.

## Flujo ideal para la demostración

1. Entra como corredor. El mantenedor muestra sus calificaciones y las oficiales
   de Bolsa, con la fuente, la fecha y la suma de factores 8 a 19.
2. Presiona "Ingresar calificación" y completa los datos (la secuencia debe ser
   mayor que 10.000).
3. Escribe los montos del ejemplo del HDU: columna 8 = 192770580, 9 = 64161878,
   10 = 0, 11 = 111812860, 25 = 71298705 y 30 = 15837333.
4. Presiona Calcular. La suma de montos 8 a 19 es 368.745.318, los factores son
   0,52277431; 0,17400052; 0,00000000; 0,30322517; 0,19335488 y 0,04294924, y la
   suma de factores 8 a 19 es 1,00000000. Nada se guarda todavía.
5. Los factores se pueden editar antes de grabar y la suma se actualiza en
   pantalla. Si supera 1, no se graba.
6. Presiona Grabar. La calificación aparece en el mantenedor con fuente "Manual".
7. Usa Ver, Modificar y Eliminar. Cada operación deja una fila en `log_operacion`.
8. Entra a "Carga masiva (CSV)" y sube `ejemplos/carga_valida.csv` (o descárgalo con
   el enlace de la pantalla). La previsualización indica cada fila y si se agrega o
   se actualiza; al confirmar se guardan. Con `ejemplos/carga_con_error.csv` el
   archivo se rechaza completo, indicando la fila y el motivo, y no se guarda nada.
9. Entra como administrador: puede modificar una calificación de cualquier corredora
   y, en "Registro de operaciones", ve quién hizo cada operación, cuándo y con qué
   origen. El analista también consulta el registro, pero no modifica nada.

## Perfiles y permisos

| Perfil | Calificaciones de su corredora | Otras corredoras | Carga CSV | Registro de operaciones | Datos oficiales de Bolsa |
|---|---|---|---|---|---|
| Corredor | Consulta, ingresa, modifica y elimina | Sin acceso (responde 404) | Sí | Sin acceso (403) | Solo lectura |
| Analista | No ingresa ni modifica | Consulta todas | No (403) | Consulta | Solo lectura |
| Administrador | Ingresa, modifica y elimina en cualquier corredora | Ingresa, modifica y elimina | No (403) | Consulta | Solo lectura |

Si el corredor ingresa una calificación con la misma llave que una oficial de
Bolsa, en su mantenedor se muestra la suya ("Predomina sobre Bolsa").

## Seguridad aplicada

| Patrón | Dónde está |
|---|---|
| Hash de claves (PBKDF2-SHA256 con sal, 600.000 iteraciones) | `seguridad.py`: `hash_clave`, `verificar_clave` |
| Consultas parametrizadas en todo el acceso a datos | `app.py` y `seguridad.py` (parámetros `%s`) |
| Validación de entradas en el servidor (tipo, largo, formato, rango) | `app.py`: `leer_campos`, `leer_montos`, `leer_factores`; `calculo.py`: `validar_factores` |
| Acceso por perfil y por corredora, revisado en el servidor | `app.py`: `requiere_login`, `requiere_perfil` (`solo_corredor`, `puede_modificar`), `puede_editar`, `consultar_registro` |
| Validación del archivo CSV (extensión, UTF-8, tamaño, columnas y cada fila) y carga en una sola transacción | `carga_csv.py`: `leer_csv`, `validar_fila_csv`; `app.py`: `cargar_csv`, `aplicar_carga` |
| Token CSRF en todos los formularios | `app.py`: `proteger_post` |
| Bloqueo de la cuenta tras 5 intentos fallidos, por 15 minutos | `seguridad.py`: `autenticar` |
| Cierre de sesión por inactividad y cookie HttpOnly y SameSite | `app.py`: `usuario_actual`, `create_app` |
| Cabeceras de seguridad (CSP, X-Frame-Options, nosniff) | `app.py`: `cabeceras_de_seguridad` |
| Mensajes de error sin detalles técnicos | `app.py`: manejadores de 400, 403, 404 y 500 |
| Datos oficiales y log protegidos también en la base | `schema.sql`: triggers |

## Guía de estilo aplicada

Es la guía del informe de diseño (sección 4.3.4), ampliada a todas las pantallas.
Los colores están como variables en `static/app.css`.

| Elemento | Definición |
|---|---|
| Texto y bordes | `#1A1A1A` |
| Fondo | `#FFFFFF` |
| Acento (botón principal y errores) | `#C8102E` |
| Filas alternas de tablas y campos bloqueados | `#F2F2F2` |
| Tipografía | Arial, Helvetica, sans-serif. Títulos y encabezados de tabla en negrita; texto de apoyo y errores en cursiva |
| Barra superior | Fondo `#1A1A1A`, nombre del sistema y ruta (perfil > sección) |
| Botones | Principal rojo (Ingresar, Grabar), secundario negro (Buscar, Calcular) y terciario con borde (Cancelar, Ver, Modificar) |
| Mensajes | Siempre con texto ("Error:", "Listo:", "Aviso:"), no solo color |
| Tamaños probados | Computador 1366×768 y celular 360×800 |

## Pruebas

```
python -m pytest -q
```

Sin configuración adicional corren 72 pruebas: 13 del cálculo, 33 del CSV, 9 de
seguridad y 17 de las rutas web con una conexión simulada.

Las 38 pruebas de integración usan PostgreSQL real y recorren el flujo ideal y
los casos de error, de borde y de seguridad. La base de pruebas se borra y se
vuelve a crear en cada corrida, por eso su nombre debe terminar en `_test`:

```powershell
psql -U postgres -c "CREATE DATABASE calificaciones_test"
$env:DATABASE_URL_TEST = "postgresql://postgres:TU_CLAVE@localhost:5432/calificaciones_test"
python -m pytest -v test_integracion_pg.py
```

## Consultas manuales a la base de datos

Sirven para extraer y comprobar los datos sin pasar por la aplicación (solo lectura).
Todas están en `consultas_manuales.sql`: corredoras y usuarios (sin la clave),
calificaciones con su fuente y la suma de montos y de factores 8 a 19, montos y
factores de una calificación, calificaciones con suma mayor que 1 (debe salir
vacío), registro de operaciones, cargas de CSV y conteo por corredora.

Todo el archivo (PowerShell o CMD, en la carpeta del proyecto):
```
psql -U postgres -d calificaciones -f consultas_manuales.sql
```

Una consulta suelta, por ejemplo los factores de la calificación 1:
```
psql -U postgres -d calificaciones -c "SELECT numero_factor, valor FROM factor_calificacion WHERE id_calificacion = 1 ORDER BY numero_factor"
```

Exportar a CSV (por ejemplo, todos los factores):
```
psql -U postgres -d calificaciones -c "\copy (SELECT k.instrumento, k.secuencia, f.numero_factor, f.valor FROM calificacion k JOIN factor_calificacion f USING (id_calificacion) ORDER BY k.id_calificacion, f.numero_factor) TO 'factores.csv' CSV HEADER"
```

Con el ejemplo del HDU cargado (`seed_ejemplo_hdu.sql`) la consulta 2 debe mostrar
suma de montos 368745318.00 y suma de factores 1.00000000.
Si `psql` no se reconoce en Windows, usa la ruta completa
(`"C:\Program Files\PostgreSQL\18\bin\psql.exe"`) o agrégalo al PATH con
`set PATH=%PATH%;C:\Program Files\PostgreSQL\18\bin`.

## Decisiones del caso

- Rango de la suma de factores: 8 al 19 (cada factor es su monto dividido por la suma de las columnas 8 a 19).
- Filas inválidas en un CSV: se rechaza todo el archivo hasta que esté completamente válido; no se guarda ninguna fila.
- Llave que identifica una calificación: corredora, ejercicio, mercado, instrumento y secuencia. En la carga masiva, si la llave existe se actualiza y si no se agrega.
- Factores 34 a 37: no se calculan (el HDU no define su regla); solo se guardan si vienen en el CSV.
- Administrador: ingresa, modifica y elimina calificaciones de cualquier corredora; los datos oficiales de Bolsa quedan bloqueados para todos.

## Problemas frecuentes

- `connection refused`: PostgreSQL no está corriendo o `DATABASE_URL` tiene otra clave o puerto.
- La pantalla de carga CSV rechaza el archivo: revisa que sea UTF-8, que tenga las 38 columnas de `ejemplos/carga_valida.csv` y que la suma de los factores 8 a 19 no supere 1. El mensaje indica la fila del archivo (la 1 es el encabezado).

Más decisiones de base de datos, cálculo y seguridad: [DECISIONES.md](./DECISIONES.md).
