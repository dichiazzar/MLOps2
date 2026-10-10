# REST (clase1)

Esta capa **no tiene código propio en esta carpeta**: es la API REST que ya existía en el TP
integrador, implementada en [`../../MLOps1_final/api`](../../MLOps1_final/api). A diferencia de
GraphQL, gRPC y Streaming —que sí son puertas de entrada nuevas agregadas en esta carpeta—, REST
fue el diseño original del TP y no se reimplementa: se reusa tal cual.

| | |
|---|---|
| Código fuente | `../../MLOps1_final/api/app/main.py` (+ `predict.py`, `db.py`, `models_orm.py`) |
| Dockerfile | [`./Dockerfile`](./Dockerfile) (copia la API de MLOps1_final y cambia solo `predict.py`) |
| Puerto | `8010` en este proyecto (la misma API usa el `8000` en el stack de `MLOps1_final`) |
| Endpoints | `GET /health`, `GET /model/info`, `POST /predict`, `GET /predictions/recent` |
| Mini-TP de origen | [`clase1/API_MLOPS2.ipynb`](../../../clase1/API_MLOPS2.ipynb) |
| Seguridad (clase 7) | [`app/seguro.py`](./app/seguro.py) envuelve la API con [`app/seguridad_rest.py`](./app/seguridad_rest.py) |

El servicio `rest` en el [`docker-compose.yml`](../docker-compose.yml) de esta carpeta usa un
[`Dockerfile`](./Dockerfile) propio, que copia la API de `../../MLOps1_final/api` tal cual (mismo
código, mismas dependencias), sin duplicarla en el repo. La única diferencia es `predict.py`: se
reemplaza por la versión de MLOps2 ([`../datalake/compartido/predict.py`](../datalake/compartido/predict.py)),
que lee la metadata del modelo desde MLflow en vez de recalcularla al arrancar (clase 6). Las otras
tres capas usan el mismo reemplazo. El stack base (`../../MLOps1_final/docker-compose.yml`) sigue
levantando su API REST original en el puerto 8000.

**Seguridad (clase 7).** La API se sirve con `uvicorn app.seguro:app`: un middleware ASGI que
envuelve la API de MLOps1 **sin modificar su código** y le agrega token JWT con rol (401/403),
validación estricta del auto con los rangos de entrenamiento (422), cuerpo de 16 KB como máximo
(413), un límite de pedidos por usuario (429) y la auditoría de cada pedido en el Data Lake.
`GET /health` y `/docs` siguen siendo públicos. Ver la sección 6 de [`../README.md`](../README.md).

Ver la comparación completa de las 4 capas en [`../README.md`](../README.md) y el diseño en
[`../Diseño de arquitectura.md`](../Diseño%20de%20arquitectura.md).
