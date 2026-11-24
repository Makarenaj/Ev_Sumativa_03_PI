"""Pruebas del cálculo de factores. Ejecutar: python -m pytest -v"""
from decimal import Decimal as D
import pytest
import calculo
from calculo import calcular_factores, validar_factores, suma_factores, ErrorValidacion

# Ejemplo resuelto de la hoja 3.2 del HDU (suma de las columnas 8 a 19 = 368.745.318)
MONTOS_HDU = {8: 192770580, 9: 64161878, 10: 0, 11: 111812860, 25: 71298705, 30: 15837333}
ESPERADOS_HDU = {8: D("0.52277431"), 9: D("0.17400052"), 10: D("0.00000000"),
                 11: D("0.30322517"), 25: D("0.19335488"), 30: D("0.04294924")}


def test_flujo_ideal_ejemplo_hdu():
    f = calcular_factores(MONTOS_HDU)
    for col, esperado in ESPERADOS_HDU.items():
        assert f[col] == esperado, f"factor {col}"


def test_suma_exactamente_uno_pasa():
    f = calcular_factores(MONTOS_HDU)
    assert suma_factores(f) == D("1.00000000")
    assert validar_factores(f) == D("1.00000000")


def test_suma_mayor_que_uno_se_rechaza():
    f = {8: D("0.50000000"), 9: D("0.50000001")}
    with pytest.raises(ErrorValidacion, match="supera 1"):
        validar_factores(f)


def test_suma_menor_que_uno_pasa():
    assert validar_factores({8: D("0.4"), 9: D("0.3")}) == D("0.7")


def test_seis_montos_iguales_mayor_resto_da_uno_exacto():
    f = calcular_factores({c: 100 for c in range(8, 14)}, metodo="mayor_resto")
    assert suma_factores(f) == D("1.00000000")
    assert sorted(f[c] for c in range(8, 14)) == [D("0.16666666")] * 2 + [D("0.16666667")] * 4


def test_seis_montos_iguales_redondeo_simple_se_pasa_de_uno():
    # Es el caso borde del HDU: 6 x 0,16666667 = 1,00000002
    f = calcular_factores({c: 100 for c in range(8, 14)}, metodo="simple")
    assert suma_factores(f) == D("1.00000002")
    with pytest.raises(ErrorValidacion):
        validar_factores(f)


def test_suma_de_montos_cero_no_divide():
    with pytest.raises(ErrorValidacion, match="es 0"):
        calcular_factores({8: 0, 9: 0})
    with pytest.raises(ErrorValidacion, match="es 0"):
        calcular_factores({25: 1000})      # monto solo fuera del rango 8 a 19


def test_monto_negativo_o_no_numerico():
    with pytest.raises(ErrorValidacion, match="negativo"):
        calcular_factores({8: -5, 9: 10})
    with pytest.raises(ErrorValidacion, match="no numérico"):
        calcular_factores({8: "abc"})


def test_mas_de_ocho_decimales_se_rechaza():
    with pytest.raises(ErrorValidacion, match="8 decimales"):
        validar_factores({8: D("0.123456789")})


def test_factor_mayor_que_uno_se_rechaza():
    with pytest.raises(ErrorValidacion, match="entre 0 y 1"):
        validar_factores({8: D("1.5")})


def test_factores_34_a_37_no_se_calculan():
    f = calcular_factores(MONTOS_HDU)
    assert all(f[c] is None for c in range(34, 38))
    assert f[33] is not None


def test_rango_8_a_16_da_lo_mismo_con_el_ejemplo_hdu():
    f = calcular_factores(MONTOS_HDU)
    assert suma_factores(f, 8, 16) == suma_factores(f, 8, 19)


def test_solo_decimal_no_float():
    f = calcular_factores(MONTOS_HDU)
    assert all(isinstance(v, D) for v in f.values() if v is not None)
