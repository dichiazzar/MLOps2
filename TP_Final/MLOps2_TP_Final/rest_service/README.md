# REST (clase1)

Esta capa **no tiene código propio en esta carpeta**: es la API REST que ya existía en el TP
integrador, implementada en [`../../MLOps1_final/api`](../../MLOps1_final/api). A diferencia de
GraphQL, gRPC y Streaming —que sí son puertas de entrada nuevas agregadas en esta carpeta—, REST
fue el diseño original del TP y no se reimplementa: se reusa tal cual.

| | |
|---|---|
| Código fuente | `../../MLOps1_final/api/app/main.py` (+ `predict.py`, `db.py`, `models_orm.py`) |
| Dockerfile | `../../MLOps1_final/api/Dockerfile` |
| Puerto | `8010` en este proyecto (la misma API usa el `8000` en el stack de `MLOps1_final`) |
| Endpoints | `GET /health`, `GET /model/info`, `POST /predict`, `GET /predictions/recent` |
| Mini-TP de origen | `clase1/Practica/API_MLOPS2.ipynb` |

El servicio `rest` en el [`docker-compose.yml`](../docker-compose.yml) de esta carpeta apunta
directamente a ese Dockerfile y contexto — no copia ni duplica el código — para que las 4 capas
se puedan levantar juntas desde acá. El stack base (`../../MLOps1_final/docker-compose.yml`)
también puede levantar la API REST por su cuenta; ambos compose construyen la misma imagen a
partir de la misma fuente.

Ver la comparación completa de las 4 capas en [`../README.md`](../README.md) y el diseño en
[`../Diseño de arquitectura.md`](../Diseño%20de%20arquitectura.md).
