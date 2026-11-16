-- Datos de ejemplo: ejemplo resuelto de la hoja 3.2 del HDU (suma de montos 8 a 19 = 368.745.318).
-- Ejecutar después de schema.sql. Los valores de instrumento, fecha y secuencia son de ejemplo.
BEGIN;
INSERT INTO corredora (nombre, es_bolsa) VALUES ('Bolsa', TRUE), ('Corredora Demo', FALSE);

WITH nueva AS (
    INSERT INTO calificacion (id_corredora, ejercicio, mercado, instrumento, fecha, secuencia, origen)
    SELECT id_corredora, 2023, 'ACN', 'Copec', DATE '2023-12-12', 123123, 'manual'
    FROM corredora WHERE nombre = 'Corredora Demo'
    RETURNING id_calificacion
), montos AS (
    INSERT INTO monto_calificacion (id_calificacion, numero_columna, monto)
    SELECT id_calificacion, v.col, v.monto
    FROM nueva, (VALUES (8, 192770580), (9, 64161878), (10, 0), (11, 111812860),
                        (25, 71298705), (30, 15837333)) AS v (col, monto)
    RETURNING 1
)
INSERT INTO factor_calificacion (id_calificacion, numero_factor, valor)
SELECT id_calificacion, v.f, v.valor
FROM nueva, (VALUES (8, 0.52277431), (9, 0.17400052), (10, 0.00000000), (11, 0.30322517),
                    (25, 0.19335488), (30, 0.04294924)) AS v (f, valor);
COMMIT;
