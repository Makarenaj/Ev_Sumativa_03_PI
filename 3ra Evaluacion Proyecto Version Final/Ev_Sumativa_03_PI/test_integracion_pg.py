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
import io
import re
import time

import psycopg
import pytest

import carga_csv
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


def test_analista_es_de_solo_lectura(app):
    cliente, token, _ = entrar(app, "analista@nuam.cl")
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



# ---------------------------------------------------------------- administrador
def id_corredora(nombre):
    return consultar("SELECT id_corredora FROM corredora WHERE nombre = %s", (nombre,))[0][0]


def test_administrador_crea_modifica_y_elimina_en_cualquier_corredora(app):
    cliente, token, _ = entrar(app, "admin@nuam.cl")
    pantalla = cliente.get("/calificaciones/nueva")
    assert pantalla.status_code == 200 and 'name="id_corredora"' in pantalla.text
    destino = id_corredora("Corredora Dos")
    formulario = calcular(cliente, datos(token, 40001, instrumento="Creada por admin", id_corredora=str(destino)))
    assert grabar(cliente, formulario).status_code == 302
    id_nueva = id_de(40001)
    assert consultar("SELECT id_corredora, origen FROM calificacion WHERE id_calificacion = %s", (id_nueva,)) == [(destino, "manual")]
    # modificar: cambia el monto de la columna 9 y vuelve a calcular
    ruta = f"/calificaciones/{id_nueva}/editar"
    nuevos = {**MONTOS_HDU, 9: "100000000"}
    editado = calcular(cliente, datos(token, 40001, montos=nuevos, instrumento="Creada por admin"), ruta=ruta)
    assert grabar(cliente, editado, ruta=ruta).status_code == 302
    (factor_9,), = consultar("SELECT valor FROM factor_calificacion WHERE id_calificacion = %s AND numero_factor = 9", (id_nueva,))
    assert str(factor_9) != FACTORES_HDU[9]
    assert consultar("SELECT 1 FROM log_operacion WHERE accion = 'modificar' AND id_registro = %s", (id_nueva,))
    # eliminar con confirmacion
    assert cliente.get(f"/calificaciones/{id_nueva}/eliminar").status_code == 200
    assert cliente.post(f"/calificaciones/{id_nueva}/eliminar", data={"csrf_token": token}).status_code == 302
    assert not consultar("SELECT 1 FROM calificacion WHERE id_calificacion = %s", (id_nueva,))
    acciones = [a for (a,) in consultar("SELECT accion FROM log_operacion WHERE id_registro = %s ORDER BY id_log", (id_nueva,))]
    assert acciones == ["crear", "modificar", "eliminar"]
    (usuario_log,), = consultar("SELECT u.rol FROM log_operacion l JOIN usuario u USING (id_usuario) WHERE l.id_registro = %s LIMIT 1", (id_nueva,))
    assert usuario_log == "administrador"


def test_administrador_no_ingresa_en_la_bolsa_ni_sin_corredora(app):
    cliente, token, _ = entrar(app, "admin@nuam.cl")
    antes = consultar("SELECT count(*) FROM calificacion")[0][0]
    en_bolsa = calcular(cliente, datos(token, 40002, id_corredora=str(id_corredora("Bolsa"))))
    assert grabar(cliente, en_bolsa).status_code == 400
    sin_corredora = calcular(cliente, datos(token, 40003))
    assert grabar(cliente, sin_corredora).status_code == 400
    assert consultar("SELECT count(*) FROM calificacion")[0][0] == antes


def test_administrador_no_modifica_ni_elimina_lo_oficial(app):
    cliente, token, _ = entrar(app, "admin@nuam.cl")
    oficial = app.id_oficial
    assert not cliente.get(f"/calificaciones/{oficial}").text.count("Eliminar")
    assert cliente.post(f"/calificaciones/{oficial}/eliminar", data={"csrf_token": token}).status_code == 302
    assert cliente.post(f"/calificaciones/{oficial}/editar", data={"csrf_token": token}).status_code in (302, 400)
    assert consultar("SELECT instrumento FROM calificacion WHERE id_calificacion = %s", (oficial,)) == [("Oficial Bolsa",)]


# ---------------------------------------------------------------- registro de operaciones (log)
def test_log_lo_consultan_analista_y_administrador_y_no_el_corredor(app):
    assert entrar(app, "corredor1@demo.cl")[0].get("/log").status_code == 403
    for correo in ("analista@nuam.cl", "admin@nuam.cl"):
        pagina = entrar(app, correo)[0].get("/log")
        assert pagina.status_code == 200 and "Registro de operaciones" in pagina.text
    cliente, token, _ = entrar(app, "admin@nuam.cl")
    assert "crear" in cliente.get("/log").text      # aparecen las operaciones hechas arriba
    assert cliente.post("/log", data={"csrf_token": token}).status_code == 405   # solo se consulta


def test_menu_segun_el_perfil(app):
    corredor = entrar(app, "corredor1@demo.cl")[0].get("/calificaciones").text
    assert "Carga masiva (CSV)" in corredor and "Registro de operaciones" not in corredor
    for correo in ("analista@nuam.cl", "admin@nuam.cl"):
        pagina = entrar(app, correo)[0].get("/calificaciones").text
        assert "Registro de operaciones" in pagina and "Carga masiva (CSV)" not in pagina


# ---------------------------------------------------------------- carga masiva CSV
RUTA_CSV = "/calificaciones/cargar-csv"


def fila_csv(instrumento, secuencia, f8="0.5", f9="0.5", fecha="2024-06-30", extra=None):
    valores = {"ejercicio": "2024", "mercado": "ACN", "instrumento": instrumento, "fecha": fecha,
               "secuencia": str(secuencia), "tipo_sociedad": "A", "factor_8": f8, "factor_9": f9}
    valores.update(extra or {})
    return [valores.get(columna, "") for columna in carga_csv.CABECERA]


def texto_csv(filas, delimitador=","):
    salida = io.StringIO(newline="")
    escritor = __import__("csv").writer(salida, delimiter=delimitador, lineterminator="\n")
    escritor.writerow(carga_csv.CABECERA)
    escritor.writerows(filas)
    return salida.getvalue()


def subir(cliente, token, texto, nombre="carga.csv"):
    return cliente.post(RUTA_CSV, data={"csrf_token": token, "accion": "previsualizar",
                                        "archivo_csv": (io.BytesIO(texto.encode("utf-8")), nombre)})


def confirmar(cliente, token, texto, nombre="carga.csv"):
    return cliente.post(RUTA_CSV, data={"csrf_token": token, "accion": "confirmar",
                                        "nombre_archivo": nombre, "contenido_csv": texto})


def test_csv_valido_se_previsualiza_y_al_confirmar_agrega_y_actualiza(app):
    cliente, token, _ = entrar(app, "corredor1@demo.cl")
    texto = carga_csv.ejemplo_csv()          # Copec ya existe en la corredora; Cencosud y Falabella son nuevas
    vista = subir(cliente, token, texto)
    assert vista.status_code == 200 and "Confirmar carga" in vista.text
    assert "Actualiza" in vista.text and "Agrega" in vista.text
    assert not consultar("SELECT 1 FROM calificacion WHERE instrumento = 'Cencosud'"), "la previsualizacion no guarda nada"
    assert confirmar(cliente, token, texto, "ejemplo.csv").status_code == 302
    assert len(consultar("SELECT 1 FROM calificacion WHERE instrumento IN ('Cencosud', 'Falabella') AND origen = 'carga_masiva'")) == 2
    (origen,), = consultar("SELECT origen FROM calificacion WHERE instrumento = 'Copec' AND id_corredora = %s", (id_corredora("Corredora Demo"),))
    assert origen == "carga_masiva"                                         # se actualizo, no se duplico
    assert len(consultar("SELECT 1 FROM calificacion WHERE instrumento = 'Copec' AND id_corredora = %s", (id_corredora("Corredora Demo"),))) == 1
    (factor_8,), = consultar("""SELECT f.valor FROM factor_calificacion f JOIN calificacion c USING (id_calificacion)
                                WHERE c.instrumento = 'Copec' AND f.numero_factor = 8""")
    assert str(factor_8) == FACTORES_HDU[8]
    assert consultar("SELECT estado, total_filas, filas_invalidas FROM carga_archivo WHERE nombre_archivo = 'ejemplo.csv'") == [("confirmado", 3, 0)]
    (despues,), = consultar("SELECT datos_despues FROM log_operacion WHERE accion = 'carga_masiva' ORDER BY id_log DESC LIMIT 1")
    assert despues["agregadas"] == 2 and despues["actualizadas"] == 1


def test_csv_con_una_fila_invalida_se_rechaza_completo(app):
    cliente, token, _ = entrar(app, "corredor1@demo.cl")
    texto = texto_csv([fila_csv("RechazoA", 41001), fila_csv("RechazoB", 41002, f8="0.7", f9="0.5"), fila_csv("RechazoC", 41003)])
    respuesta = subir(cliente, token, texto, "con_error.csv")
    assert respuesta.status_code == 400 and "rechazó completo" in respuesta.text and "supera 1" in respuesta.text
    assert "Fila del archivo" in respuesta.text and ">3<" in respuesta.text.replace(" ", "")     # indica la fila con el error
    assert confirmar(cliente, token, texto, "con_error.csv").status_code == 400       # tampoco se puede forzar al confirmar
    assert not consultar("SELECT 1 FROM calificacion WHERE instrumento ~ '^Rechazo'")
    estado, invalidas, detalle = consultar("SELECT estado, filas_invalidas, detalle_error FROM carga_archivo WHERE nombre_archivo = 'con_error.csv' ORDER BY id_carga LIMIT 1")[0]
    assert estado == "rechazado" and invalidas == 1 and "supera 1" in detalle
    # una vez corregido, el mismo archivo se acepta
    corregido = texto_csv([fila_csv("RechazoA", 41001), fila_csv("RechazoB", 41002), fila_csv("RechazoC", 41003)])
    assert subir(cliente, token, corregido, "corregido.csv").status_code == 200
    assert confirmar(cliente, token, corregido, "corregido.csv").status_code == 302
    assert len(consultar("SELECT 1 FROM calificacion WHERE instrumento ~ '^Rechazo'")) == 3


def test_csv_con_formato_incorrecto(app):
    cliente, token, _ = entrar(app, "corredor1@demo.cl")
    assert subir(cliente, token, "a,b\n1,2", "datos.txt").status_code == 400                    # no es .csv
    respuesta = subir(cliente, token, "ejercicio,mercado\n2024,ACN", "corto.csv")
    assert respuesta.status_code == 400 and "Formato incorrecto" in respuesta.text
    assert subir(cliente, token, "", "vacio.csv").status_code == 400
    assert cliente.post(RUTA_CSV, data={"csrf_token": token, "accion": "otra"}).status_code == 400


def test_csv_punto_y_coma_con_decimal_coma(app):
    cliente, token, _ = entrar(app, "corredor1@demo.cl")
    texto = texto_csv([fila_csv("ComaDecimal", 42001, f8="0,25", f9="0,75")], delimitador=";")
    assert confirmar(cliente, token, texto).status_code == 302
    (factor,), = consultar("SELECT f.valor FROM factor_calificacion f JOIN calificacion c USING (id_calificacion) WHERE c.instrumento = 'ComaDecimal' AND f.numero_factor = 8")
    assert str(factor) == "0.25000000"


def test_csv_es_local_de_cada_corredora(app):
    cliente, token, _ = entrar(app, "corredor2@demo.cl")
    texto = texto_csv([fila_csv("Copec", 123123, extra={"ejercicio": "2023", "fecha": "2023-12-12"})])
    assert "Agrega" in subir(cliente, token, texto).text          # para la otra corredora es una calificacion nueva
    assert confirmar(cliente, token, texto).status_code == 302
    assert len(consultar("SELECT 1 FROM calificacion WHERE instrumento = 'Copec' AND secuencia = 123123")) == 2


def test_csv_solo_lo_carga_el_corredor(app):
    for correo in ("analista@nuam.cl", "admin@nuam.cl"):
        cliente, token, _ = entrar(app, correo)
        assert cliente.get(RUTA_CSV).status_code == 403
        assert subir(cliente, token, carga_csv.ejemplo_csv()).status_code == 403
    assert entrar(app, "corredor1@demo.cl")[0].get(RUTA_CSV).status_code == 200
    assert entrar(app, "corredor1@demo.cl")[0].get(RUTA_CSV + "/ejemplo").status_code == 200


def test_csv_sin_token_csrf_se_rechaza(app):
    cliente, _, _ = entrar(app, "corredor1@demo.cl")
    respuesta = cliente.post(RUTA_CSV, data={"accion": "confirmar", "contenido_csv": carga_csv.ejemplo_csv()})
    assert respuesta.status_code in (400, 403)


def test_csv_de_1000_filas_se_procesa_en_menos_de_10_segundos(app):
    cliente, token, _ = entrar(app, "corredor1@demo.cl")
    texto = texto_csv([fila_csv(f"Estres{n:04d}", 100000 + n) for n in range(1000)])
    inicio = time.perf_counter()
    assert subir(cliente, token, texto, "estres.csv").status_code == 200
    assert confirmar(cliente, token, texto, "estres.csv").status_code == 302
    assert time.perf_counter() - inicio < 10
    assert consultar("SELECT count(*) FROM calificacion WHERE instrumento ~ '^Estres'")[0][0] == 1000
