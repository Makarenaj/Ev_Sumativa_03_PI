"""Crea el primer usuario administrador de forma interactiva."""
import getpass
import os
import re
import sys

import psycopg
from psycopg.errors import UniqueViolation

from seguridad import ErrorValidacion, hash_clave


def main():
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("Define DATABASE_URL antes de crear el administrador.", file=sys.stderr)
        return 2

    nombre = input("Nombre del administrador: ").strip()
    correo = input("Correo del administrador: ").strip().lower()
    if not 1 <= len(nombre) <= 100 or not re.fullmatch(
        r"[^@\s]+@[^@\s]+\.[^@\s]+", correo
    ):
        print("Ingresa un nombre y correo validos.", file=sys.stderr)
        return 2
    clave = getpass.getpass("Clave (minimo 8 caracteres): ")
    confirmacion = getpass.getpass("Repite la clave: ")
    if clave != confirmacion:
        print("Las claves no coinciden.", file=sys.stderr)
        return 2

    try:
        clave_hash = hash_clave(clave)
    except ErrorValidacion as error:
        print(str(error), file=sys.stderr)
        return 2

    try:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(%s)", (741852963,))
                cursor.execute(
                    "SELECT EXISTS (SELECT 1 FROM usuario WHERE rol = 'administrador')"
                )
                if cursor.fetchone()[0]:
                    print(
                        "Ya existe un administrador; usa crear_usuario.py para altas posteriores.",
                        file=sys.stderr,
                    )
                    return 1
                cursor.execute(
                    """
                    INSERT INTO usuario (nombre, correo, clave_hash, rol)
                    VALUES (%s, %s, %s, 'administrador')
                    RETURNING id_usuario
                    """,
                    (nombre, correo, clave_hash),
                )
                id_usuario = cursor.fetchone()[0]
    except UniqueViolation:
        print("Ya existe un usuario con ese correo.", file=sys.stderr)
        return 1

    print(f"Administrador creado (id_usuario={id_usuario}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
