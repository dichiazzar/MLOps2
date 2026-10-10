"""La API REST de MLOps1_final, servida con la capa de seguridad de la clase 7.

    uvicorn app.seguro:app

No cambia el código de la API: la importa tal cual y la envuelve con SeguridadREST.
"""

import app.main as api_mlops1
from app import lago
from app.predict import rangos_entrada
from app.seguridad import Auditor, LimiteDeTasa
from app.seguridad_rest import SeguridadREST


def _version():
    return api_mlops1._state.model_version if api_mlops1._state else None


app = SeguridadREST(api_mlops1.app, auditor=Auditor("rest", lago.subir_bytes), limite=LimiteDeTasa(),
                    rangos=rangos_entrada, version=_version)
