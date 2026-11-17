"""Cambia la clave de una cuenta con autorización de un administrador."""
import getpass
import os
import sys

import psycopg

from seguridad import AccesoDenegado, ErrorValidacion, autenticar, exigir_rol, hash_clave


def main():
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("Define DATABASE_URL antes de cambiar claves.", file=sys.stderr)
        return 2

    correo_admin = input("Correo del administrador: ").strip()
    clave_admin = getpass.getpass("Clave del administrador: ")
    correo_objetivo = input("Correo de la cuenta a cambiar: ").strip().lower()
    nueva_clave = getpass.getpass("Nueva clave: ")
    if nueva_clave != getpass.getpass("Repite la nueva clave: "):
        print("Las claves no coinciden.", file=sys.stderr)
        return 2

    try:
        clave_hash = hash_clave(nueva_clave)
        with psycopg.connect(dsn) as conn:
            actor = autenticar(conn, correo_admin, clave_admin)
            if actor is None:
                print("Credenciales de administrador incorrectas.", file=sys.stderr)
                return 1
            exigir_rol(actor, "administrador")
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE usuario SET clave_hash = %s
                    WHERE correo = %s AND activo = TRUE
                    RETURNING id_usuario
                    """,
                    (clave_hash, correo_objetivo),
                )
                actualizado = cursor.fetchone()
    except (AccesoDenegado, ErrorValidacion) as error:
        print(str(error), file=sys.stderr)
        return 2

    if actualizado is None:
        print("No se encontro una cuenta activa con ese correo.", file=sys.stderr)
        return 1
    print(f"Clave actualizada (id_usuario={actualizado[0]}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
