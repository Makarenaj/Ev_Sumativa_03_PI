# Ev_Sumativa_03_PI

Mantenedor de Calificaciones Tributarias (caso Nuam). Prototipo del flujo ideal:
inicio de sesión, mantenedor con búsqueda, ingreso de calificación, montos,
Calcular, factores editables, Grabar, modificar y eliminar, con log de cada operación.

Tecnología: Python 3 con Flask, PostgreSQL 16, HTML, CSS y JavaScript sin frameworks.

## Instalar y ejecutar

Requiere Python 3.10 o superior y PostgreSQL 16. Los comandos se ejecutan en la
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
6. Crea un corredor. El ingreso, la modificación y la eliminación son exclusivos
   del perfil corredor, así que sin este paso no se puede mostrar el flujo.
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

## Perfiles y permisos

| Perfil | Calificaciones de su corredora | Otras corredoras | Datos oficiales de Bolsa |
|---|---|---|---|
| Corredor | Consulta, ingresa, modifica y elimina | Sin acceso (responde 404) | Solo lectura |
| Analista | No ingresa ni modifica | Consulta todas | Solo lectura |
| Administrador | No ingresa ni modifica | Consulta todas | Solo lectura |

Si el corredor ingresa una calificación con la misma llave que una oficial de
Bolsa, en su mantenedor se muestra la suya ("Predomina sobre Bolsa").

## Seguridad aplicada

| Patrón | Dónde está |
|---|---|
| Hash de claves (PBKDF2-SHA256 con sal, 600.000 iteraciones) | `seguridad.py`: `hash_clave`, `verificar_clave` |
| Consultas parametrizadas en todo el acceso a datos | `app.py` y `seguridad.py` (parámetros `%s`) |
| Validación de entradas en el servidor (tipo, largo, formato, rango) | `app.py`: `leer_campos`, `leer_montos`, `leer_factores`; `calculo.py`: `validar_factores` |
| Acceso por perfil y por corredora, revisado en el servidor | `app.py`: `requiere_login`, `solo_corredor`, `consultar_registro` |
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

Sin configuración adicional corren 39 pruebas: 13 del cálculo, 9 de seguridad y
17 de las rutas web con una conexión simulada.

Las 26 pruebas de integración usan PostgreSQL real y recorren el flujo ideal y
los casos de error, de borde y de seguridad. La base de pruebas se borra y se
vuelve a crear en cada corrida, por eso su nombre debe terminar en `_test`:

```powershell
psql -U postgres -c "CREATE DATABASE calificaciones_test"
$env:DATABASE_URL_TEST = "postgresql://postgres:TU_CLAVE@localhost:5432/calificaciones_test"
python -m pytest -v test_integracion_pg.py
```

Más decisiones de base de datos, cálculo y seguridad: [DECISIONES.md](./DECISIONES.md).
