"""Aplicacion web del mantenedor de calificaciones (tareas 4 y 5).

Flujo ideal: login -> mantenedor (buscar) -> ingresar calificacion -> montos ->
Calcular -> factores editables -> Grabar -> la grilla muestra la fila con su fuente.
Reglas de permisos: solo el corredor crea, modifica y elimina, y solo lo de su
corredora; analista y administrador consultan todo; lo oficial de Bolsa no se toca.
"""
import csv
import io
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps
import hashlib
import hmac
import json
import os
import re
import secrets
import time

from flask import (
    Flask,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
import psycopg
from psycopg.errors import UniqueViolation

import calculo
from seguridad import (
    AccesoDenegado,
    CuentaBloqueada,
    ErrorValidacion as ErrorValidacionSeguridad,
    SesionUsuario,
    autenticar,
)


COLUMNAS = range(8, 38)
COLUMNAS_CALCULADAS = range(8, 34)      # el HDU da formula hasta la 33
FACTORES_MANUALES = range(34, 38)       # sin formula en el HDU: se ingresan a mano
SUMA_DESDE, SUMA_HASTA = calculo.RANGO_SUMA
SECUENCIA_MINIMA = 10_001               # el flujo ideal pide secuencia mayor que 10.000
MAXIMO_MONTO = Decimal("9999999999999999.99")
ORIGENES = {"manual": "Manual", "carga_masiva": "Carga masiva", "bolsa": "Bolsa"}
CLAVES_REGISTRO = (
    "id_calificacion",
    "id_corredora",
    "ejercicio",
    "mercado",
    "instrumento",
    "fecha",
    "secuencia",
    "numero_dividendo",
    "tipo_sociedad",
    "valor_historico",
    "origen",
    "creado_en",
    "modificado_en",
    "nombre_corredora",
    "es_bolsa",
)
CAMPOS_EDICION = (
    "ejercicio", "mercado", "instrumento", "fecha", "secuencia",
    "numero_dividendo", "tipo_sociedad", "valor_historico",
)


class ErrorFlujo(ValueError):
    """Entrada del flujo no valida: se muestra el mensaje y no se guarda nada."""


def formato_monto(valor):
    """368745318 -> '368.745.318' (formato chileno; muestra decimales solo si existen)."""
    numero = Decimal(str(valor)).quantize(Decimal("0.01"))
    entero, _, decimales = f"{numero:,.2f}".partition(".")
    entero = entero.replace(",", ".")
    return entero if decimales == "00" else f"{entero},{decimales}"


def formato_factor(valor):
    """Decimal('0.52277431') -> '0,52277431' (siempre 8 decimales)."""
    return f"{Decimal(str(valor)):.8f}".replace(".", ",")


def formato_fecha_hora(valor):
    return valor.strftime("%d-%m-%Y %H:%M") if isinstance(valor, datetime) else ""


def create_app(test_config=None):
    config = test_config or {}
    secret_key = config.get("SECRET_KEY") or os.environ.get("FLASK_SECRET_KEY")
    if not secret_key:
        raise RuntimeError("Define la variable FLASK_SECRET_KEY antes de iniciar la app")
    if not (
        config.get("DB_CONNECT")
        or config.get("DATABASE_URL")
        or os.environ.get("DATABASE_URL")
    ):
        raise RuntimeError("Define DATABASE_URL antes de iniciar la app")

    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=secret_key,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        # la sesion se cierra sola tras este tiempo sin actividad
        MINUTOS_INACTIVIDAD=int(os.environ.get("MINUTOS_INACTIVIDAD", "15")),
        MAX_CONTENT_LENGTH=1024 * 1024,
    )
    app.config.update(config)
    app.jinja_env.filters["monto"] = formato_monto
    app.jinja_env.filters["factor"] = formato_factor
    app.jinja_env.filters["fecha_hora"] = formato_fecha_hora

    def connect():
        factory = app.config.get("DB_CONNECT")
        if factory is not None:
            return factory()
        dsn = app.config.get("DATABASE_URL") or os.environ.get("DATABASE_URL")
        return psycopg.connect(dsn)

    app.extensions["db_connect"] = connect

    # ------------------------------------------------------------------
    # Seguridad transversal: token CSRF, cabeceras y sesion
    # ------------------------------------------------------------------
    @app.before_request
    def proteger_post():
        if request.method != "POST":
            return None
        token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
        esperado = session.get("_csrf_token", "")
        if not esperado or not token or not hmac.compare_digest(token, esperado):
            abort(400, description="Formulario vencido o token de seguridad inválido.")
        return None

    @app.after_request
    def cabeceras_de_seguridad(respuesta):
        respuesta.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'self'",
        )
        respuesta.headers.setdefault("X-Content-Type-Options", "nosniff")
        respuesta.headers.setdefault("X-Frame-Options", "DENY")
        respuesta.headers.setdefault("Referrer-Policy", "same-origin")
        if respuesta.mimetype == "text/html":
            respuesta.headers["Cache-Control"] = "no-store"
        return respuesta

    @app.context_processor
    def contexto_comun():
        if "_csrf_token" not in session:
            session["_csrf_token"] = secrets.token_urlsafe(32)
        return {
            "csrf_token": session["_csrf_token"],
            "usuario_actual": getattr(g, "usuario", None),
            "origenes": ORIGENES,
            "suma_desde": SUMA_DESDE,
            "suma_hasta": SUMA_HASTA,
        }

    def usuario_actual():
        if hasattr(g, "usuario"):
            return g.usuario
        id_usuario = session.get("id_usuario")
        if not id_usuario:
            g.usuario = None
            return None
        ahora = time.time()
        ultima = session.get("ultima_actividad")
        if ultima is not None and ahora - ultima > app.config["MINUTOS_INACTIVIDAD"] * 60:
            session.clear()
            flash("Tu sesión se cerró por inactividad. Vuelve a ingresar.", "aviso")
            g.usuario = None
            return None
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id_usuario, id_corredora, rol
                    FROM usuario
                    WHERE id_usuario = %s AND activo = TRUE
                    """,
                    (id_usuario,),
                )
                fila = cursor.fetchone()
        if fila is None:
            session.clear()
            g.usuario = None
            return None
        session["ultima_actividad"] = ahora
        g.usuario = SesionUsuario(fila[0], fila[1], fila[2])
        return g.usuario

    def requiere_login(view):
        @wraps(view)
        def protegida(*args, **kwargs):
            usuario = usuario_actual()
            if usuario is None:
                flash("Inicia sesión para continuar.", "aviso")
                return redirect(url_for("login", siguiente=request.path))
            g.usuario = usuario
            return view(*args, **kwargs)

        return protegida

    def solo_corredor(view):
        @wraps(view)
        def protegida(*args, **kwargs):
            if g.usuario.rol != "corredor":
                app.logger.warning(
                    "Acceso denegado: usuario %s (%s) intento %s %s",
                    g.usuario.id_usuario, g.usuario.rol, request.method, request.path,
                )
                abort(403)
            return view(*args, **kwargs)

        return protegida

    # ------------------------------------------------------------------
    # Lectura y validacion de entradas
    # ------------------------------------------------------------------
    def listar_corredoras(conn, usuario):
        consulta = "SELECT id_corredora, nombre, es_bolsa FROM corredora"
        parametros = ()
        if usuario.rol == "corredor":
            consulta += " WHERE id_corredora = %s"
            parametros = (usuario.id_corredora,)
        consulta += " ORDER BY nombre"
        with conn.cursor() as cursor:
            cursor.execute(consulta, parametros)
            filas = cursor.fetchall()
        return [
            {"id_corredora": fila[0], "nombre": fila[1], "es_bolsa": fila[2]}
            for fila in filas
        ]

    def parse_entero(valor, nombre, minimo=None, maximo=None):
        texto = str(valor or "").strip()
        if not re.fullmatch(r"[0-9]+", texto):
            raise ErrorFlujo(f"{nombre}: ingresa un número entero válido.")
        numero = int(texto)
        if (
            (minimo is not None and numero < minimo)
            or (maximo is not None and numero > maximo)
        ):
            raise ErrorFlujo(f"{nombre}: el valor está fuera del rango permitido.")
        return numero

    def parse_decimal(valor, nombre, decimales, maximo):
        try:
            numero = Decimal(str(valor or "").strip())
        except (InvalidOperation, ValueError):
            raise ErrorFlujo(f"{nombre}: ingresa un monto numérico válido.")
        if not numero.is_finite() or numero < 0:
            raise ErrorFlujo(f"{nombre}: debe ser un número positivo o cero.")
        if numero > maximo:
            raise ErrorFlujo(f"{nombre}: excede el máximo permitido.")
        escala = Decimal(1).scaleb(-decimales)
        try:
            redondeado = numero.quantize(escala)
        except InvalidOperation:
            raise ErrorFlujo(f"{nombre}: excede la precisión permitida.")
        if numero != redondeado:
            raise ErrorFlujo(f"{nombre}: admite como máximo {decimales} decimales.")
        return numero

    def leer_campos(form):
        ejercicio = parse_entero(form.get("ejercicio"), "Ejercicio", 1900, 2100)
        mercado = (form.get("mercado") or "").strip().upper()
        if not re.fullmatch(r"[A-Z0-9]{1,3}", mercado):
            raise ErrorFlujo("Mercado debe tener entre 1 y 3 letras o números.")
        instrumento = (form.get("instrumento") or "").strip()
        if not 1 <= len(instrumento) <= 50:
            raise ErrorFlujo("Instrumento debe tener entre 1 y 50 caracteres.")
        try:
            fecha = date.fromisoformat((form.get("fecha") or "").strip())
        except ValueError:
            raise ErrorFlujo("Fecha inválida.")
        secuencia = parse_entero(form.get("secuencia"), "Secuencia", 0, 9_223_372_036_854_775_807)
        if secuencia < SECUENCIA_MINIMA:
            raise ErrorFlujo("Secuencia: debe ser mayor que 10.000.")

        raw_dividendo = (form.get("numero_dividendo") or "").strip()
        dividendo = (
            parse_entero(raw_dividendo, "Número de dividendo", 0, 9_223_372_036_854_775_807)
            if raw_dividendo else None
        )
        tipo_sociedad = (form.get("tipo_sociedad") or "").strip().upper() or None
        if tipo_sociedad not in (None, "A", "C"):
            raise ErrorFlujo("Tipo de sociedad debe ser A o C.")
        raw_historico = (form.get("valor_historico") or "").strip()
        valor_historico = (
            parse_decimal(raw_historico, "Valor histórico", 2, MAXIMO_MONTO)
            if raw_historico else None
        )
        return {
            "ejercicio": ejercicio,
            "mercado": mercado,
            "instrumento": instrumento,
            "fecha": fecha,
            "secuencia": secuencia,
            "numero_dividendo": dividendo,
            "tipo_sociedad": tipo_sociedad,
            "valor_historico": valor_historico,
        }

    def leer_montos(origen):
        montos = {}
        for columna in COLUMNAS:
            crudo = origen.get(f"monto_{columna}", origen.get(str(columna), "0"))
            montos[columna] = parse_decimal(
                crudo or "0", f"Monto columna {columna}", 2, MAXIMO_MONTO
            )
        return montos

    def leer_factores(form):
        factores = {}
        for columna in COLUMNAS:
            texto = (form.get(f"factor_{columna}") or "").strip().replace(",", ".")
            if not texto:
                factores[columna] = None
                continue
            if not re.fullmatch(r"[0-9]+(\.[0-9]+)?", texto):
                raise ErrorFlujo(
                    f"Factor {columna}: ingresa un número entre 0 y 1, por ejemplo 0,52277431."
                )
            factores[columna] = Decimal(texto)
        return factores

    def firmar_montos(montos):
        texto = ";".join(
            f"{columna}={montos[columna].quantize(Decimal('0.01'))}" for columna in COLUMNAS
        )
        return hmac.new(
            app.config["SECRET_KEY"].encode("utf-8"), texto.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    def resumen_sumas(montos_txt, factores_txt):
        try:
            suma_montos = formato_monto(sum(
                (Decimal(montos_txt[c] or "0") for c in range(SUMA_DESDE, SUMA_HASTA + 1)),
                Decimal("0"),
            ))
        except (InvalidOperation, ValueError):
            suma_montos = "—"
        hay_factores = any(factores_txt[c] for c in COLUMNAS_CALCULADAS)
        try:
            total = sum(
                (
                    Decimal(factores_txt[c].replace(",", "."))
                    for c in range(SUMA_DESDE, SUMA_HASTA + 1) if factores_txt[c]
                ),
                Decimal("0"),
            )
            suma_factores = formato_factor(total)
            estado = "vacia" if not hay_factores else ("excede" if total > 1 else "ok")
        except (InvalidOperation, ValueError):
            suma_factores, estado = "—", "vacia"
        return {"suma_montos": suma_montos, "suma_factores": suma_factores, "estado": estado}

    # ------------------------------------------------------------------
    # Acceso a datos
    # ------------------------------------------------------------------
    def consultar_registro(conn, id_calificacion, usuario, bloquear=False, para_editar=False):
        consulta = """
            SELECT c.id_calificacion, c.id_corredora, c.ejercicio, c.mercado,
                   c.instrumento, c.fecha, c.secuencia, c.numero_dividendo,
                   c.tipo_sociedad, c.valor_historico, c.origen, c.creado_en,
                   c.modificado_en, co.nombre, co.es_bolsa
            FROM calificacion c
            JOIN corredora co ON co.id_corredora = c.id_corredora
            WHERE c.id_calificacion = %s
        """
        parametros = [id_calificacion]
        if usuario.rol == "corredor":
            if para_editar or bloquear:
                consulta += " AND c.id_corredora = %s"
            else:
                consulta += " AND (c.id_corredora = %s OR co.es_bolsa)"
            parametros.append(usuario.id_corredora)
        if bloquear:
            consulta += " FOR UPDATE OF c"
        with conn.cursor() as cursor:
            cursor.execute(consulta, tuple(parametros))
            fila = cursor.fetchone()
        if fila is None:
            abort(404)
        return dict(zip(CLAVES_REGISTRO, fila))

    def leer_detalles(conn, id_calificacion):
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT numero_columna, monto
                FROM monto_calificacion
                WHERE id_calificacion = %s
                """,
                (id_calificacion,),
            )
            montos = {fila[0]: fila[1] for fila in cursor.fetchall()}
            cursor.execute(
                """
                SELECT numero_factor, valor
                FROM factor_calificacion
                WHERE id_calificacion = %s
                """,
                (id_calificacion,),
            )
            factores = {fila[0]: fila[1] for fila in cursor.fetchall()}
        return montos, factores

    def guardar_detalles(conn, id_calificacion, montos, factores, reemplazar=False):
        with conn.cursor() as cursor:
            if reemplazar:
                cursor.execute(
                    "DELETE FROM monto_calificacion WHERE id_calificacion = %s",
                    (id_calificacion,),
                )
                cursor.execute(
                    "DELETE FROM factor_calificacion WHERE id_calificacion = %s",
                    (id_calificacion,),
                )
            cursor.executemany(
                """
                INSERT INTO monto_calificacion (id_calificacion, numero_columna, monto)
                VALUES (%s, %s, %s)
                """,
                [
                    (id_calificacion, columna, monto)
                    for columna, monto in montos.items()
                ],
            )
            cursor.executemany(
                """
                INSERT INTO factor_calificacion (id_calificacion, numero_factor, valor)
                VALUES (%s, %s, %s)
                """,
                [
                    (id_calificacion, columna, factor)
                    for columna, factor in factores.items()
                    if factor is not None
                ],
            )

    def _json_valor(valor):
        if isinstance(valor, (date, datetime)):
            return valor.isoformat()
        if isinstance(valor, Decimal):
            return str(valor)
        return valor

    def snapshot(conn, registro):
        montos, factores = leer_detalles(conn, registro["id_calificacion"])
        return {
            clave: _json_valor(valor)
            for clave, valor in registro.items()
            if clave not in ("es_bolsa", "creado_en", "modificado_en")
        } | {
            "montos": {str(k): str(v) for k, v in montos.items()},
            "factores": {str(k): str(v) for k, v in factores.items()},
        }

    def insertar_log(conn, usuario, accion, id_registro, antes=None, despues=None):
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO log_operacion
                    (id_usuario, accion, tabla_afectada, id_registro,
                     datos_antes, datos_despues, origen)
                VALUES (%s, %s, 'calificacion', %s, %s::jsonb, %s::jsonb, 'manual')
                """,
                (
                    usuario.id_usuario,
                    accion,
                    id_registro,
                    json.dumps(antes) if antes is not None else None,
                    json.dumps(despues) if despues is not None else None,
                ),
            )

    def puede_editar(usuario, registro):
        return (
            usuario.rol == "corredor"
            and registro["id_corredora"] == usuario.id_corredora
            and not registro["es_bolsa"]
        )

    # ------------------------------------------------------------------
    # Inicio y cierre de sesion
    # ------------------------------------------------------------------
    @app.get("/")
    def inicio():
        return redirect(url_for("calificaciones"))

    @app.route("/login", methods=("GET", "POST"))
    def login():
        if request.method == "GET":
            return render_template("login.html")
        correo = request.form.get("correo", "")
        try:
            with connect() as conn:
                usuario = autenticar(conn, correo, request.form.get("clave", ""))
        except CuentaBloqueada as error:
            app.logger.warning("Inicio de sesion sobre cuenta bloqueada: %r", correo[:150])
            flash(str(error), "error")
            return render_template("login.html"), 429
        except ErrorValidacionSeguridad as error:
            flash(str(error), "error")
            return render_template("login.html"), 400
        if usuario is None:
            app.logger.warning("Inicio de sesion fallido para %r", correo[:150])
            flash("Correo o contraseña incorrectos.", "error")
            return render_template("login.html"), 401
        session.clear()
        session["id_usuario"] = usuario.id_usuario
        session["ultima_actividad"] = time.time()
        session.permanent = True
        return redirect(url_for("calificaciones"))

    @app.post("/logout")
    @requiere_login
    def logout():
        session.clear()
        flash("Sesión cerrada.", "ok")
        return redirect(url_for("login"))

    # ------------------------------------------------------------------
    # Calculo
    # ------------------------------------------------------------------
    @app.post("/api/calculo")
    @requiere_login
    def api_calculo():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not isinstance(payload.get("montos"), dict):
            return jsonify(error="Envío de cálculo inválido."), 400
        try:
            montos = leer_montos(payload["montos"])
            factores = calculo.calcular_factores(montos)
            manuales = payload.get("factores_manuales", {})
            if not isinstance(manuales, dict):
                raise ErrorFlujo("Factores manuales inválidos.")
            for columna in FACTORES_MANUALES:
                raw = str(manuales.get(str(columna), "")).strip().replace(",", ".")
                factores[columna] = raw or None
            suma_factores = calculo.validar_factores(factores)
        except (ErrorFlujo, calculo.ErrorValidacion) as error:
            return jsonify(error=str(error)), 400
        suma_montos = sum(
            (montos[c] for c in range(SUMA_DESDE, SUMA_HASTA + 1)), Decimal("0")
        )
        return jsonify(
            suma_montos=f"{suma_montos:.2f}",
            suma_factores=f"{suma_factores:.8f}",
            factores={
                str(columna): f"{Decimal(str(valor)):.8f}" if valor is not None else ""
                for columna, valor in factores.items()
            },
            firma=firmar_montos(montos),
        )

    # ------------------------------------------------------------------
    # Mantenedor: busqueda y grilla
    # ------------------------------------------------------------------
    @app.get("/calificaciones")
    @requiere_login
    def calificaciones():
        usuario = g.usuario
        busqueda = (request.args.get("q") or "").strip()
        if len(busqueda) > 50:
            abort(400, description="La búsqueda admite hasta 50 caracteres.")
        ejercicio_raw = (request.args.get("ejercicio") or "").strip()
        ejercicio = (
            parse_entero(ejercicio_raw, "Ejercicio", 1900, 2100)
            if ejercicio_raw else None
        )
        corredora_raw = (request.args.get("id_corredora") or "").strip()
        id_corredora = (
            parse_entero(corredora_raw, "Corredora", 1)
            if corredora_raw and usuario.rol != "corredor" else None
        )
        condiciones = []
        parametros = []
        if usuario.rol == "corredor":
            condiciones.append(
                """(c.id_corredora = %s OR (co.es_bolsa AND NOT EXISTS (
                        SELECT 1 FROM calificacion propia
                        WHERE propia.id_corredora = %s
                          AND propia.ejercicio = c.ejercicio AND propia.mercado = c.mercado
                          AND propia.instrumento = c.instrumento
                          AND propia.secuencia = c.secuencia)))"""
            )
            parametros += [usuario.id_corredora, usuario.id_corredora]
        elif id_corredora is not None:
            condiciones.append("c.id_corredora = %s")
            parametros.append(id_corredora)
        if busqueda:
            patron = busqueda.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            condiciones.append("c.instrumento ILIKE %s")
            parametros.append(f"%{patron}%")
        if ejercicio is not None:
            condiciones.append("c.ejercicio = %s")
            parametros.append(ejercicio)
        where = " WHERE " + " AND ".join(condiciones) if condiciones else ""
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT c.id_calificacion, co.nombre, co.es_bolsa, c.ejercicio,
                           c.mercado, c.instrumento, c.fecha, c.secuencia,
                           COALESCE((
                               SELECT SUM(m.monto) FROM monto_calificacion m
                               WHERE m.id_calificacion = c.id_calificacion
                                 AND m.numero_columna BETWEEN {SUMA_DESDE} AND {SUMA_HASTA}
                           ), 0),
                           COALESCE((
                               SELECT SUM(f.valor) FROM factor_calificacion f
                               WHERE f.id_calificacion = c.id_calificacion
                                 AND f.numero_factor BETWEEN {SUMA_DESDE} AND {SUMA_HASTA}
                           ), 0),
                           c.origen, COALESCE(c.modificado_en, c.creado_en),
                           c.modificado_en IS NOT NULL, c.id_corredora,
                           NOT co.es_bolsa AND EXISTS (
                               SELECT 1 FROM calificacion oficial
                               JOIN corredora cb ON cb.id_corredora = oficial.id_corredora
                               WHERE cb.es_bolsa
                                 AND oficial.ejercicio = c.ejercicio AND oficial.mercado = c.mercado
                                 AND oficial.instrumento = c.instrumento
                                 AND oficial.secuencia = c.secuencia)
                    FROM calificacion c
                    JOIN corredora co ON co.id_corredora = c.id_corredora
                    {where}
                    ORDER BY c.ejercicio DESC, c.instrumento, c.secuencia
                    LIMIT 200
                    """,
                    tuple(parametros),
                )
                filas = cursor.fetchall()
            corredoras = listar_corredoras(conn, usuario)
        registros = [
            {
                "id": fila[0],
                "corredora": fila[1],
                "es_bolsa": fila[2],
                "ejercicio": fila[3],
                "mercado": fila[4],
                "instrumento": fila[5],
                "fecha": fila[6],
                "secuencia": fila[7],
                "suma_montos": fila[8],
                "suma_factores": fila[9],
                "origen": fila[10],
                "fecha_cambio": fila[11],
                "modificada": fila[12],
                "editable": (
                    usuario.rol == "corredor"
                    and fila[13] == usuario.id_corredora
                    and not fila[2]
                ),
                "predomina": fila[14],
            }
            for fila in filas
        ]
        return render_template(
            "calificaciones.html",
            registros=registros,
            corredoras=corredoras,
            filtros={
                "q": busqueda,
                "ejercicio": ejercicio_raw,
                "id_corredora": corredora_raw,
            },
        )

    @app.get("/calificaciones/<int:id_calificacion>")
    @requiere_login
    def ver_calificacion(id_calificacion):
        usuario = g.usuario
        with connect() as conn:
            registro = consultar_registro(conn, id_calificacion, usuario)
            montos, factores = leer_detalles(conn, id_calificacion)
        suma_montos = sum(
            (montos.get(c, Decimal("0")) for c in range(SUMA_DESDE, SUMA_HASTA + 1)),
            Decimal("0"),
        )
        suma_factores = sum(
            (factores.get(c, Decimal("0")) for c in range(SUMA_DESDE, SUMA_HASTA + 1)),
            Decimal("0"),
        )
        return render_template(
            "detalle.html",
            registro=registro,
            montos=montos,
            factores=factores,
            suma_montos=suma_montos,
            suma_factores=suma_factores,
            editable=puede_editar(usuario, registro),
        )

    # ------------------------------------------------------------------
    # NUEVA FUNCIONALIDAD PUNTO 6: Carga CSV con previsualización y validación
    # ------------------------------------------------------------------
    @app.route("/calificaciones/cargar-csv", methods=("GET", "POST"))
    @requiere_login
    @solo_corredor
    def cargar_csv():
        usuario = g.usuario
        if request.method == "GET":
            return render_template("cargar_csv.html", previsualizacion=None)

        accion = request.form.get("accion", "previsualizar")
        archivo = request.files.get("archivo_csv")

        if not archivo or not archivo.filename.endswith(".csv"):
            flash("Error: Sube un archivo CSV válido.", "error")
            return redirect(url_for("cargar_csv"))

        try:
            contenido = archivo.stream.read().decode("UTF-8")
            stream = io.StringIO(contenido, newline=None)
            csv_reader = csv.reader(stream)

            filas_datos = []
            for i, fila in enumerate(csv_reader, start=1):
                if not fila or all(not col.strip() for col in fila):
                    continue
                # Regla de validación de filas: mínimo de columnas requeridas
                if len(fila) < 5:
                    raise ErrorFlujo(f"Línea {i}: Fila inválida o incompleta (faltan columnas obligatorias).")
                filas_datos.append({
                    "linea": i,
                    "ejercicio": fila[0].strip(),
                    "mercado": fila[1].strip(),
                    "instrumento": fila[2].strip(),
                    "fecha": fila[3].strip(),
                    "secuencia": fila[4].strip(),
                })

            if accion == "previsualizar":
                return render_template("cargar_csv.html", previsualizacion=filas_datos, contenido_csv=contenido)

            elif accion == "confirmar":
                with connect() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute(
                            "SELECT es_bolsa FROM corredora WHERE id_corredora = %s",
                            (usuario.id_corredora,),
                        )
                        corredora = cursor.fetchone()
                        if corredora is None or corredora[0]:
                            raise ErrorFlujo("Tu corredora no está autorizada para carga masiva.")

                        for item in filas_datos:
                            ejercicio = parse_entero(item["ejercicio"], f"Línea {item['linea']} - Ejercicio", 1900, 2100)
                            mercado = item["mercado"].upper()
                            instrumento = item["instrumento"]
                            fecha = date.fromisoformat(item["fecha"])
                            secuencia = parse_entero(item["secuencia"], f"Línea {item['linea']} - Secuencia", SECUENCIA_MINIMA, 9_223_372_036_854_775_807)

                            cursor.execute(
                                """
                                INSERT INTO calificacion
                                    (id_corredora, ejercicio, mercado, instrumento, fecha,
                                     secuencia, origen, creado_por)
                                VALUES (%s, %s, %s, %s, %s, %s, 'carga_masiva', %s)
                                RETURNING id_calificacion
                                """,
                                (
                                    usuario.id_corredora,
                                    ejercicio,
                                    mercado,
                                    instrumento,
                                    fecha,
                                    secuencia,
                                    usuario.id_usuario,
                                ),
                            )
                flash(f"Carga masiva completada correctamente. {len(filas_datos)} registros importados.", "ok")
                return redirect(url_for("calificaciones"))

        except (ErrorFlujo, ValueError, Exception) as error:
            flash(f"Error al procesar el archivo CSV (Fila inválida o formato incorrecto): {str(error)}", "error")
            return render_template("cargar_csv.html", previsualizacion=None), 400

    # ------------------------------------------------------------------
    # NUEVA FUNCIONALIDAD PUNTO 6/7: Consulta del log de solo lectura
    # ------------------------------------------------------------------
    @app.get("/log")
    @requiere_login
    def ver_log():
        usuario = g.usuario
        # Solo analistas y administradores tienen acceso de consulta al log
        if usuario.rol not in ("analista", "administrador"):
            abort(403, description="No tienes permiso para consultar el log de operaciones.")

        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT l.id_log, u.correo, l.accion, l.tabla_afectada, 
                           l.id_registro, l.fecha_hora, l.origen, l.datos_antes, l.datos_despues
                    FROM log_operacion l
                    LEFT JOIN usuario u ON u.id_usuario = l.id_usuario
                    ORDER BY l.fecha_hora DESC
                    LIMIT 200
                    """
                )
                filas = cursor.fetchall()

        logs = [
            {
                "id_log": fila[0],
                "correo": fila[1],
                "accion": fila[2],
                "tabla": fila[3],
                "id_registro": fila[4],
                "fecha_hora": fila[5],
                "origen": fila[6],
                "datos_antes": fila[7],
                "datos_despues": fila[8],
            }
            for fila in filas
        ]
        return render_template("log.html", logs=logs)

    # ------------------------------------------------------------------
    # Ingreso y modificacion
    # ------------------------------------------------------------------
    def render_formulario(titulo, usuario, id_calificacion=None, campos=None, montos=None,
                          factores=None, firma="", mensaje="", codigo_estado=200):
        form = request.form
        with connect() as conn:
            corredoras = listar_corredoras(conn, usuario)
        campos_vista = {}
        for nombre in CAMPOS_EDICION:
            valor = campos[nombre] if campos is not None else form.get(nombre, "")
            if hasattr(valor, "isoformat"):
                valor = valor.isoformat()
            campos_vista[nombre] = "" if valor is None else str(valor)
        montos_vista = {
            columna: str(
                montos[columna] if montos is not None and columna in montos
                else (form.get(f"monto_{columna}", "0") or "0")
            )
            for columna in COLUMNAS
        }
        factores_vista = {}
        for columna in COLUMNAS:
            if factores is not None:
                valor = factores.get(columna)
                factores_vista[columna] = "" if valor is None else (
                    formato_factor(valor) if isinstance(valor, Decimal) else str(valor)
                )
            else:
                factores_vista[columna] = (form.get(f"factor_{columna}") or "").strip()
        estado = {
            "campos": campos_vista,
            "montos": montos_vista,
            "factores": factores_vista,
            "firma": firma or form.get("firma_montos", ""),
            "mensaje": mensaje,
            "nombre_corredora": next(
                (c["nombre"] for c in corredoras
                 if c["id_corredora"] == usuario.id_corredora), "",
            ),
        }
        estado.update(resumen_sumas(montos_vista, factores_vista))
        return (
            render_template(
                "formulario.html",
                titulo=titulo,
                estado=estado,
                id_calificacion=id_calificacion,
            ),
            codigo_estado,
        )

    def calcular_desde_formulario(titulo, usuario, id_calificacion=None):
        montos = leer_montos(request.form)
        calculados = calculo.calcular_factores(montos)
        factores = {c: calculados[c] for c in COLUMNAS_CALCULADAS}
        for columna in FACTORES_MANUALES:
            factores[columna] = (request.form.get(f"factor_{columna}") or "").strip() or None
        return render_formulario(
            titulo, usuario, id_calificacion, montos=montos, factores=factores,
            firma=firmar_montos(montos),
            mensaje="Factores calculados. Puedes editarlos antes de grabar.",
        )

    def validar_para_grabar():
        campos = leer_campos(request.form)
        montos = leer_montos(request.form)
        factores = leer_factores(request.form)
        if all(factores[c] is None for c in COLUMNAS_CALCULADAS):
            raise ErrorFlujo("Presiona Calcular para obtener los factores antes de grabar.")
        firma = request.form.get("firma_montos", "")
        if not hmac.compare_digest(firma, firmar_montos(montos)):
            raise ErrorFlujo(
                "Los montos cambiaron después del cálculo. Presiona Calcular antes de grabar."
            )
        calculo.validar_factores(factores)
        return campos, montos, factores

    @app.route("/calificaciones/nueva", methods=("GET", "POST"))
    @requiere_login
    @solo_corredor
    def nueva_calificacion():
        usuario = g.usuario
        titulo = "Ingresar calificación"
        if request.method == "GET":
            return render_formulario(
                titulo, usuario, mensaje="Ingresa los montos y presiona Calcular."
            )
        try:
            if request.form.get("accion") == "calcular":
                return calcular_desde_formulario(titulo, usuario)
            campos, montos, factores = validar_para_grabar()
            with connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT es_bolsa FROM corredora WHERE id_corredora = %s",
                        (usuario.id_corredora,),
                    )
                    corredora = cursor.fetchone()
                    if corredora is None:
                        raise ErrorFlujo("Tu cuenta no tiene una corredora asignada.")
                    origen = "bolsa" if corredora[0] else "manual"
                    cursor.execute(
                        """
                        INSERT INTO calificacion
                            (id_corredora, ejercicio, mercado, instrumento, fecha,
                             secuencia, numero_dividendo, tipo_sociedad,
                             valor_historico, origen, creado_por)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id_calificacion
                        """,
                        (
                            usuario.id_corredora,
                            campos["ejercicio"],
                            campos["mercado"],
                            campos["instrumento"],
                            campos["fecha"],
                            campos["secuencia"],
                            campos["numero_dividendo"],
                            campos["tipo_sociedad"],
                            campos["valor_historico"],
                            origen,
                            usuario.id_usuario,
                        ),
                    )
                    id_calificacion = cursor.fetchone()[0]
                guardar_detalles(conn, id_calificacion, montos, factores)
                registro = consultar_registro(conn, id_calificacion, usuario)
                insertar_log(conn, usuario, "crear", id_calificacion, despues=snapshot(conn, registro))
        except (ErrorFlujo, calculo.ErrorValidacion) as error:
            flash(str(error), "error")
            return render_formulario(titulo, usuario, codigo_estado=400)
        except UniqueViolation:
            flash("Ya existe una calificación con ese ejercicio, mercado, instrumento y secuencia.", "error")
            return render_formulario(titulo, usuario, codigo_estado=409)
        flash("Calificación grabada correctamente.", "ok")
        return redirect(url_for("calificaciones"))

    @app.route("/calificaciones/<int:id_calificacion>/editar", methods=("GET", "POST"))
    @requiere_login
    @solo_corredor
    def editar_calificacion(id_calificacion):
        usuario = g.usuario
        titulo = "Modificar calificación"
        with connect() as conn:
            registro = consultar_registro(conn, id_calificacion, usuario, para_editar=True)
            montos_guardados, factores_guardados = leer_detalles(conn, id_calificacion)
        if registro["es_bolsa"]:
            flash("Los datos oficiales de Bolsa no se pueden modificar.", "error")
            return redirect(url_for("calificaciones"))
        if request.method == "GET":
            montos = {c: montos_guardados.get(c, Decimal("0")) for c in COLUMNAS}
            return render_formulario(
                titulo, usuario, id_calificacion,
                campos={clave: registro[clave] for clave in CAMPOS_EDICION},
                montos=montos, factores=factores_guardados, firma=firmar_montos(montos),
                mensaje="Si cambias los montos, presiona Calcular antes de grabar.",
            )
        try:
            if request.form.get("accion") == "calcular":
                return calcular_desde_formulario(titulo, usuario, id_calificacion)
            campos, montos, factores = validar_para_grabar()
            with connect() as conn:
                registro_actual = consultar_registro(
                    conn, id_calificacion, usuario, bloquear=True
                )
                if registro_actual["es_bolsa"]:
                    raise AccesoDenegado("Los datos oficiales de Bolsa no se pueden modificar.")
                antes = snapshot(conn, registro_actual)
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE calificacion
                        SET ejercicio = %s, mercado = %s, instrumento = %s, fecha = %s,
                            secuencia = %s, numero_dividendo = %s, tipo_sociedad = %s,
                            valor_historico = %s, modificado_en = now()
                        WHERE id_calificacion = %s
                        """,
                        (
                            campos["ejercicio"], campos["mercado"], campos["instrumento"],
                            campos["fecha"], campos["secuencia"], campos["numero_dividendo"],
                            campos["tipo_sociedad"], campos["valor_historico"], id_calificacion,
                        ),
                    )
                guardar_detalles(conn, id_calificacion, montos, factores, reemplazar=True)
                despues = snapshot(conn, consultar_registro(conn, id_calificacion, usuario))
                insertar_log(conn, usuario, "modificar", id_calificacion, antes, despues)
        except (ErrorFlujo, calculo.ErrorValidacion) as error:
            flash(str(error), "error")
            return render_formulario(titulo, usuario, id_calificacion, codigo_estado=400)
        except AccesoDenegado as error:
            flash(str(error), "error")
            return redirect(url_for("calificaciones"))
        except UniqueViolation:
            flash("La modificación genera una calificación duplicada.", "error")
            return render_formulario(titulo, usuario, id_calificacion, codigo_estado=409)
        flash("Calificación modificada correctamente.", "ok")
        return redirect(url_for("calificaciones"))

    @app.route("/calificaciones/<int:id_calificacion>/eliminar", methods=("GET", "POST"))
    @requiere_login
    @solo_corredor
    def eliminar_calificacion(id_calificacion):
        usuario = g.usuario
        if request.method == "GET":
            with connect() as conn:
                registro = consultar_registro(conn, id_calificacion, usuario, para_editar=True)
            if registro["es_bolsa"]:
                flash("Los datos oficiales de Bolsa no se pueden eliminar.", "error")
                return redirect(url_for("calificaciones"))
            return render_template("confirmar_eliminar.html", registro=registro)
        try:
            with connect() as conn:
                registro = consultar_registro(conn, id_calificacion, usuario, bloquear=True)
                if registro["es_bolsa"]:
                    raise AccesoDenegado("Los datos oficiales de Bolsa no se pueden eliminar.")
                antes = snapshot(conn, registro)
                with conn.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM calificacion WHERE id_calificacion = %s",
                        (id_calificacion,),
                    )
                insertar_log(conn, usuario, "eliminar", id_calificacion, antes=antes)
        except AccesoDenegado as error:
            flash(str(error), "error")
            return redirect(url_for("calificaciones"))
        flash("Calificación eliminada.", "ok")
        return redirect(url_for("calificaciones"))

    # ------------------------------------------------------------------
    # Errores
    # ------------------------------------------------------------------
    def pagina_error(titulo, mensaje, codigo):
        return render_template("error.html", titulo=titulo, mensaje=mensaje), codigo

    @app.errorhandler(400)
    def error_peticion(error):
        return pagina_error(
            "Solicitud no válida",
            getattr(error, "description", "Revisa los datos e intenta nuevamente."),
            400,
        )

    @app.errorhandler(403)
    def error_permiso(error):
        usuario_actual()
        return pagina_error(
            "Sin permiso", "Tu perfil no tiene permiso para realizar esta operación.", 403
        )

    @app.errorhandler(404)
    def error_no_encontrado(error):
        usuario_actual()
        return pagina_error(
            "No encontrado", "El registro no existe o no pertenece a tu corredora.", 404
        )

    @app.errorhandler(ErrorFlujo)
    def error_flujo(error):
        return pagina_error("Revisa los filtros", str(error), 400)

    @app.errorhandler(500)
    def error_interno(error):
        return pagina_error(
            "Error del sistema",
            "No se pudo completar la operación. Intenta nuevamente o avisa al administrador.",
            500,
        )

    return app


if __name__ == "__main__":
    create_app().run(debug=os.environ.get("FLASK_DEBUG") == "1")