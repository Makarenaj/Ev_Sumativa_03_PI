"""Genera un CSV de prueba con muchas filas validas (por defecto 1.000) para la prueba de estres.

Uso:  python ejemplos/generar_csv_estres.py 1000 > ejemplos/carga_estres_1000.csv
"""
import csv
import sys

sys.path.insert(0, ".")
import carga_csv  # noqa: E402

cantidad = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
escritor = csv.writer(sys.stdout, lineterminator="\n")
escritor.writerow(carga_csv.CABECERA)
for n in range(cantidad):
    fila = {c: "" for c in carga_csv.CABECERA}
    fila.update(ejercicio="2024", mercado="ACN", instrumento=f"Estres{n:04d}", fecha="2024-06-30",
                secuencia=str(100000 + n), tipo_sociedad="A", factor_8="0.5", factor_9="0.5")
    escritor.writerow([fila[c] for c in carga_csv.CABECERA])
