-- Consultas manuales para extraer datos del mantenedor (solo lectura).
-- Ejecutar: psql -U postgres -d calificaciones -f consultas_manuales.sql
-- Para una sola consulta, copia el bloque y usa: psql -U postgres -d calificaciones -c "..."

\echo '== 1) Corredoras y usuarios (sin la clave) =='
SELECT c.id_corredora, c.nombre AS corredora, c.es_bolsa
FROM corredora c ORDER BY c.id_corredora;

SELECT u.id_usuario, u.nombre, u.correo, u.rol, c.nombre AS corredora, u.activo
FROM usuario u LEFT JOIN corredora c USING (id_corredora)
ORDER BY u.id_usuario;

\echo '== 2) Calificaciones con fuente, suma de montos y suma de factores 8 a 19 =='
SELECT k.id_calificacion, c.nombre AS corredora, k.ejercicio, k.mercado, k.instrumento,
       k.secuencia, k.origen AS fuente, COALESCE(k.modificado_en, k.creado_en) AS ultima_fecha,
       (SELECT SUM(m.monto)  FROM monto_calificacion  m
         WHERE m.id_calificacion = k.id_calificacion AND m.numero_columna BETWEEN 8 AND 19) AS suma_montos_8_19,
       (SELECT SUM(f.valor)  FROM factor_calificacion f
         WHERE f.id_calificacion = k.id_calificacion AND f.numero_factor  BETWEEN 8 AND 19) AS suma_factores_8_19
FROM calificacion k JOIN corredora c USING (id_corredora)
ORDER BY k.id_calificacion;

\echo '== 3) Montos y factores de una calificacion (cambia el 1 por el id) =='
SELECT n.numero AS columna, m.monto, f.valor AS factor
FROM generate_series(8, 37) AS n (numero)
LEFT JOIN monto_calificacion  m ON m.numero_columna = n.numero AND m.id_calificacion = 1
LEFT JOIN factor_calificacion f ON f.numero_factor  = n.numero AND f.id_calificacion = 1
WHERE m.monto IS NOT NULL OR f.valor IS NOT NULL
ORDER BY n.numero;

\echo '== 4) Calificaciones cuya suma de factores 8 a 19 supera 1 (debe salir vacio) =='
SELECT f.id_calificacion, SUM(f.valor) AS suma
FROM factor_calificacion f WHERE f.numero_factor BETWEEN 8 AND 19
GROUP BY f.id_calificacion HAVING SUM(f.valor) > 1;

\echo '== 5) Registro de operaciones (ultimas 20) =='
SELECT l.fecha_hora, u.correo AS usuario, l.accion, l.tabla_afectada, l.id_registro, l.origen
FROM log_operacion l JOIN usuario u USING (id_usuario)
ORDER BY l.fecha_hora DESC LIMIT 20;

\echo '== 6) Cargas de archivos CSV (aceptadas y rechazadas) =='
SELECT a.id_carga, a.creado_en, u.correo AS usuario, a.nombre_archivo, a.estado,
       a.total_filas, a.filas_invalidas, a.detalle_error
FROM carga_archivo a JOIN usuario u USING (id_usuario)
ORDER BY a.id_carga DESC;

\echo '== 7) Conteo de calificaciones por corredora y fuente =='
SELECT c.nombre AS corredora, k.origen AS fuente, COUNT(*) AS cantidad
FROM calificacion k JOIN corredora c USING (id_corredora)
GROUP BY c.nombre, k.origen ORDER BY c.nombre, k.origen;
