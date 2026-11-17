"""Pruebas de integracion contra PostgreSQL real (sin simulacion).

Recorren el flujo ideal y los casos de error, de borde y de seguridad con la
aplicacion conectada a una base de datos de verdad.

Como ejecutarlas (la base de pruebas se BORRA y se vuelve a crear en cada corrida,
por eso su nombre debe terminar en "_test"):

    psql -U postgres -c "CREATE DATABASE calificaciones_test"
    PowerShell:  $env:DATABASE_URL_TEST = "postgresql://postgres:TU_CLAVE@localhost:5432/calificaciones_test"
    python -m pytest -v test_integracion_pg.py

Sin la variable DATABASE_URL_TEST estas pruebas se omiten.
"""
import os
from pathlib import Path
import re

import psycopg
import pytest

from app import create_app
from seguridad import MAX_INTENTOS_FALLIDOS, hash_clave

DSN = os.environ.get("DATABASE_URL_TEST", "")
pytestmark = pytest.mark.skipif(not DSN, reason="Define DATABASE_URL_TEST para probar con PostgreSQL")

CARPETA = Path(__file__).parent
CLAVE = "ClaveDemo2026"
# Ejemplo resuelto de la hoja 3.2 del HDU: la suma de los montos 8 a 19 es 368.745.318
MONTOS_HDU = {8: "192770580", 9: "64161878", 10: "0", 11: "111812860", 25: "71298705", 30: "15837333"}
FACTORES_HDU = {8: "0.52277431", 9: "0.17400052", 10: "0.00000000", 11: "0.30322517",
                25: "0.19335488", 30: "0.04294924"}


def consultar(sql, parametros=()):
    with psycopg.connect(DSN) as conn:
        return conn.execute(sql, parametros).fetchall()


@pytest.fixture(scope="module")
def app():
    nombre_bd = psycopg.conninfo.conninfo_to_dict(DSN).get("dbname", "")
    assert nombre_bd.endswith("_test"), "DATABASE_URL_TEST debe apuntar a una base terminada en _test"
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
        conn.execute((CARPETA / "schema.sql").read_text(encoding="utf-8"))
        conn.execute((CARPETA / "seed_ejemplo_hdu.sql").read_text(encoding="utf-8"))
        conn.execute("INSERT INTO corredora (nombre) VALUES ('Corredora Dos')")
        ids = dict(conn.execute("SELECT nombre, id_corredora FROM corredora").fetchall())
        clave_hash = hash_clave(CLAVE)
        for nombre, correo, rol, corredora in (
            ("Corredor Uno", "corredor1@demo.cl", "corredor", ids["Corredora Demo"]),
            ("Corredor Dos", "corredor2@demo.cl", "corredor", ids["Corredora Dos"]),
            ("Analista", "analista@nuam.cl", "analista", None),
            ("Admin", "admin@nuam.cl", "administrador", None),
            ("Bloqueable", "bloqueo@demo.cl", "corredor", ids["Corredora Dos"]),
        ):
            conn.execute(
                "INSERT INTO usuario (id_corredora, nombre, correo, clave_hash, rol) VALUES (%s, %s, %s, %s, %s)",
                (corredora, nombre, correo, clave_hash, rol),
            )
        # un dato oficial de Bolsa para probar que nadie lo modifica
        id_oficial = conn.execute(
            """INSERT INTO calificacion (id_corredora, ejercicio, mercado, instrumento, fecha, secuencia, origen)
               VALUES (%s, 2023, 'ACN', 'Oficial Bolsa', '2023-12-12', 30001, 'bolsa') RETURNING id_calificacion""",
            (ids["Bolsa"],),
        ).fetchone()[0]
        conn.execute("INSERT INTO factor_calificacion VALUES (%s, 8, 1)", (id_oficial,))
    aplicacion = create_app({"TESTING": True, "SECRET_KEY": "clave-de-pruebas-de-integracion-0123456789", "DATABASE_URL": DSN})
    aplicacion.id_oficial = id_oficial
    return aplicacion


def token_de(html):
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def entrar(app, correo, clave=CLAVE):
    """Inicia sesion y devuelve (cliente, token CSRF vigente, respuesta del login)."""
    cliente = app.test_client()
    token = token_de(cliente.get("/login").text)
    respuesta = cliente.post("/login", data={"csrf_token": token, "correo": correo, "clave": clave})
    if respuesta.status_code == 302:        # la app renueva el token al iniciar sesion
        token = token_de(cliente.get("/calificaciones").text)
    return cliente, token, respuesta


def datos(token, secuencia, montos=None, **extra):
    campos = {"csrf_token": token, "ejercicio": "2024", "mercado": "acn", "instrumento": "Prueba",
              "fecha": "2024-12-12", "secuencia": str(secuencia)}
    campos.update({f"monto_{c}": (montos or MONTOS_HDU).get(c, "0") for c in range(8, 38)})
    campos.update(extra)
    return campos


def calcular(cliente, formulario, ruta="/calificaciones/nueva"):
    """Presiona Calcular y devuelve el formulario con los factores y la firma que entrega la pantalla."""
    respuesta = cliente.post(ruta, data={**formulario, "accion": "calcular"})
    assert respuesta.status_code == 200, respuesta.text[:300]
    resultado = dict(formulario)
    for columna, valor in re.findall(r'name="factor_(\d+)"[^>]*?value="([^"]*)"', respuesta.text, re.S):
        resultado[f"factor_{columna}"] = valor
    resultado["firma_montos"] = re.search(r'name="firma_montos"[^>]*value="([^"]*)"', respuesta.text).group(1)
    return resultado


def grabar(cliente, formulario, ruta="/calificaciones/nueva"):
    return cliente.post(ruta, data={**formulario, "accion": "grabar"})


def id_de(secuencia):
    fila = consultar("SELECT id_calificacion FROM calificacion WHERE secuencia = %s AND origen <> 'bolsa'", (secuencia,))
    return fila[0][0] if fila else None


# ---------------------------------------------------------------- inicio de sesion
def test_login_valido_y_clave_erronea(app):
    assert entrar(app, "corredor1@demo.cl", "ClaveMala123")[2].status_code == 401
    respuesta = entrar(app, "corredor1@demo.cl")[2]
    assert respuesta.status_code == 302 and respuesta.headers["Location"].endswith("/calificaciones")


def test_sin_sesion_no_se_entra(app):
    respuesta = app.test_client().get("/calificaciones")
    assert respuesta.status_code == 302 and "/login" in respuesta.headers["Location"]


def test_clave_guardada_con_hash(app):
    (clave_hash,), = consultar("SELECT clave_hash FROM usuario WHERE correo = 'corredor1@demo.cl'")
    assert clave_hash.startswith("pbkdf2_sha256$") and CLAVE not in clave_hash


def test_bloqueo_tras_intentos_fallidos(app):
    for _ in range(MAX_INTENTOS_FALLIDOS):
        assert entrar(app, "bloqueo@demo.cl", "ClaveMala123")[2].status_code == 401
    respuesta = entrar(app, "bloqueo@demo.cl")[2]            # clave correcta, pero ya esta bloqueada
    assert respuesta.status_code == 429 and "bloqueada" in respuesta.text
    consultar("UPDATE usuario SET bloqueado_hasta = now() - interval '1 minute' WHERE correo = 'bloqueo@demo.cl' RETURNING 1")
    assert entrar(app, "bloqueo@demo.cl")[2].status_code == 302   # vencido el bloqueo, vuelve a entrar
    assert consultar("SELECT intentos_fallidos FROM usuario WHERE correo = 'bloqueo@demo.cl'") == [(0,)]


# ---------------------------------------------------------------- flujo ideal
def test_flujo_ideal_con_ejemplo_del_hdu(app):
    cliente, token, _ = entrar(app, "corredor1@demo.cl")
    formulario = calcular(cliente, datos(token, 20001))
    assert formulario["factor_8"] == "0,52277431" and formulario["factor_25"] == "0,19335488"
    assert not consultar("SELECT 1 FROM calificacion WHERE secuencia = 20001"), "Calcular no debe guardar"

    assert grabar(cliente, formulario).status_code == 302
    id_calificacion = id_de(20001)
    assert consultar("SELECT origen, mercado FROM calificacion WHERE id_calificacion = %s", (id_calificacion,)) == [("manual", "ACN")]
    factores = dict(consultar("SELECT numero_factor, valor::text FROM factor_calificacion WHERE id_calificacion = %s", (id_calificacion,)))
    assert {k: factores[k] for k in FACTORES_HDU} == FACTORES_HDU
    suma = consultar("SELECT SUM(valor)::text FROM factor_calificacion WHERE id_calificacion = %s AND numero_factor BETWEEN 8 AND 19", (id_calificacion,))
    assert suma == [("1.00000000",)]
    log = consultar("SELECT accion, origen, datos_antes IS NULL, datos_despues->'factores'->>'8' FROM log_operacion WHERE id_registro = %s", (id_calificacion,))
    assert log == [("crear", "manual", True, "0.52277431")]

    grilla = cliente.get("/calificaciones").text      # la grilla muestra la fila con su fuente y la suma
    assert "Prueba" in grilla and "Manual" in grilla and "1,00000000" in grilla and "368.745.318" in grilla


def test_factor_editado_antes_de_grabar_es_el_que_se_guarda(app):
    cliente, token, _ = entrar(app, "corredor1@demo.cl")
    formulario = calcular(cliente, datos(token, 20010))
    formulario["factor_9"] = "0,10000000"                     # se edita a mano antes de grabar
    assert grabar(cliente, formulario).status_code == 302
    assert consultar("SELECT valor::text FROM factor_calificacion WHERE id_calificacion = %s AND numero_factor = 9", (id_de(20010),)) == [("0.10000000",)]


# ---------------------------------------------------------------- errores y bordes
def test_suma_de_factores_mayor_que_uno_se_rechaza(app):
    cliente, token, _ = entrar(app, "corredor1@demo.cl")
    formulario = calcular(cliente, datos(token, 20020))
    formulario["factor_9"] = "0,17400053"                     # suma 8 a 19 = 1,00000001
    respuesta = grabar(cliente, formulario)
    assert respuesta.status_code == 400 and "supera 1" in respuesta.text
    assert id_de(20020) is None


def test_suma_exactamente_uno_con_seis_montos_iguales(app):
    cliente, token, _ = entrar(app, "corredor1@demo.cl")
    formulario = calcular(cliente, datos(token, 20030, montos={c: "100" for c in range(8, 14)}))
    assert grabar(cliente, formulario).status_code == 302
    suma = consultar("SELECT SUM(valor)::text FROM factor_calificacion WHERE id_calificacion = %s AND numero_factor BETWEEN 8 AND 19", (id_de(20030),))
    assert suma == [("1.00000000",)]


def test_suma_de_montos_cero_no_calcula(app):
    cliente, token, _ = entrar(app, "corredor1@demo.cl")
    respuesta = cliente.post("/calificaciones/nueva", data={**datos(token, 20040, montos={25: "1000"}), "accion": "calcular"})
    assert respuesta.status_code == 400 and "es 0" in respuesta.text


def test_grabar_exige_calcular_y_montos_sin_cambios(app):
    cliente, token, _ = entrar(app, "corredor1@demo.cl")
    respuesta = grabar(cliente, datos(token, 20050))           # sin Calcular
    assert respuesta.status_code == 400 and "Presiona Calcular" in respuesta.text
    formulario = calcular(cliente, datos(token, 20050))
    formulario["monto_8"] = "999"                              # monto cambiado despues de Calcular
    respuesta = grabar(cliente, formulario)
    assert respuesta.status_code == 400 and "cambiaron" in respuesta.text
    assert id_de(20050) is None


@pytest.mark.parametrize("cambio, mensaje", [
    ({"instrumento": ""}, "Instrumento debe tener"),
    ({"secuencia": "10000"}, "mayor que 10.000"),
    ({"monto_8": "-5"}, "positivo o cero"),
    ({"monto_8": "abc"}, "monto numérico"),
    ({"factor_34": "1,5"}, "entre 0 y 1"),
    ({"factor_8": "0,123456789"}, "8 decimales"),
])
def test_dato_invalido_se_rechaza_y_no_guarda(app, cambio, mensaje):
    cliente, token, _ = entrar(app, "corredor1@demo.cl")
    formulario = calcular(cliente, datos(token, 20060))
    formulario.update(cambio)
    if "monto_8" in cambio:      # el monto invalido se detecta al leerlo, antes de la firma
        formulario.pop("firma_montos")
    respuesta = grabar(cliente, formulario)
    assert respuesta.status_code == 400 and mensaje in respuesta.text
    assert id_de(20060) is None and id_de(10000) is None


def test_llave_duplicada_se_rechaza(app):
    cliente, token, _ = entrar(app, "corredor1@demo.cl")
    formulario = calcular(cliente, datos(token, 20070))
    assert grabar(cliente, formulario).status_code == 302
    assert grabar(cliente, formulario).status_code == 409


def test_post_sin_token_csrf_se_rechaza(app):
    cliente, token, _ = entrar(app, "corredor1@demo.cl")
    formulario = calcular(cliente, datos(token, 20080))
    formulario.pop("csrf_token")
    assert grabar(cliente, formulario).status_code == 400 and id_de(20080) is None


# ---------------------------------------------------------------- acceso por corredora y por rol
def test_un_corredor_no_ve_ni_altera_lo_de_otro(app):
    cliente1, token1, _ = entrar(app, "corredor1@demo.cl")
    assert grabar(cliente1, calcular(cliente1, datos(token1, 20100, instrumento="Privado Uno"))).status_code == 302
    id_ajeno = id_de(20100)
    cliente2, token2, _ = entrar(app, "corredor2@demo.cl")
    assert "Privado Uno" not in cliente2.get("/calificaciones").text
    for ruta in (f"/calificaciones/{id_ajeno}", f"/calificaciones/{id_ajeno}/editar", f"/calificaciones/{id_ajeno}/eliminar"):
        assert cliente2.get(ruta).status_code == 404, ruta
    assert cliente2.post(f"/calificaciones/{id_ajeno}/eliminar", data={"csrf_token": token2}).status_code == 404
    assert grabar(cliente2, calcular(cliente2, datos(token2, 20100)), f"/calificaciones/{id_ajeno}/editar").status_code == 404
    assert consultar("SELECT instrumento FROM calificacion WHERE id_calificacion = %s", (id_ajeno,)) == [("Privado Uno",)]


def test_dato_oficial_de_bolsa_visible_pero_bloqueado(app):
    cliente, token, _ = entrar(app, "corredor2@demo.cl")
    grilla = cliente.get("/calificaciones").text
    assert "Oficial Bolsa" in grilla and "Solo lectura" in grilla
    assert cliente.get(f"/calificaciones/{app.id_oficial}").status_code == 200       # se puede ver
    assert cliente.get(f"/calificaciones/{app.id_oficial}/editar").status_code == 404
    assert cliente.post(f"/calificaciones/{app.id_oficial}/eliminar", data={"csrf_token": token}).status_code == 404
    assert consultar("SELECT instrumento FROM calificacion WHERE id_calificacion = %s", (app.id_oficial,)) == [("Oficial Bolsa",)]


def test_la_calificacion_del_corredor_predomina_sobre_la_de_bolsa(app):
    cliente, token, _ = entrar(app, "corredor2@demo.cl")
    propia = datos(token, 30001, ejercicio="2023", instrumento="Oficial Bolsa", fecha="2023-12-12")
    assert grabar(cliente, calcular(cliente, propia)).status_code == 302
    grilla = cliente.get("/calificaciones", query_string={"q": "Oficial Bolsa"}).text
    assert "1 resultado(s)" in grilla and "Predomina sobre Bolsa" in grilla
    assert consultar("SELECT 1 FROM calificacion WHERE id_calificacion = %s", (app.id_oficial,)), "lo de Bolsa no se altera"
    otra = entrar(app, "corredor1@demo.cl")[0].get("/calificaciones", query_string={"q": "Oficial Bolsa"}).text
    assert "Predomina" not in otra and "Oficial" in otra    # el otro corredor sigue viendo la oficial


@pytest.mark.parametrize("correo", ["analista@nuam.cl", "admin@nuam.cl"])
def test_analista_y_administrador_son_de_solo_lectura(app, correo):
    cliente, token, _ = entrar(app, correo)
    grilla = cliente.get("/calificaciones").text
    assert "Copec" in grilla and "Oficial Bolsa" in grilla    # consultan todas las corredoras
    id_copec = consultar("SELECT id_calificacion FROM calificacion WHERE instrumento = 'Copec'")[0][0]
    assert cliente.get(f"/calificaciones/{id_copec}").status_code == 200
    assert cliente.get("/calificaciones/nueva").status_code == 403
    assert grabar(cliente, datos(token, 20200)).status_code == 403
    assert cliente.post(f"/calificaciones/{id_copec}/editar", data={"csrf_token": token}).status_code == 403
    assert cliente.post(f"/calificaciones/{id_copec}/eliminar", data={"csrf_token": token}).status_code == 403
    assert consultar("SELECT 1 FROM calificacion WHERE id_calificacion = %s", (id_copec,))


# ---------------------------------------------------------------- busqueda, inyeccion y XSS
def test_busqueda_inyeccion_sql_y_xss(app):
    cliente, token, _ = entrar(app, "corredor1@demo.cl")
    assert "Copec" in cliente.get("/calificaciones", query_string={"q": "copec"}).text
    inyeccion = cliente.get("/calificaciones", query_string={"q": "' OR 1=1 --"})
    assert inyeccion.status_code == 200 and "No hay resultados" in inyeccion.text
    comodin = cliente.get("/calificaciones", query_string={"q": "%"})
    assert "No hay resultados" in comodin.text              # % se busca como texto, no como comodin
    assert grabar(cliente, calcular(cliente, datos(token, 20300, instrumento="<script>alert(1)</script>"))).status_code == 302
    grilla = cliente.get("/calificaciones").text
    assert "<script>alert(1)</script>" not in grilla and "&lt;script&gt;alert(1)&lt;/script&gt;" in grilla


# ---------------------------------------------------------------- modificar, eliminar y log
def test_modificar_y_eliminar_dejan_log(app):
    cliente, token, _ = entrar(app, "corredor1@demo.cl")
    assert grabar(cliente, calcular(cliente, datos(token, 20400))).status_code == 302
    id_calificacion = id_de(20400)
    ruta = f"/calificaciones/{id_calificacion}/editar"

    pantalla = cliente.get(ruta).text
    assert 'value="192770580.00"' in pantalla and 'value="0,52277431"' in pantalla
    cambio = calcular(cliente, datos(token, 20400, montos={8: "100", 9: "100"}), ruta)
    assert grabar(cliente, cambio, ruta).status_code == 302
    factores = dict(consultar("SELECT numero_factor, valor::text FROM factor_calificacion WHERE id_calificacion = %s AND numero_factor IN (8, 9)", (id_calificacion,)))
    assert factores == {8: "0.50000000", 9: "0.50000000"}
    assert consultar("SELECT modificado_en IS NOT NULL FROM calificacion WHERE id_calificacion = %s", (id_calificacion,)) == [(True,)]
    assert "Modificada" in cliente.get("/calificaciones", query_string={"q": "Prueba"}).text

    assert "no se puede deshacer" in cliente.get(f"/calificaciones/{id_calificacion}/eliminar").text
    assert cliente.post(f"/calificaciones/{id_calificacion}/eliminar", data={"csrf_token": token}).status_code == 302
    assert not consultar("SELECT 1 FROM calificacion WHERE id_calificacion = %s", (id_calificacion,))
    assert not consultar("SELECT 1 FROM factor_calificacion WHERE id_calificacion = %s", (id_calificacion,))

    log = consultar(
        """SELECT accion, datos_antes->'factores'->>'8', datos_despues->'factores'->>'8'
           FROM log_operacion WHERE id_registro = %s ORDER BY id_log""", (id_calificacion,))
    assert log == [("crear", None, "0.52277431"), ("modificar", "0.52277431", "0.50000000"), ("eliminar", "0.50000000", None)]


def test_el_log_no_se_puede_editar_ni_borrar(app):
    for sql in ("UPDATE log_operacion SET accion = 'crear'", "DELETE FROM log_operacion"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            consultar(sql + " RETURNING 1")
