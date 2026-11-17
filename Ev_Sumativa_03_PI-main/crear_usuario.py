"""Permite a un administrador aprovisionar perfiles desde la terminal."""
import getpass
import os
import sys

import psycopg
from psycopg.errors import UniqueViolation

from seguridad import (
    AccesoDenegado,
    ErrorValidacion,
    autenticar,
    crear_usuario,
)


def main():
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("Define DATABASE_URL antes de crear usuarios.", file=sys.stderr)
        return 2

    correo_admin = input("Correo del administrador: ").strip()
    clave_admin = getpass.getpass("Clave del administrador: ")
    nombre = input("Nombre del nuevo usuario: ").strip()
    correo = input("Correo del nuevo usuario: ").strip()
    rol = input("Perfil (corredor, analista, administrador): ").strip().lower()
    id_corredora = None
    if rol == "corredor":
        try:
            id_corredora = int(input("ID de la corredora: ").strip())
        except ValueError:
            print("El ID de corredora debe ser un entero.", file=sys.stderr)
            return 2
    clave = getpass.getpass("Clave nueva (minimo 8 caracteres): ")
    confirmacion = getpass.getpass("Repite la clave nueva: ")
    if clave != confirmacion:
        print("Las claves no coinciden.", file=sys.stderr)
        return 2

    try:
        with psycopg.connect(dsn) as conn:
            actor = autenticar(conn, correo_admin, clave_admin)
            if actor is None:
                print("Credenciales de administrador incorrectas.", file=sys.stderr)
                return 1
            id_usuario = crear_usuario(
                conn, actor, nombre, correo, clave, rol, id_corredora
            )
    except (AccesoDenegado, ErrorValidacion) as error:
        print(str(error), file=sys.stderr)
        return 2
    except UniqueViolation:
        print("Ya existe un usuario con ese correo.", file=sys.stderr)
        return 1

    print(f"Usuario creado (id_usuario={id_usuario}, rol={rol}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
