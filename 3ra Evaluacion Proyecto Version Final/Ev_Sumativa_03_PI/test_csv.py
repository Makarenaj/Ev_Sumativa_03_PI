"""Pruebas de la lectura y validacion del CSV de la carga masiva (no usan la base de datos)."""
import csv
import io
from decimal import Decimal as D

import pytest

import carga_csv
from carga_csv import CABECERA, leer_csv


def fila(**cambios):
    valores = {"ejercicio": "2024", "mercado": "acn", "instrumento": "Prueba", "fecha": "2024-06-30",
               "secuencia": "20001", "tipo_sociedad": "a", "factor_8": "0.5", "factor_9": "0.5"}
    valores.update(cambios)
    return [valores.get(columna, "") for columna in CABECERA]


def texto(filas, delimitador=",", cabecera=CABECERA):
    salida = io.StringIO(newline="")
    escritor = csv.writer(salida, delimiter=delimitador, lineterminator="\n")
    escritor.writerow(cabecera)
    escritor.writerows(filas)
    return salida.getvalue()


def test_ejemplo_del_sistema_es_valido():
    resultado = leer_csv(carga_csv.ejemplo_csv())
    assert resultado.valido and resultado.total == 3
    copec = resultado.filas[0]
    assert copec["factores"][8] == D("0.52277431") and copec["factores"][25] == D("0.19335488")


def test_ejemplo_con_error_se_rechaza_y_dice_la_fila():
    resultado = leer_csv(carga_csv.ejemplo_csv(con_error=True))
    assert not resultado.valido and resultado.filas_invalidas == 1
    assert resultado.errores[0][0] == 3 and "supera 1" in resultado.errores[0][1]


def test_se_normalizan_mercado_y_tipo_de_sociedad():
    campos = leer_csv(texto([fila()])).filas[0]["campos"]
    assert campos["mercado"] == "ACN" and campos["tipo_sociedad"] == "A"


def test_suma_exactamente_uno_pasa_y_uno_con_un_decimal_mas_no():
    assert leer_csv(texto([fila(factor_8="0.50000000", factor_9="0.50000000")])).valido
    resultado = leer_csv(texto([fila(factor_8="0.50000000", factor_9="0.50000001")]))
    assert not resultado.valido and "supera 1" in resultado.errores[0][1]


@pytest.mark.parametrize("cambios, parte", [
    ({"factor_8": "1.5"}, "máximo"),
    ({"factor_8": "-0.2"}, "número válido"),
    ({"factor_8": "abc"}, "número válido"),
    ({"factor_8": "0.123456789"}, "8 decimales"),
    ({"secuencia": "10000"}, "entre 10001"),
    ({"secuencia": "abc"}, "entero"),
    ({"ejercicio": "1800"}, "entre 1900"),
    ({"mercado": "ABCD"}, "mercado"),
    ({"mercado": ""}, "mercado"),
    ({"instrumento": ""}, "instrumento"),
    ({"instrumento": "x" * 51}, "instrumento"),
    ({"fecha": "30/13/2024"}, "fecha"),
    ({"tipo_sociedad": "Z"}, "tipo_sociedad"),
    ({"valor_historico": "1.234"}, "decimales"),
    ({"numero_dividendo": "-1"}, "entero"),
])
def test_cada_regla_rechaza_su_caso(cambios, parte):
    resultado = leer_csv(texto([fila(**cambios)]))
    assert not resultado.valido
    assert any(parte in mensaje for _, mensaje in resultado.errores)


@pytest.mark.parametrize("fecha", ["2024-06-30", "30-06-2024", "30/06/2024"])
def test_formatos_de_fecha_aceptados(fecha):
    assert leer_csv(texto([fila(fecha=fecha)])).filas[0]["campos"]["fecha"].isoformat() == "2024-06-30"


def test_factores_34_a_37_solo_se_guardan_si_traen_valor():
    sin = leer_csv(texto([fila()])).filas[0]["factores"]
    con = leer_csv(texto([fila(factor_34="0.4", factor_37="0.1")])).filas[0]["factores"]
    assert all(c not in sin for c in range(34, 38)) and all(c in sin for c in range(8, 34))
    assert con[34] == D("0.4") and con[37] == D("0.1") and 35 not in con


def test_los_factores_fuera_del_rango_de_la_suma_no_la_afectan():
    # 20 a 33 son creditos: pueden sumar mas que 1 sin romper la regla (solo cuenta 8 a 19)
    assert leer_csv(texto([fila(factor_20="0.9", factor_21="0.9")])).valido


def test_punto_y_coma_con_decimal_coma():
    resultado = leer_csv(texto([fila(factor_8="0,25", factor_9="0,75")], delimitador=";"))
    assert resultado.valido and resultado.filas[0]["factores"][8] == D("0.25")


def test_con_coma_como_separador_no_se_acepta_decimal_coma():
    assert not leer_csv(texto([fila(factor_8='"0,5"', factor_9="0.5")])).valido


def test_bom_y_filas_vacias_se_ignoran():
    contenido = "\ufeff" + texto([fila(), [""] * len(CABECERA), fila(instrumento="Otra", secuencia="20002")])
    resultado = leer_csv(contenido)
    assert resultado.valido and resultado.total == 2


def test_llave_repetida_en_el_archivo_se_rechaza():
    resultado = leer_csv(texto([fila(), fila()]))
    assert not resultado.valido and "repite la llave" in resultado.errores[0][1]


def test_columnas_faltantes_sobrantes_o_repetidas():
    assert "faltan" in leer_csv("ejercicio,mercado\n2024,ACN").error_formato
    assert "no reconocidas" in leer_csv(texto([fila() + ["x"]], cabecera=list(CABECERA) + ["extra"])).error_formato
    assert "repetidas" in leer_csv(texto([fila() + ["0"]], cabecera=list(CABECERA) + ["factor_8"])).error_formato


def test_fila_con_columnas_de_menos():
    resultado = leer_csv(texto([fila()[:-3]]))
    assert not resultado.valido and "columnas" in resultado.errores[0][1]


def test_archivo_vacio_o_solo_encabezado():
    assert leer_csv("").error_formato and leer_csv("  \n \n").error_formato
    assert "no tiene filas" in leer_csv(texto([])).error_formato


def test_maximo_de_filas():
    filas = [fila(instrumento=f"I{n}", secuencia=str(20000 + n)) for n in range(carga_csv.MAXIMO_FILAS + 1)]
    assert "máximo" in leer_csv(texto(filas)).error_formato


def test_una_fila_invalida_basta_para_rechazar_todo():
    resultado = leer_csv(texto([fila(), fila(instrumento="Mala", secuencia="20002", factor_8="2"), fila(instrumento="Buena", secuencia="20003")]))
    assert not resultado.valido and resultado.filas_invalidas == 1 and len(resultado.filas) == 2
    assert "Fila 3" in resultado.resumen_error()
