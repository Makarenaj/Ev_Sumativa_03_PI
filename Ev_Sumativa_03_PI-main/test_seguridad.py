"""Pruebas de autenticacion, perfiles y acceso por corredora."""
import unittest

from seguridad import (
    AccesoDenegado,
    CuentaBloqueada,
    ErrorValidacion,
    SesionUsuario,
    autenticar,
    crear_usuario,
    hash_clave,
    listar_calificaciones,
    verificar_clave,
)


class CursorFalso:
    def __init__(self, fila=None, filas=None):
        self.fila = fila
        self.filas = filas or []
        self.consultas = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, consulta, parametros):
        self.consultas.append((consulta, parametros))

    def fetchone(self):
        return self.fila

    def fetchall(self):
        return self.filas


class ConexionFalsa:
    def __init__(self, cursor):
        self.cursor_falso = cursor

    def cursor(self):
        return self.cursor_falso


class PruebasSeguridad(unittest.TestCase):
    def test_hash_usa_sales_distintas_y_verifica_clave(self):
        primero = hash_clave("clave-segura-123")
        segundo = hash_clave("clave-segura-123")
        self.assertNotEqual(primero, segundo)
        self.assertTrue(verificar_clave("clave-segura-123", primero))
        self.assertFalse(verificar_clave("otra-clave-123", primero))

    def test_login_parametrizado_devuelve_perfil_y_rechaza_clave_incorrecta(self):
        clave_hash = hash_clave("clave-segura-123")
        cursor = CursorFalso((7, 42, "corredor", clave_hash, False))
        sesion = autenticar(ConexionFalsa(cursor), " Ana@Ejemplo.cl ", "clave-segura-123")
        consulta, parametros = cursor.consultas[0]
        self.assertEqual(sesion, SesionUsuario(7, 42, "corredor"))
        self.assertIn("correo = %s", consulta)
        self.assertEqual(parametros, ("ana@ejemplo.cl",))

        self.assertIsNone(
            autenticar(ConexionFalsa(cursor), "ana@ejemplo.cl", "clave-incorrecta")
        )
        # la clave incorrecta suma un intento fallido con una consulta parametrizada
        consulta, parametros = cursor.consultas[-1]
        self.assertIn("intentos_fallidos", consulta)
        self.assertEqual(parametros, (5, 15, 7, 7))

    def test_cuenta_bloqueada_no_inicia_sesion_ni_con_clave_correcta(self):
        clave_hash = hash_clave("clave-segura-123")
        cursor = CursorFalso((7, 42, "corredor", clave_hash, True))
        with self.assertRaises(CuentaBloqueada):
            autenticar(ConexionFalsa(cursor), "ana@ejemplo.cl", "clave-segura-123")

    def test_correo_inexistente_devuelve_none(self):
        cursor = CursorFalso(None)
        self.assertIsNone(
            autenticar(ConexionFalsa(cursor), "nadie@ejemplo.cl", "clave-segura-123")
        )

    def test_corredor_solo_lista_su_propia_corredora(self):
        cursor = CursorFalso(filas=[(1, 42, 2024, "ACN", "Copec", None, 1)])
        resultado = listar_calificaciones(
            ConexionFalsa(cursor), SesionUsuario(7, 42, "corredor")
        )
        consulta, parametros = cursor.consultas[0]
        self.assertIn("WHERE id_corredora = %s", consulta)
        self.assertEqual(parametros, (42,))
        self.assertEqual(len(resultado), 1)

    def test_corredor_no_puede_solicitar_otra_corredora(self):
        cursor = CursorFalso()
        with self.assertRaises(AccesoDenegado):
            listar_calificaciones(
                ConexionFalsa(cursor), SesionUsuario(7, 42, "corredor"), 99
            )
        self.assertEqual(cursor.consultas, [])

    def test_analista_puede_consultar_todas_las_corredoras(self):
        cursor = CursorFalso(filas=[(1, 42, 2024, "ACN", "Copec", None, 1)])
        listar_calificaciones(
            ConexionFalsa(cursor), SesionUsuario(3, None, "analista")
        )
        consulta, parametros = cursor.consultas[0]
        self.assertNotIn("WHERE id_corredora", consulta)
        self.assertEqual(parametros, ())

    def test_solo_administrador_puede_crear_perfiles(self):
        cursor = CursorFalso((8,))
        conn = ConexionFalsa(cursor)
        with self.assertRaises(AccesoDenegado):
            crear_usuario(
                conn, SesionUsuario(7, 42, "corredor"),
                "Nuevo", "nuevo@ejemplo.cl", "clave-segura-123", "administrador"
            )
        self.assertEqual(cursor.consultas, [])

        creado = crear_usuario(
            conn, SesionUsuario(1, None, "administrador"),
            "Nuevo", "nuevo@ejemplo.cl", "clave-segura-123", "corredor", 42
        )
        consulta, parametros = cursor.consultas[0]
        self.assertEqual(creado, 8)
        self.assertIn("VALUES (%s, %s, %s, %s, %s)", consulta)
        self.assertEqual(parametros[:3], (42, "Nuevo", "nuevo@ejemplo.cl"))
        self.assertTrue(verificar_clave("clave-segura-123", parametros[3]))
        self.assertNotEqual(parametros[3], "clave-segura-123")

    def test_valida_correo_y_clave_antes_de_consultar(self):
        cursor = CursorFalso()
        conn = ConexionFalsa(cursor)
        with self.assertRaises(ErrorValidacion):
            autenticar(conn, "no-es-correo", "clave-segura-123")
        with self.assertRaises(ErrorValidacion):
            autenticar(conn, "ana@ejemplo.cl", "corta")
        self.assertEqual(cursor.consultas, [])


if __name__ == "__main__":
    unittest.main()
