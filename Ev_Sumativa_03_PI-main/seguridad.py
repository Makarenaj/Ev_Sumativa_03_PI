"""Autenticacion y control de acceso para el mantenedor de calificaciones."""
from dataclasses import dataclass
import hashlib
import hmac
import os
import re


ROLES = frozenset({"corredor", "analista", "administrador"})
_ITERACIONES_HASH = 600_000
MAX_INTENTOS_FALLIDOS = 5       # intentos seguidos antes de bloquear la cuenta
MINUTOS_BLOQUEO = 15            # duracion del bloqueo
_PATRON_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ErrorValidacion(ValueError):
    """Entrada que no cumple las reglas de seguridad."""


class AccesoDenegado(PermissionError):
    """La sesion no tiene permisos para la operacion solicitada."""


class CuentaBloqueada(AccesoDenegado):
    """La cuenta esta bloqueada temporalmente por intentos fallidos."""


@dataclass(frozen=True)
class SesionUsuario:
    id_usuario: int
    id_corredora: int | None
    rol: str


def _validar_correo(correo):
    if not isinstance(correo, str):
        raise ErrorValidacion("El correo debe ser texto")
    correo = correo.strip().lower()
    if len(correo) > 150 or not _PATRON_CORREO.fullmatch(correo):
        raise ErrorValidacion("Correo invalido")
    return correo


def _validar_clave(clave):
    if not isinstance(clave, str) or not 8 <= len(clave) <= 1024:
        raise ErrorValidacion("La clave debe tener entre 8 y 1024 caracteres")
    return clave


def _validar_id(valor, nombre):
    if isinstance(valor, bool) or not isinstance(valor, int) or valor <= 0:
        raise ErrorValidacion(f"{nombre} debe ser un entero positivo")
    return valor


def hash_clave(clave):
    """Genera un hash PBKDF2 con sal aleatoria; nunca almacena la clave en claro."""
    clave = _validar_clave(clave)
    sal = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", clave.encode("utf-8"), sal, _ITERACIONES_HASH
    )
    return f"pbkdf2_sha256${_ITERACIONES_HASH}${sal.hex()}${digest.hex()}"


def verificar_clave(clave, hash_guardado):
    """Verifica hashes PBKDF2 producidos por hash_clave."""
    try:
        clave = _validar_clave(clave)
        algoritmo, iteraciones, sal_hex, digest_hex = hash_guardado.split("$")
        if algoritmo != "pbkdf2_sha256":
            return False
        iteraciones = int(iteraciones)
        sal = bytes.fromhex(sal_hex)
        digest_esperado = bytes.fromhex(digest_hex)
        if not 1 <= iteraciones <= 2_000_000 or len(sal) != 16:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", clave.encode("utf-8"), sal, iteraciones
        )
        return hmac.compare_digest(digest, digest_esperado)
    except (AttributeError, TypeError, ValueError):
        return False


# Hash de relleno: si el correo no existe igual se calcula un hash, para que
# la respuesta tarde lo mismo y no revele que cuentas existen.
_HASH_RELLENO = hash_clave("clave-de-relleno-sin-uso")


def autenticar(conn, correo, clave):
    """Devuelve el perfil activo o None si las credenciales no son validas.

    Tras MAX_INTENTOS_FALLIDOS claves erroneas seguidas la cuenta queda bloqueada
    MINUTOS_BLOQUEO minutos y se lanza CuentaBloqueada, aunque la clave sea correcta.
    conn es una conexion DB-API de PostgreSQL (por ejemplo, psycopg 3).
    """
    correo = _validar_correo(correo)
    clave = _validar_clave(clave)
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id_usuario, id_corredora, rol, clave_hash,
                   bloqueado_hasta IS NOT NULL AND bloqueado_hasta > now()
            FROM usuario
            WHERE correo = %s AND activo = TRUE
            """,
            (correo,),
        )
        fila = cursor.fetchone()
        if fila is None:
            verificar_clave(clave, _HASH_RELLENO)
            return None
        if fila[4]:
            raise CuentaBloqueada(
                f"Cuenta bloqueada por intentos fallidos. Intenta en {MINUTOS_BLOQUEO} minutos."
            )
        if not verificar_clave(clave, fila[3]):
            # Si el bloqueo anterior ya vencio, la cuenta de intentos parte de nuevo.
            cursor.execute(
                """
                UPDATE usuario
                SET intentos_fallidos = n.nuevo,
                    bloqueado_hasta = CASE WHEN n.nuevo >= %s
                                           THEN now() + make_interval(mins => %s) END
                FROM (
                    SELECT CASE WHEN bloqueado_hasta IS NOT NULL AND bloqueado_hasta <= now()
                                THEN 1 ELSE intentos_fallidos + 1 END AS nuevo
                    FROM usuario WHERE id_usuario = %s
                ) AS n
                WHERE id_usuario = %s
                """,
                (MAX_INTENTOS_FALLIDOS, MINUTOS_BLOQUEO, fila[0], fila[0]),
            )
            return None
        cursor.execute(
            """
            UPDATE usuario SET intentos_fallidos = 0, bloqueado_hasta = NULL
            WHERE id_usuario = %s
              AND (intentos_fallidos <> 0 OR bloqueado_hasta IS NOT NULL)
            """,
            (fila[0],),
        )
    return SesionUsuario(id_usuario=fila[0], id_corredora=fila[1], rol=fila[2])


def exigir_rol(sesion, *roles):
    """Deniega el acceso si la sesion no pertenece a uno de los roles indicados."""
    if not isinstance(sesion, SesionUsuario) or sesion.rol not in roles:
        raise AccesoDenegado("La operacion requiere un perfil autorizado")


def crear_usuario(conn, actor, nombre, correo, clave, rol, id_corredora=None):
    """Crea un perfil; solo un administrador autenticado puede aprovisionarlo."""
    exigir_rol(actor, "administrador")
    if not isinstance(nombre, str) or not 1 <= len(nombre.strip()) <= 100:
        raise ErrorValidacion("El nombre debe tener entre 1 y 100 caracteres")
    nombre = nombre.strip()
    correo = _validar_correo(correo)
    if not isinstance(rol, str) or rol not in ROLES:
        raise ErrorValidacion("Rol invalido")
    if rol == "corredor":
        id_corredora = _validar_id(id_corredora, "La corredora")
    elif id_corredora is not None:
        id_corredora = _validar_id(id_corredora, "La corredora")
    clave_hash = hash_clave(clave)

    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO usuario (id_corredora, nombre, correo, clave_hash, rol)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id_usuario
            """,
            (id_corredora, nombre, correo, clave_hash, rol),
        )
        fila = cursor.fetchone()
    return fila[0]


def listar_calificaciones(conn, sesion, id_corredora=None):
    """Lista calificaciones dentro del alcance del perfil autenticado.

    Corredores quedan limitados a su propia corredora incluso si solicitan otra.
    Analistas y administradores pueden consultar todas o filtrar por corredora.
    """
    if not isinstance(sesion, SesionUsuario) or sesion.rol not in ROLES:
        raise AccesoDenegado("Sesion invalida")
    if sesion.rol == "corredor":
        if id_corredora is not None and id_corredora != sesion.id_corredora:
            raise AccesoDenegado("No puede acceder a otra corredora")
        id_corredora = _validar_id(sesion.id_corredora, "La corredora de la sesion")
    elif id_corredora is not None:
        id_corredora = _validar_id(id_corredora, "La corredora")

    consulta = """
        SELECT id_calificacion, id_corredora, ejercicio, mercado, instrumento,
               fecha, secuencia
        FROM calificacion
    """
    if id_corredora is not None:
        consulta += " WHERE id_corredora = %s"
        parametros = (id_corredora,)
    else:
        parametros = ()
    consulta += " ORDER BY ejercicio DESC, instrumento"
    with conn.cursor() as cursor:
        cursor.execute(consulta, parametros)
        return cursor.fetchall()
