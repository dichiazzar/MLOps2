from graphql import parse

from app.costo import COSTO_MAX, costo_documento

AUTO = ('{name: "M", year: 2014, kmDriven: 1, fuel: diesel, sellerType: individual, transmission: manual, '
        'owner: first, mileage: "23.4 kmpl", engine: "1248 CC", maxPower: "74 bhp", torque: "190Nm", seats: 5}')


def c(q):
    return costo_documento(parse(q))


def test_campos_simples():
    assert c("{ modelInfo { modelName modelVersion } }") == 3


def test_predict_cuesta_10():
    assert c(f"mutation {{ predict(car: {AUTO}) {{ predictedPrice modelVersion }} }}") == 12


def test_alias_en_masa():
    q = "mutation { " + " ".join(f"p{i}: predict(car: {AUTO}) {{ predictedPrice }}" for i in range(25)) + " }"
    assert c(q) == 25 * 11 > COSTO_MAX
    q15 = "mutation { " + " ".join(f"p{i}: predict(car: {AUTO}) {{ predictedPrice }}" for i in range(15)) + " }"
    assert c(q15) == 165 <= COSTO_MAX


def test_lista_se_multiplica_por_limite():
    base = "{ prediccionesStreaming(limite: %s) { fecha total items { name kmDriven predictedPrice } } }"
    assert c(base % 20) == 1 + 1 + 1 + (1 + 20 * 3)          # 64
    assert c(base % 100) > COSTO_MAX


def test_limite_por_defecto():
    assert c("{ prediccionesStreaming { items { name } } }") == 1 + (1 + 20 * 1)


def test_costo_fragmentos_y_variables():
    q = """
    query($n: Int) { prediccionesStreaming(limite: $n) { ...F } }
    fragment F on ResumenStreaming { items { name kmDriven predictedPrice modelVersion } }
    """
    assert c(q) == 1 + (1 + 500 * 4)                            # variable = peor caso (500)
    q2 = "{ ...G } fragment G on Query { prediccionesStreaming(limite: 50) { items { name } } }"
    assert c(q2) == 1 + (1 + 50 * 1)
