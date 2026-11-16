-- Mantenedor de Calificaciones Tributarias (NUAM) - Esquema para PostgreSQL 16
-- Tarea 2: base de datos del flujo ideal (usuarios, calificaciones, montos, factores, cargas y log).
-- Ejecutar: psql -U postgres -d calificaciones -f schema.sql

BEGIN;

-- 1) Corredoras. La Bolsa es una corredora especial (es_bolsa): sus datos son oficiales.
CREATE TABLE corredora (
    id_corredora SERIAL PRIMARY KEY,
    nombre       VARCHAR(100) NOT NULL UNIQUE,
    es_bolsa     BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE UNIQUE INDEX uq_corredora_unica_bolsa ON corredora (es_bolsa) WHERE es_bolsa;

-- 2) Usuarios. La clave se guarda con hash (lo genera la aplicación, nunca texto plano).
CREATE TABLE usuario (
    id_usuario   SERIAL PRIMARY KEY,
    id_corredora INT REFERENCES corredora (id_corredora),
    nombre       VARCHAR(100) NOT NULL,
    correo       VARCHAR(150) NOT NULL UNIQUE,
    clave_hash   TEXT NOT NULL,
    rol          VARCHAR(15) NOT NULL CHECK (rol IN ('corredor', 'analista', 'administrador')),
    activo       BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT ck_corredor_con_corredora CHECK (rol <> 'corredor' OR id_corredora IS NOT NULL)
);

-- 3) Cargas de archivo CSV. Un archivo con filas inválidas se rechaza completo.
CREATE TABLE carga_archivo (
    id_carga        BIGSERIAL PRIMARY KEY,
    id_usuario      INT NOT NULL REFERENCES usuario (id_usuario),
    nombre_archivo  VARCHAR(200) NOT NULL,
    tipo            VARCHAR(10) NOT NULL CHECK (tipo IN ('montos', 'factores')),
    estado          VARCHAR(12) NOT NULL CHECK (estado IN ('rechazado', 'confirmado')),
    total_filas     INT NOT NULL CHECK (total_filas >= 0),
    filas_invalidas INT NOT NULL DEFAULT 0 CHECK (filas_invalidas >= 0),
    detalle_error   TEXT,
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 4) Calificación. Campos del archivo de carga del HDU (hoja 3.1).
--    Llave de negocio declarada por el grupo: corredora + ejercicio + mercado + instrumento + secuencia.
CREATE TABLE calificacion (
    id_calificacion  BIGSERIAL PRIMARY KEY,
    id_corredora     INT NOT NULL REFERENCES corredora (id_corredora),
    ejercicio        SMALLINT NOT NULL CHECK (ejercicio BETWEEN 1900 AND 2100),
    mercado          VARCHAR(3) NOT NULL,
    instrumento      VARCHAR(50) NOT NULL,
    fecha            DATE NOT NULL,
    secuencia        BIGINT NOT NULL,
    numero_dividendo BIGINT,
    tipo_sociedad    CHAR(1) CHECK (tipo_sociedad IN ('A', 'C')),
    valor_historico  NUMERIC(18, 2) CHECK (valor_historico >= 0),
    origen           VARCHAR(12) NOT NULL DEFAULT 'manual' CHECK (origen IN ('manual', 'carga_masiva', 'bolsa')),
    id_carga         BIGINT REFERENCES carga_archivo (id_carga),
    creado_por       INT REFERENCES usuario (id_usuario),
    creado_en        TIMESTAMPTZ NOT NULL DEFAULT now(),
    modificado_en    TIMESTAMPTZ,
    CONSTRAINT uq_calificacion UNIQUE (id_corredora, ejercicio, mercado, instrumento, secuencia)
);
-- búsqueda por instrumento dentro de una corredora
CREATE INDEX ix_calificacion_busqueda ON calificacion (id_corredora, instrumento);
CREATE INDEX ix_calificacion_carga ON calificacion (id_carga);

-- 5) Detalle de montos y de factores: una fila por columna (8 a 37), en vez de 60 columnas.
--    Los factores usan NUMERIC(9,8): 1 entero y 8 decimales exactos (nunca float).
CREATE TABLE monto_calificacion (
    id_calificacion BIGINT NOT NULL REFERENCES calificacion (id_calificacion) ON DELETE CASCADE,
    numero_columna  SMALLINT NOT NULL CHECK (numero_columna BETWEEN 8 AND 37),
    monto           NUMERIC(18, 2) NOT NULL CHECK (monto >= 0),
    PRIMARY KEY (id_calificacion, numero_columna)
);

CREATE TABLE factor_calificacion (
    id_calificacion BIGINT NOT NULL REFERENCES calificacion (id_calificacion) ON DELETE CASCADE,
    numero_factor   SMALLINT NOT NULL CHECK (numero_factor BETWEEN 8 AND 37),
    valor           NUMERIC(9, 8) NOT NULL CHECK (valor >= 0 AND valor <= 1),
    PRIMARY KEY (id_calificacion, numero_factor)
);

-- 6) Registro de operaciones (log): solo se agrega, nunca se edita ni se borra.
CREATE TABLE log_operacion (
    id_log         BIGSERIAL PRIMARY KEY,
    fecha_hora     TIMESTAMPTZ NOT NULL DEFAULT now(),
    id_usuario     INT NOT NULL REFERENCES usuario (id_usuario),
    accion         VARCHAR(15) NOT NULL CHECK (accion IN ('crear', 'modificar', 'eliminar', 'carga_masiva')),
    tabla_afectada VARCHAR(40) NOT NULL,
    id_registro    BIGINT,
    datos_antes    JSONB,
    datos_despues  JSONB,
    origen         VARCHAR(12) NOT NULL CHECK (origen IN ('manual', 'carga_masiva'))
);
CREATE INDEX ix_log_fecha ON log_operacion (fecha_hora DESC);
CREATE INDEX ix_log_usuario ON log_operacion (id_usuario);

-- ---------------------------------------------------------------------------
-- Reglas dentro de la base de datos
-- ---------------------------------------------------------------------------

-- A) Lo oficial de la Bolsa no se modifica ni se elimina (calificación del corredor != calificación de Bolsa).
CREATE FUNCTION bloquear_calificacion_oficial() RETURNS trigger AS $$
DECLARE
    v_es_bolsa BOOLEAN;
BEGIN
    SELECT co.es_bolsa INTO v_es_bolsa
    FROM calificacion c JOIN corredora co ON co.id_corredora = c.id_corredora
    WHERE c.id_calificacion = OLD.id_calificacion;
    IF v_es_bolsa THEN
        RAISE EXCEPTION 'Los datos oficiales de la Bolsa no se pueden modificar ni eliminar'
            USING ERRCODE = '42501';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_oficial_calificacion BEFORE UPDATE OR DELETE ON calificacion
    FOR EACH ROW EXECUTE FUNCTION bloquear_calificacion_oficial();
CREATE TRIGGER trg_oficial_monto BEFORE UPDATE OR DELETE ON monto_calificacion
    FOR EACH ROW EXECUTE FUNCTION bloquear_calificacion_oficial();
CREATE TRIGGER trg_oficial_factor BEFORE UPDATE OR DELETE ON factor_calificacion
    FOR EACH ROW EXECUTE FUNCTION bloquear_calificacion_oficial();

-- A2) El origen 'bolsa' solo vale para la corredora Bolsa y una calificación no cambia de corredora.
CREATE FUNCTION validar_origen_bolsa() RETURNS trigger AS $$
DECLARE
    v_es_bolsa BOOLEAN;
BEGIN
    SELECT es_bolsa INTO v_es_bolsa FROM corredora WHERE id_corredora = NEW.id_corredora;
    IF (NEW.origen = 'bolsa') <> v_es_bolsa THEN
        RAISE EXCEPTION 'El origen bolsa solo corresponde a la corredora Bolsa'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE' AND NEW.id_corredora <> OLD.id_corredora THEN
        RAISE EXCEPTION 'No se puede cambiar la corredora de una calificación'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_origen_bolsa BEFORE INSERT OR UPDATE ON calificacion
    FOR EACH ROW EXECUTE FUNCTION validar_origen_bolsa();

-- B) La suma de los factores 8 a 19 no puede superar 1 (se revisa al confirmar la transacción).
--    Si se usa 8 a 16, cambiar el 19 por 16.
CREATE FUNCTION validar_suma_factores() RETURNS trigger AS $$
DECLARE
    v_suma NUMERIC;
BEGIN
    SELECT COALESCE(SUM(valor), 0) INTO v_suma
    FROM factor_calificacion
    WHERE id_calificacion = NEW.id_calificacion AND numero_factor BETWEEN 8 AND 19;
    IF v_suma > 1 THEN
        RAISE EXCEPTION 'La suma de los factores 8 a 19 es % y supera 1', v_suma
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER trg_suma_factores AFTER INSERT OR UPDATE ON factor_calificacion
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION validar_suma_factores();

-- C) El log es de solo lectura: nadie puede editarlo, borrarlo ni vaciarlo.
CREATE FUNCTION proteger_log() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'El registro de operaciones es de solo lectura' USING ERRCODE = '42501';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_log_solo_lectura BEFORE UPDATE OR DELETE ON log_operacion
    FOR EACH ROW EXECUTE FUNCTION proteger_log();
CREATE TRIGGER trg_log_sin_vaciar BEFORE TRUNCATE ON log_operacion
    FOR EACH STATEMENT EXECUTE FUNCTION proteger_log();
-- Ojo: el dueño o un superusuario puede desactivar los triggers; la app debería usar un usuario con solo INSERT y SELECT.
REVOKE UPDATE, DELETE, TRUNCATE ON log_operacion FROM PUBLIC;

COMMIT;
