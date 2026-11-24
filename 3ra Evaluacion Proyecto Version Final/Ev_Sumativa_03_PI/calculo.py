"""Cálculo y validación de factores tributarios (Mantenedor de Calificaciones, NUAM).

factor = monto / suma de los montos de las columnas 8 a 19 (hojas 3 y 3.2 del HDU).
8 decimales, ningún factor mayor que 1 y la suma de 8 a 19 no puede pasar de 1.
Las decisiones del grupo están en DECISIONES.md. Se usa Decimal porque float pierde decimales.
"""
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP, InvalidOperation

DECIMALES = Decimal("0.00000001")          # 8 decimales
RANGO_SUMA = (8, 19)                       # columnas que entran en la suma
COLUMNAS = range(8, 38)                    # 8 a 37
COLUMNAS_CALCULADAS = range(8, 34)         # 8 a 33 (34 a 37 no tienen regla en el HDU)
UNO = Decimal("1")


class ErrorValidacion(ValueError):
    """Dato inválido: se muestra el mensaje y no se guarda nada."""


def _a_decimal(valor, nombre):
    try:
        d = Decimal(str(valor))
    except (InvalidOperation, ValueError):
        raise ErrorValidacion(f"{nombre}: valor no numérico ({valor!r})")
    if not d.is_finite():
        raise ErrorValidacion(f"{nombre}: valor no numérico ({valor!r})")
    return d


def calcular_factores(montos, metodo="mayor_resto"):
    """Calcula los factores desde un dict {columna: monto}. Lo que falte vale 0.
    metodo: 'mayor_resto' (suma exacta 1) o 'simple'. Las columnas 34 a 37 quedan en None."""
    if metodo not in ("mayor_resto", "simple"):
        raise ValueError("metodo debe ser 'mayor_resto' o 'simple'")
    m = {}
    for col in COLUMNAS:
        valor = _a_decimal(montos.get(col, 0), f"Monto columna {col}")
        if valor < 0:
            raise ErrorValidacion(f"Monto columna {col}: no puede ser negativo")
        m[col] = valor
    for col in montos:
        if col not in COLUMNAS:
            raise ErrorValidacion(f"Columna {col} fuera del rango 8 a 37")

    desde, hasta = RANGO_SUMA
    total = sum(m[c] for c in range(desde, hasta + 1))
    if total == 0:
        raise ErrorValidacion(
            f"La suma de los montos de las columnas {desde} a {hasta} es 0: no se pueden calcular los factores")

    exactos = {c: m[c] / total for c in COLUMNAS_CALCULADAS}
    if metodo == "simple":
        factores = {c: exactos[c].quantize(DECIMALES, rounding=ROUND_HALF_UP) for c in COLUMNAS_CALCULADAS}
    else:
        factores = {}
        for c in COLUMNAS_CALCULADAS:
            if desde <= c <= hasta:
                factores[c] = exactos[c].quantize(DECIMALES, rounding=ROUND_DOWN)
            else:
                factores[c] = exactos[c].quantize(DECIMALES, rounding=ROUND_HALF_UP)
        # redondeamos hacia abajo, así que faltan unos 0,00000001: se los sumamos
        # a los que perdieron más (si empatan, el de columna menor)
        faltante = int((UNO - sum(factores[c] for c in range(desde, hasta + 1))) / DECIMALES)
        restos = sorted(
            range(desde, hasta + 1),
            key=lambda c: (-(exactos[c] - factores[c]), c))
        for c in restos[:max(faltante, 0)]:
            factores[c] += DECIMALES
    # un monto fuera de 8-19 puede dar un factor > 1
    for c, f in factores.items():
        if f > UNO:
            raise ErrorValidacion(f"Factor {c}: debe estar entre 0 y 1")
    for c in COLUMNAS:
        factores.setdefault(c, None)
    return factores


def suma_factores(factores, desde=None, hasta=None):
    """Suma los factores del rango (por defecto 8 a 19). Los None no cuentan."""
    d, h = RANGO_SUMA
    desde, hasta = desde or d, hasta or h
    return sum((_a_decimal(factores[c], f"Factor {c}") for c in range(desde, hasta + 1)
                if factores.get(c) is not None), Decimal("0"))


def validar_factores(factores):
    """Valida factores ingresados a mano o de un CSV."""
    for c, v in factores.items():
        if c not in COLUMNAS:
            raise ErrorValidacion(f"Columna {c} fuera del rango 8 a 37")
        if v is None:
            continue
        d = _a_decimal(v, f"Factor {c}")
        if d < 0 or d > UNO:
            raise ErrorValidacion(f"Factor {c}: debe estar entre 0 y 1")
        if d != d.quantize(DECIMALES):
            raise ErrorValidacion(f"Factor {c}: máximo 8 decimales")
    suma = suma_factores(factores)
    if suma > UNO:
        raise ErrorValidacion(
            f"La suma de los factores {RANGO_SUMA[0]} a {RANGO_SUMA[1]} es {suma} y supera 1")
    return suma
