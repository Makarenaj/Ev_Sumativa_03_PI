"""Pruebas de rutas web sin depender de PostgreSQL."""
import os
import unittest
from unittest.mock import patch

from app import create_app
from seguridad import SesionUsuario


class CursorFalso:
    def __init__(self):
        self.fila = None
        self.consulta = ""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, consulta, parametros=()):
        self.consulta = consulta
        if "FROM usuario" in consulta and "activo = TRUE" in consulta:
            self.fila = (7, 42, "corredor")
        else:
            self.fila = None

    def fetchone(self):
        return self.fila

    def fetchall(self):
        if "FROM calificacion c" in self.consulta:
            return []
        return [(42, "Corredora Demo", False)]


class ConexionFalsa:
    def __init__(self):
        self.cursor_falso = CursorFalso()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return self.cursor_falso


class PruebasAplicacion(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SECRET_KEY": "clave-de-prueba-no-usar-en-produccion",
            "DB_CONNECT": ConexionFalsa,
        })
        self.client = self.app.test_client()

    def iniciar_sesion_de_prueba(self):
        self.client.get("/login")
        with self.client.session_transaction() as sesion:
            sesion["id_usuario"] = 7
            return sesion["_csrf_token"]

    def test_arranque_exige_clave_y_conexion(self):
        with patch.dict(os.environ, {"DATABASE_URL": ""}):
            with self.assertRaisesRegex(RuntimeError, "DATABASE_URL"):
                create_app({"SECRET_KEY": "clave-de-prueba"})

    def test_pantalla_login_y_ruta_protegida(self):
        respuesta = self.client.get("/login")
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn(b'name="correo"', respuesta.data)
        self.assertEqual(self.client.get("/calificaciones").status_code, 302)

    def test_login_crea_sesion_solo_tras_autenticacion(self):
        self.client.get("/login")
        with self.client.session_transaction() as sesion:
            csrf = sesion["_csrf_token"]
        with patch("app.autenticar", return_value=SesionUsuario(7, 42, "corredor")):
            respuesta = self.client.post(
                "/login",
                data={
                    "csrf_token": csrf,
                    "correo": "corredor@ejemplo.cl",
                    "clave": "ClaveDemo123",
                },
            )
        self.assertEqual(respuesta.status_code, 302)
        with self.client.session_transaction() as sesion:
            self.assertEqual(sesion["id_usuario"], 7)

    def test_post_rechaza_token_csrf_ausente(self):
        self.iniciar_sesion_de_prueba()
        respuesta = self.client.post("/api/calculo", json={"montos": {}})
        self.assertEqual(respuesta.status_code, 400)

    def test_formulario_ingreso_muestra_columnas_y_totales(self):
        self.iniciar_sesion_de_prueba()
        respuesta = self.client.get("/calificaciones/nueva")
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn(b'name="monto_8"', respuesta.data)
        self.assertIn(b'name="factor_34"', respuesta.data)
        self.assertIn("Suma de montos (columnas 8–19)".encode(), respuesta.data)

    def test_ingreso_rechaza_instrumento_vacio(self):
        csrf = self.iniciar_sesion_de_prueba()
        respuesta = self.client.post(
            "/calificaciones/nueva",
            data={
                "csrf_token": csrf,
                "ejercicio": "2025",
                "mercado": "ACN",
                "instrumento": "",
                "fecha": "2025-01-10",
                "secuencia": "1",
            },
        )
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn(b"Instrumento debe tener", respuesta.data)

    def test_formulario_tiene_calcular_grabar_y_cancelar(self):
        self.iniciar_sesion_de_prueba()
        html = self.client.get("/calificaciones/nueva").get_data(as_text=True)
        for boton in (">Calcular<", ">Grabar<", ">Cancelar<"):
            self.assertIn(boton, html)
        self.assertIn('name="factor_8"', html)      # los factores son editables

    def test_calcular_muestra_factores_y_no_guarda(self):
        csrf = self.iniciar_sesion_de_prueba()
        respuesta = self.client.post(
            "/calificaciones/nueva",
            data={"csrf_token": csrf, "accion": "calcular", "monto_8": "100", "monto_9": "100"},
        )
        html = respuesta.get_data(as_text=True)
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('value="0,50000000"', html)
        self.assertIn("Cumple: no supera 1.", html)

    def test_grabar_sin_calcular_se_rechaza(self):
        csrf = self.iniciar_sesion_de_prueba()
        respuesta = self.client.post(
            "/calificaciones/nueva",
            data={
                "csrf_token": csrf, "accion": "grabar", "ejercicio": "2025", "mercado": "ACN",
                "instrumento": "Copec", "fecha": "2025-01-10", "secuencia": "20001",
                "monto_8": "100",
            },
        )
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("Presiona Calcular", respuesta.get_data(as_text=True))

    def test_secuencia_debe_ser_mayor_que_10000(self):
        csrf = self.iniciar_sesion_de_prueba()
        respuesta = self.client.post(
            "/calificaciones/nueva",
            data={
                "csrf_token": csrf, "accion": "grabar", "ejercicio": "2025", "mercado": "ACN",
                "instrumento": "Copec", "fecha": "2025-01-10", "secuencia": "10000",
            },
        )
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("mayor que 10.000", respuesta.get_data(as_text=True))

    def test_sesion_se_cierra_por_inactividad(self):
        self.iniciar_sesion_de_prueba()
        with self.client.session_transaction() as sesion:
            sesion["ultima_actividad"] = 0      # ultima actividad hace mucho mas de 15 minutos
        respuesta = self.client.get("/calificaciones")
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn("/login", respuesta.headers["Location"])
        with self.client.session_transaction() as sesion:
            self.assertNotIn("id_usuario", sesion)

    def test_cabeceras_de_seguridad(self):
        respuesta = self.client.get("/login")
        self.assertIn("default-src 'self'", respuesta.headers["Content-Security-Policy"])
        self.assertEqual(respuesta.headers["X-Frame-Options"], "DENY")
        self.assertEqual(respuesta.headers["X-Content-Type-Options"], "nosniff")

    def test_busqueda_muestra_estado_vacio(self):
        self.iniciar_sesion_de_prueba()
        respuesta = self.client.get("/calificaciones?q=copec")
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn(b"No hay resultados", respuesta.data)

    def test_api_calcula_suma_visible_y_factores(self):
        csrf = self.iniciar_sesion_de_prueba()
        montos = {"8": "100.00"}
        respuesta = self.client.post(
            "/api/calculo",
            json={"montos": montos, "factores_manuales": {}},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(respuesta.status_code, 200)
        resultado = respuesta.get_json()
        self.assertEqual(resultado["suma_montos"], "100.00")
        self.assertEqual(resultado["suma_factores"], "1.00000000")
        self.assertEqual(resultado["factores"]["8"], "1.00000000")

    def test_api_rechaza_suma_de_montos_cero(self):
        csrf = self.iniciar_sesion_de_prueba()
        respuesta = self.client.post(
            "/api/calculo",
            json={"montos": {}, "factores_manuales": {}},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("es 0", respuesta.get_json()["error"])


class PruebasSoloLectura(unittest.TestCase):
    """El analista consulta, pero no crea, modifican ni eliminan."""

    def setUp(self):
        class CursorAnalista(CursorFalso):
            def execute(self, consulta, parametros=()):
                super().execute(consulta, parametros)
                if "FROM usuario" in consulta and "activo = TRUE" in consulta:
                    self.fila = (9, None, "analista")

        class ConexionAnalista(ConexionFalsa):
            def __init__(self):
                self.cursor_falso = CursorAnalista()

        self.app = create_app({
            "TESTING": True,
            "SECRET_KEY": "clave-de-prueba-no-usar-en-produccion",
            "DB_CONNECT": ConexionAnalista,
        })
        self.client = self.app.test_client()
        self.client.get("/login")
        with self.client.session_transaction() as sesion:
            sesion["id_usuario"] = 9
            self.csrf = sesion["_csrf_token"]

    def test_analista_consulta_el_listado(self):
        respuesta = self.client.get("/calificaciones")
        self.assertEqual(respuesta.status_code, 200)
        self.assertNotIn("Ingresar calificaci", respuesta.get_data(as_text=True))

    def test_analista_no_puede_crear_modificar_ni_eliminar(self):
        self.assertEqual(self.client.get("/calificaciones/nueva").status_code, 403)
        for ruta in ("/calificaciones/nueva", "/calificaciones/1/editar", "/calificaciones/1/eliminar"):
            respuesta = self.client.post(ruta, data={"csrf_token": self.csrf})
            self.assertEqual(respuesta.status_code, 403, ruta)


if __name__ == "__main__":
    unittest.main()
