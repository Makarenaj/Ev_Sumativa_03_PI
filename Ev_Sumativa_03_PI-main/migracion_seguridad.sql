-- Solo para bases creadas con el schema.sql anterior (sin las columnas de bloqueo).
-- Agrega el bloqueo de cuenta tras intentos fallidos. Se puede ejecutar más de una vez.
-- Ejecutar: psql -U postgres -d calificaciones -f migracion_seguridad.sql
ALTER TABLE usuario
    ADD COLUMN IF NOT EXISTS intentos_fallidos SMALLINT NOT NULL DEFAULT 0 CHECK (intentos_fallidos >= 0),
    ADD COLUMN IF NOT EXISTS bloqueado_hasta TIMESTAMPTZ;
