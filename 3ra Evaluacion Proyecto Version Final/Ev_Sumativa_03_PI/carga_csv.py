"""Lectura y validacion del archivo CSV de la carga masiva (formato de la hoja 3.1 del HDU).

Reglas del grupo:
  - El archivo se rechaza COMPLETO si una sola fila es invalida: no se guarda nada
    hasta que el archivo este totalmente valido.
  - Separador coma (decimales con punto) o punto y coma (decimales con coma, como
    lo exporta Excel en Chile). Codificacion UTF-8.
  - Cada fila lleva los datos de la calificacion y sus factores 8 al 37 (vacio = 0).
  - Los factores 34 al 37 solo se guardan si vienen con valor (el HDU no define su regla).
  - La suma de los factores 8 al 19 no puede superar 1 (misma regla del mantenedor).
Este modulo no usa la base de datos, asi se puede probar solo.
"""
import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

import calculo

CABECERA = (
    "ejercicio", "mercado", "instrumento", "fecha", "secuencia",
    "numero_dividendo", "tipo_sociedad", "valor_historico",
) + tuple(f"factor_{columna}" for columna in range(8, 38))
COLUMNAS_CON_FORMULA = range(8, 34)     # 8 a 33 siempre se guardan (vacio = 0)
MAXIMO_FILAS = 5000
SECUENCIA_MINIMA = 10_001               # el flujo ideal pide secuencia mayor que 10.000
MAXIMO_MONTO = Decimal("9999999999999999.99")
MAXIMO_DIVIDENDO = 9_999_999_999


@dataclass
class ResultadoCsv:
    filas: list = field(default_factory=list)     # filas validas: {"linea", "campos", "factores"}
    errores: list = field(default_factory=list)   # (linea, mensaje)
    total: int = 0                                # filas de datos leidas
    error_formato: str = ""                       # problema que impide leer el archivo

    @property
    def valido(self):
        return not self.error_formato and not self.errores and self.total > 0

    @property
    def filas_invalidas(self):
        return len({linea for linea, _ in self.errores})

    def resumen_error(self, maximo=5):
        if self.error_formato:
            return self.error_formato
        partes = [f"Fila {linea}: {mensaje}" for linea, mensaje in self.errores[:maximo]]
        if len(self.errores) > maximo:
            partes.append(f"... y {len(self.errores) - maximo} errores más")
        return " | ".join(partes)


def _numero(texto, nombre, decimales, maximo, decimal_coma):
    texto = (texto or "").strip()
    if decimal_coma:
        texto = texto.replace(",", ".")
    if not re.fullmatch(r"[0-9]+(\.[0-9]+)?", texto):
        raise ValueError(f"{nombre}: no es un número válido")
    numero = Decimal(texto)
    if numero.as_tuple().exponent < -decimales:
        raise ValueError(f"{nombre}: admite como máximo {decimales} decimales")
    if numero > maximo:
        raise ValueError(f"{nombre}: excede el máximo permitido")
    return numero


def _entero(texto, nombre, minimo, maximo):
    texto = (texto or "").strip()
    if not re.fullmatch(r"[0-9]+", texto):
        raise ValueError(f"{nombre}: debe ser un número entero")
    numero = int(texto)
    if numero < minimo or numero > maximo:
        raise ValueError(f"{nombre}: debe estar entre {minimo} y {maximo}")
    return numero


def _fecha(texto):
    texto = (texto or "").strip()
    for formato in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    raise ValueError("fecha: usa el formato aaaa-mm-dd o dd-mm-aaaa")


def validar_fila_csv(fila, decimal_coma=False):
    """Valida una fila (dict columna -> texto). Devuelve (datos, errores).

    datos = {"campos": {...}, "factores": {8: Decimal, ...}} si no hay errores.
    """
    errores = []

    def intentar(funcion, *argumentos):
        try:
            return funcion(*argumentos)
        except ValueError as error:
            errores.append(str(error))
            return None

    ejercicio = intentar(_entero, fila.get("ejercicio"), "ejercicio", 1900, 2100)
    mercado = (fila.get("mercado") or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{1,3}", mercado):
        errores.append("mercado: debe tener entre 1 y 3 letras o números")
    instrumento = (fila.get("instrumento") or "").strip()
    if not 1 <= len(instrumento) <= 50:
        errores.append("instrumento: debe tener entre 1 y 50 caracteres")
    fecha = intentar(_fecha, fila.get("fecha"))
    secuencia = intentar(_entero, fila.get("secuencia"), "secuencia", SECUENCIA_MINIMA, 9_999_999_999)
    dividendo = None
    if (fila.get("numero_dividendo") or "").strip():
        dividendo = intentar(_entero, fila.get("numero_dividendo"), "numero_dividendo", 0, MAXIMO_DIVIDENDO)
    tipo = (fila.get("tipo_sociedad") or "").strip().upper() or None
    if tipo not in (None, "A", "C"):
        errores.append("tipo_sociedad: debe ser A o C")
    valor_historico = None
    if (fila.get("valor_historico") or "").strip():
        valor_historico = intentar(_numero, fila.get("valor_historico"), "valor_historico", 2, MAXIMO_MONTO, decimal_coma)

    factores = {}
    for columna in range(8, 38):
        nombre = f"factor_{columna}"
        texto = (fila.get(nombre) or "").strip()
        if not texto:
            if columna in COLUMNAS_CON_FORMULA:
                factores[columna] = Decimal("0")
            continue
        valor = intentar(_numero, texto, nombre, 8, Decimal(1), decimal_coma)
        if valor is not None:
            factores[columna] = valor
    if not errores:
        try:
            calculo.validar_factores(factores)
        except calculo.ErrorValidacion as error:
            errores.append(str(error))
    if errores:
        return None, errores
    campos = {
        "ejercicio": ejercicio, "mercado": mercado, "instrumento": instrumento,
        "fecha": fecha, "secuencia": secuencia, "numero_dividendo": dividendo,
        "tipo_sociedad": tipo, "valor_historico": valor_historico,
    }
    return {"campos": campos, "factores": factores}, []


def leer_csv(texto):
    """Lee y valida el CSV completo. No toca la base de datos."""
    resultado = ResultadoCsv()
    texto = (texto or "").lstrip("\ufeff")
    primera = next((linea for linea in texto.splitlines() if linea.strip()), "")
    if not primera:
        resultado.error_formato = "El archivo está vacío."
        return resultado
    delimitador = ";" if primera.count(";") > primera.count(",") else ","
    lector = csv.reader(io.StringIO(texto, newline=""), delimiter=delimitador)
    cabecera = None
    vistas = {}
    try:
        for fila in lector:
            if not fila or all(not celda.strip() for celda in fila):
                continue
            linea = lector.line_num
            if cabecera is None:
                cabecera = [celda.strip().lower() for celda in fila]
                faltan = [c for c in CABECERA if c not in cabecera]
                sobran = [c for c in cabecera if c not in CABECERA]
                if faltan or sobran or len(set(cabecera)) != len(cabecera):
                    detalle = []
                    if faltan:
                        detalle.append("faltan las columnas " + ", ".join(faltan[:5]) + ("..." if len(faltan) > 5 else ""))
                    if sobran:
                        detalle.append("columnas no reconocidas: " + ", ".join(sobran[:5]))
                    if len(set(cabecera)) != len(cabecera):
                        detalle.append("hay columnas repetidas")
                    resultado.error_formato = "Formato incorrecto: " + "; ".join(detalle) + "."
                    return resultado
                continue
            resultado.total += 1
            if resultado.total > MAXIMO_FILAS:
                resultado.error_formato = f"El archivo supera el máximo de {MAXIMO_FILAS} filas."
                return resultado
            if len(fila) != len(cabecera):
                resultado.errores.append((linea, f"tiene {len(fila)} columnas y se esperaban {len(cabecera)}"))
                continue
            datos, errores = validar_fila_csv(dict(zip(cabecera, fila)), decimal_coma=(delimitador == ";"))
            for mensaje in errores:
                resultado.errores.append((linea, mensaje))
            if datos is None:
                continue
            campos = datos["campos"]
            llave = (campos["ejercicio"], campos["mercado"], campos["instrumento"], campos["secuencia"])
            if llave in vistas:
                resultado.errores.append((linea, f"repite la llave de la fila {vistas[llave]} (ejercicio, mercado, instrumento y secuencia)"))
                continue
            vistas[llave] = linea
            datos["linea"] = linea
            resultado.filas.append(datos)
    except csv.Error as error:
        resultado.error_formato = f"El archivo no se pudo leer como CSV: {error}"
        return resultado
    if cabecera is None:
        resultado.error_formato = "El archivo está vacío."
    elif resultado.total == 0:
        resultado.error_formato = "El archivo no tiene filas de datos."
    return resultado


def _fila_ejemplo(ejercicio, mercado, instrumento, fecha, secuencia, tipo, factores):
    valores = {f"factor_{c}": "" for c in range(8, 38)}
    valores.update({f"factor_{c}": v for c, v in factores.items()})
    base = [str(ejercicio), mercado, instrumento, fecha, str(secuencia), "", tipo, ""]
    return base + [valores[f"factor_{c}"] for c in range(8, 38)]


def ejemplo_csv(con_error=False):
    """CSV de ejemplo: el ejemplo resuelto del HDU y dos calificaciones mas."""
    filas = [
        _fila_ejemplo(2023, "ACN", "Copec", "2023-12-12", 123123, "A",
                      {8: "0.52277431", 9: "0.17400052", 10: "0", 11: "0.30322517", 25: "0.19335488", 30: "0.04294924"}),
        _fila_ejemplo(2024, "ACN", "Cencosud", "2024-06-30", 20001, "A",
                      {8: "0.7", 9: "0.5"} if con_error else {8: "0.5", 9: "0.5"}),
        _fila_ejemplo(2024, "ACN", "Falabella", "2024-06-30", 20002, "C",
                      {8: "0.25", 9: "0.25", 10: "0.25", 11: "0.25"}),
    ]
    salida = io.StringIO(newline="")
    escritor = csv.writer(salida, lineterminator="\n")
    escritor.writerow(CABECERA)
    escritor.writerows(filas)
    return salida.getvalue()
