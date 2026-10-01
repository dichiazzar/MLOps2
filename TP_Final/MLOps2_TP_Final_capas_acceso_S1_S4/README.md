# Capas de acceso: REST · GraphQL · gRPC · Streaming

Implementación de [`Diseño de arquitectura.md`](./Diseño%20de%20arquitectura.md): cuatro formas de
acceder al mismo modelo (`xgb_best`) del TP integrador (`../MLOps1_final`), una por cada mini-TP de
la cursada. Ninguna capa reimplementa la carga ni el scoring del modelo — todas reusan
`api/app/predict.py` y `common/` de `MLOps1_final` sin copiarlos.

| Capa | Puerto (esta carpeta) | Origen del código | Qué demuestra |
|---|---|---|---|
| **REST** | 8010 | `rest_service/` → mismo Dockerfile/código de `../MLOps1_final/api` (no se reimplementa) | petición → respuesta simple (`clase1/Practica/API_MLOPS2.ipynb`) |
| **GraphQL** | 8001 | `graphql_service/` | el cliente elige qué campos pedir (`clase2/.../mini_tp2_actividad.ipynb`) |
| **gRPC** | 50051 | `grpc_service/` | contrato tipado + unary + server-streaming (`clase3/.../mini_tp3_actividad.ipynb`) |
| **Streaming** | — (consume de Redpanda) | `streaming_service/` | scoring online + métricas por ventana + alerta de drift (`clase4/.../mini_tp4_actividad.ipynb`) |

> REST no es una capa nueva: reusa el mismo código y Dockerfile que ya existía en
> `MLOps1_final/api`, solo expuesto acá en el puerto 8010 (no 8000) para poder levantar las 4
> capas desde este único compose sin chocar de puerto si `MLOps1_final` también tiene su propia
> API arriba a la vez. Ver [`rest_service/README.md`](./rest_service/README.md).

## 1. Requisitos previos

El stack base (Postgres, MinIO, MLflow, Airflow) tiene que estar corriendo, con el modelo
`xgb_best` ya entrenado y en stage **Production** en MLflow Registry. No hace falta levantar el
servicio `api` de ese compose — esta carpeta construye su propia copia en el puerto 8010:

```bash
cd ../MLOps1_final
docker compose up -d postgres minio init-minio mlflow airflow-init airflow-webserver airflow-scheduler
# disparar el DAG de entrenamiento una vez (UI de Airflow en :8080, o `scripts/smoke_test.sh`)
```

## 2. Levantar las cuatro capas

```bash
cd ../capas_acceso_S1_S4
docker compose up -d --build
```

Esto levanta `rest`, `graphql`, `grpc`, `redpanda` y `streaming-consumer` en la misma red Docker
que `mlflow`/`minio` (`mlops-net` de `MLOps1_final`), sin duplicar esos servicios.

> Si tu carpeta del TP integrador no se llama exactamente `MLOps1_final`, ajustá el nombre de red
> en `docker-compose.yml` (`networks.mlops-net.name`) al que muestre `docker network ls`.

## 3. Probar cada capa

**REST** — `curl -X POST http://localhost:8010/predict -H "Content-Type: application/json" -d '{
  "name": "Maruti Swift Dzire VDI",
  "year": 2010,
  "km_driven": 15000,
  "fuel": "Petrol",
  "seller_type": "Individual",
  "transmission": "Manual",
  "owner": "First Owner",
  "mileage": "23.4 kmpl",
  "engine": "1248 CC",
  "max_power": "74 bhp",
  "torque": "190Nm@ 2000rpm",
  "seats": 1
}'`
(mismos endpoints y payload que `MLOps1_final/api`, ver su README).

**GraphQL** — abrir `http://localhost:8001/graphql` (GraphiQL incluido) y correr alguno de estos dos queries:

```graphql
query {
  modelInfo { modelName modelVersion nFeatures }
}

mutation {
  predict(car: {
    name: "Maruti Swift Dzire VDI", year: 2014, kmDriven: 145500,
    fuel: DIESEL, sellerType: INDIVIDUAL, transmission: MANUAL, owner: FIRST,
    mileage: "23.4 kmpl", engine: "1248 CC", maxPower: "74 bhp",
    torque: "190Nm@ 2000rpm", seats: 5
  }) { predictedPrice modelVersion }
}
```

**gRPC** — desde dentro del contenedor (o instalando `grpcio`/`grpcio-tools` localmente y
regenerando los stubs con el `.proto` de `grpc_service/proto/`):

```bash
docker compose exec grpc python -m app.client_example
```

**Streaming** — el consumidor ya está escuchando el topic `autos`; para generar tráfico de prueba
(incluye un cambio de distribución a mitad de camino, para ver la alerta de drift):

```bash
docker compose run --rm streaming-producer
docker compose logs -f streaming-consumer
```

Los logs muestran throughput, p95 y la media de `km_driven` por ventana; a mitad de la corrida del
productor debería aparecer `⚠ ALERTA DE DRIFT`.

## Qué NO cambia

El pipeline de entrenamiento (Airflow), el registro del modelo (MLflow) y la lógica de
preprocesamiento/scoring (`common/`, `api/app/predict.py`) son los mismos que en `MLOps1_final`.
Esta carpeta solo agrega puertas de entrada nuevas; no reentrena ni redefine el modelo.
