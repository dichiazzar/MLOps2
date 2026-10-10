import os

import pytest

SECRETO = "x" * 40


@pytest.fixture(autouse=True)
def _entorno(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", SECRETO)
    monkeypatch.setenv("LIMITE_POR_MINUTO", "60")


@pytest.fixture(scope="session")
def dataset_csv():
    ruta = os.environ.get("DATASET_CSV", "/datos/Car details v3.csv")
    if not os.path.exists(ruta):
        pytest.skip(f"no está el dataset en {ruta}")
    return ruta
