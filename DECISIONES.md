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
3. Tests: `pip install pytest` y `python -m pytest -v` (15 casos).
4. En la aplicación, guardar calificación, montos, factores y log en UNA transacción (la suma se revisa al confirmar).
