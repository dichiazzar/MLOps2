# Capas de acceso: REST · GraphQL · gRPC · Streaming (+ entrenamiento federado y Data Lake)

Implementación de [`Diseño de arquitectura.md`](./Diseño%20de%20arquitectura.md): cuatro formas de
acceder al mismo modelo (`xgb_best`) del TP integrador (`../MLOps1_final`), una por cada mini-TP de
la cursada. Ninguna capa reimplementa la carga ni el scoring del modelo — todas reusan
`api/app/predict.py` y `common/` de `MLOps1_final` sin copiarlos (desde la clase 6, con un
`predict.py` de MLOps2 que solo cambia de dónde se lee la metadata del modelo, ver sección 5).

Además incluye:
- el **entrenamiento federado** de la clase 5 (sección 4): no es una capa de acceso sino otra
  forma de **entrenar** un modelo, sin juntar los datos en un solo lugar;
- el **Data Lake** de la clase 6 (sección 5): datos organizados por zonas en MinIO, la memoria
  durable del streaming y MLflow como zona de modelos.

| Capa | Puerto (esta carpeta) | Origen del código | Qué demuestra |
|---|---|---|---|
| **REST** | 8010 | `rest_service/` → mismo código de `../MLOps1_final/api` (no se reimplementa), Dockerfile propio | petición → respuesta simple ([`clase1/API_MLOPS2.ipynb`](../../clase1/API_MLOPS2.ipynb)) |
| **GraphQL** | 8001 | `graphql_service/` | el cliente elige qué campos pedir ([`clase2/mini_tp2_actividad.ipynb`](../../clase2/mini_tp2_actividad.ipynb)) |
| **gRPC** | 50051 | `grpc_service/` | contrato tipado + unary + server-streaming ([`clase3/mini_tp3_actividad.ipynb`](../../clase3/mini_tp3_actividad.ipynb)) |
| **Streaming** | — (consume de Redpanda) | `streaming_service/` | scoring online + métricas por ventana + alerta de drift ([`clase4/mini_tp4_actividad.ipynb`](../../clase4/mini_tp4_actividad.ipynb)) |
| **Federado** | — (interno, se corre a mano) | `federated_service/` | entrenar sin mover los datos: FedAvg con Flower, IID / non-IID / ruido ([`clase5/mini_tp5_federado_actividad.ipynb`](../../clase5/mini_tp5_federado_actividad.ipynb)) |
| **Data Lake** | — (MinIO, bucket `datalake`) | `datalake/` | zonas raw/curated, metadata del modelo en MLflow, streaming guardado en el lake ([`clase6/mini_tp6_actividad.ipynb`](../../clase6/mini_tp6_actividad.ipynb)) |

> REST no es una capa nueva: reusa el mismo código que ya existía en `MLOps1_final/api`, solo
> expuesto acá en el puerto 8010 (no 8000) para poder levantar las 4 capas desde este único
> compose sin chocar de puerto si `MLOps1_final` también tiene su propia API arriba a la vez.
> Tiene un Dockerfile propio solo para usar el `predict.py` de la clase 6.
> Ver [`rest_service/README.md`](./rest_service/README.md).

## 1. Requisitos previos

El stack base (Postgres, MinIO, MLflow, Airflow) tiene que estar corriendo, con el modelo
`xgb_best` ya entrenado y en stage **Production** en MLflow Registry. No hace falta levantar el
servicio `api` de ese compose — esta carpeta construye su propia copia en el puerto 8010:

```bash
cd ../MLOps1_final
docker compose up -d postgres minio init-minio mlflow airflow-init airflow-webserver airflow-scheduler
# disparar el DAG de entrenamiento una vez (UI de Airflow en :8080, o `scripts/smoke_test.sh`)
```

Después, preparar el Data Lake una vez (ver sección 5). Sin este paso las capas funcionan igual,
pero calculan la metadata del modelo al arrancar, como en `MLOps1_final`:

```bash
cd ../MLOps2_TP_Final
docker compose --profile lake run --rm lake-preparar
```

## 2. Levantar las cuatro capas

```bash
cd ../MLOps2_TP_Final
docker compose up -d --build
```

Esto levanta `rest`, `graphql`, `grpc`, `redpanda` y `streaming-consumer` en la misma red Docker
que `mlflow`/`minio` (`mlops-net` de `MLOps1_final`), sin duplicar esos servicios.

> Si tu carpeta del TP integrador no se llama exactamente `MLOps1_final`, ajustá el nombre de red
> en `docker-compose.yml` (`networks.mlops-net.name`) al que muestre `docker network ls`.

## 3. Probar cada capa

**REST** \
linux — `curl -X POST http://localhost:8010/predict -H "Content-Type: application/json" -d '{
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

windows CMD (no powershell) — `curl -X POST http://localhost:8010/predict -H "Content-Type: application/json" -d "{\"name\": \"Maruti Swift Dzire VDI\", \"year\": 2014, \"km_driven\": 145500, \"fuel\": \"Diesel\", \"seller_type\": \"Individual\", \"transmission\": \"Manual\", \"owner\": \"First Owner\", \"mileage\": \"23.4 kmpl\", \"engine\": \"1248 CC\", \"max_power\": \"74 bhp\", \"torque\": \"190Nm@ 2000rpm\", \"seats\": 5}"`
(mismos endpoints y payload que `MLOps1_final/api`, ver su README).

**GraphQL** — abrir `http://localhost:8001/graphql` (GraphiQL incluido) y correr alguno de estos queries:

```graphql
query {
  modelInfo { modelName modelVersion nFeatures }
}

mutation {
  predict(car: {
    name: "Maruti Swift Dzire VDI", year: 2014, kmDriven: 145500,
    fuel: diesel, sellerType: individual, transmission: manual, owner: first,
    mileage: "23.4 kmpl", engine: "1248 CC", maxPower: "74 bhp",
    torque: "190Nm@ 2000rpm", seats: 5
  }) { predictedPrice modelVersion }
}

# clase 6: predicciones de streaming guardadas en el Data Lake (fecha por defecto: hoy, UTC)
query {
  prediccionesStreaming(limite: 5) {
    fecha archivos total
    items { name kmDriven predictedPrice modelVersion eventTime }
  }
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
productor debería aparecer `⚠ ALERTA DE DRIFT`. Además, cada 500 eventos (o tras 10 s sin eventos)
aparece `Lake: N eventos guardados en s3://datalake/raw/streaming/...` (clase 6).

El pipeline de entrenamiento (Airflow), el registro del modelo (MLflow) y la lógica de
preprocesamiento/scoring (`common/`, `api/app/predict.py`) son los mismos que en `MLOps1_final`.
Las 4 capas solo agregan puertas de entrada nuevas; no reentrenan ni redefinen el modelo.

## 4. Entrenamiento federado (clase 5)

**Idea.** Cada cliente es una **concesionaria** que tiene sus propios autos y no los comparte.
Un servidor coordina el entrenamiento con **FedAvg** usando **Flower** (`flwr`): en cada ronda
manda el modelo a los clientes, cada uno entrena con sus datos y devuelve solo los **pesos**, y
el servidor los promedia (ponderando por cantidad de autos). Los datos nunca salen del cliente.

| Contenedor | Qué hace |
|---|---|
| `fl-particionar` | Prepara la simulación (se corre una vez): reparte el dataset entre 3 clientes en MinIO (`s3://federado/`), deja un set de test para el servidor y entrena el mismo modelo de forma centralizada como línea de base |
| `fl-servidor` | Arma un esquema común (marcas principales, media y desvío) pidiendo solo conteos y sumas a los clientes, hace 20 rondas de FedAvg y registra todo en MLflow |
| `fl-cliente-0/1/2` | Cada uno lee **solo su parte** de los datos, la limpia con `common/` y entrena localmente |

- **Modelo:** la misma regresión lineal (SGD) de `mini_tp5`, que predice `log(precio)` como `xgb_best`.
- **No reemplaza a `xgb_best`:** se registra en MLflow con otro nombre, `linreg_federado`.
  El modelo en producción sigue siendo `xgb_best`.
- **Dos formas de repartir los datos:** `iid` (al azar, todos los clientes parecidos) y `no_iid`
  (por rango de precio: un cliente vende autos baratos, otro caros, etc.).
- **Privacidad diferencial simple:** con `SIGMA` mayor a 0 el servidor suma ruido a los pesos
  promediados, igual que en el punto 6 de `mini_tp5`.

**Cómo correrlo.** Estos contenedores **no** arrancan con `docker compose up -d` (están en el
profile `federado`). Con el stack de `MLOps1_final` levantado:

```bash
# 1. Repartir los datos (una sola vez)
docker compose --profile federado run --rm fl-particionar

# 2. Entrenar (por defecto: partición iid, sin ruido)
docker compose --profile federado up --build fl-servidor fl-cliente-0 fl-cliente-1 fl-cliente-2
```

Para probar otra variante, cambiar `PARTICION` y/o `SIGMA` antes del paso 2:

```bash
# Bash
PARTICION=no_iid SIGMA=0 docker compose --profile federado up fl-servidor fl-cliente-0 fl-cliente-1 fl-cliente-2
```

```powershell
# PowerShell
$env:PARTICION="no_iid"; $env:SIGMA="0"
docker compose --profile federado up fl-servidor fl-cliente-0 fl-cliente-1 fl-cliente-2
```

El comando termina solo cuando el servidor completa las 20 rondas. Los resultados quedan en la UI
de MLflow (`http://localhost:5000`), experimento `federado_concesionarias`: error por ronda,
comparación contra el centralizado y el modelo registrado.

> **Ojo:** no usar `docker compose --profile federado down`: baja **todos** los servicios de este
> compose, incluidas las 4 capas. Para borrar solo los contenedores federados ya terminados:
> `docker compose --profile federado rm -f fl-particionar fl-servidor fl-cliente-0 fl-cliente-1 fl-cliente-2`.

**Resultados** (RMSE en log-precio, menor es mejor; 3 clientes, 20 rondas de 50 épocas):

| Variante | RMSE | vs. centralizado (0.2664) |
|---|---|---|
| Federado IID | 0.2664 | igual |
| Federado non-IID | 0.2700 | +0.0036 |
| Federado IID con ruido (`SIGMA=0.05`) | 0.4653 | +0.1989 |

Con datos IID federar no cuesta error. Con non-IID el error baja más lento y termina un poco más
alto, pero la curva baja sin saltos. La privacidad diferencial sí tiene un costo alto, y es la
única variante donde el error sube y baja entre rondas.
La línea de base centralizada usa el mismo total de pasos de entrenamiento que cada cliente
(20 × 50 = 1000 épocas), para que la comparación sea justa.

**Diferencias con el mini TP 5:**
- Servidor y clientes corren en **contenedores separados** que se hablan por la red (en el mini
  TP todo corría en un mismo notebook).
- La **media, el desvío y las marcas principales** se calculan entre todos los clientes a partir
  de conteos y sumas. En el mini TP se calculaban con todos los datos juntos, algo que en un
  federado real no se puede hacer.
- El preprocesamiento se reusa de `common/` en lugar de estar copiado en el notebook.
- En cada ronda participan **los 3 clientes**. En el mini TP participaban 2 de 5 elegidos al azar,
  y por eso allá la curva non-IID saltaba según qué clientes tocaban en cada ronda.

## 5. Data Lake (clase 6)

**Idea.** Un Data Lake es un lugar central y barato donde viven los datos de toda la plataforma,
organizado por **zonas** para que no se vuelva un depósito desordenado. Acá se arma sobre el mismo
MinIO de `MLOps1_final` (compatible con S3), con dos dueños claros:

| Bucket | Qué guarda | Quién lo administra |
|---|---|---|
| `datalake` | **Datos**: zona `raw` (dataset crudo y eventos de streaming) y zona `curated` (features listas para entrenar, en Parquet) | este proyecto |
| `mlflow-artifacts` | **Modelos**: cada versión de `xgb_best` con sus métricas y su metadata. Funciona como la zona de modelos del lake | MLflow |

```
datalake/
├── raw/car_dekho/car_details_v3.csv              dataset crudo, tal cual
├── raw/streaming/fecha=AAAA-MM-DD/lote-*.parquet  eventos + predicción + versión del modelo
└── curated/car_dekho/car_features.parquet         features + target, con columna split train/test
```

**Por qué MLflow sigue siendo la fuente del modelo.** El Mini TP 6 guarda el modelo en el lake
con un archivo `PRODUCTION` que dice qué versión usar. Este TP ya tiene MLflow, que hace eso mismo
con más garantías (cuándo cambió de estado cada versión, vínculo con su entrenamiento y métricas), y
que **ya guarda los modelos en MinIO**. Tener un segundo registro solo agregaría el riesgo de que
los dos digan cosas distintas. Las capas siguen sin llevar el modelo dentro de la imagen: lo bajan
del lake (vía MLflow) al arrancar, que es la idea central de la clase 6.

**Qué cambia en las capas.** Antes, cada capa al arrancar bajaba el dataset crudo y rehacía parte
del preprocesamiento para saber las marcas principales y el orden de las columnas. Ahora esa
**metadata** (`lake_metadata.json`) se guarda una vez en el mismo run de MLflow que el modelo, y las
capas solo la leen. Se hace con una versión de MLOps2 de `predict.py`
([`datalake/compartido/predict.py`](./datalake/compartido/predict.py)), con las mismas funciones,
que reemplaza a la original al construir cada imagen: el código de las capas no cambia.

| Contenedor / capa | Qué hace con el lake |
|---|---|
| `lake-preparar` | Crea el bucket y las zonas, copia el dataset crudo a `raw`, guarda las features en `curated` y agrega la metadata al run del modelo en Production. Se puede correr varias veces |
| las 4 capas | Bajan el modelo de MLflow y leen su metadata del mismo run |
| `streaming-consumer` | Guarda cada evento con su predicción en `raw/streaming/`, separado por fecha, por lotes de 500 (o tras 10 s sin eventos). Usa un grupo de consumidores y confirma a Redpanda hasta dónde leyó recién después de guardar cada lote: si se reinicia, sigue desde ahí sin perder los eventos que tenía juntados |
| `graphql` | La query `prediccionesStreaming` lee esos archivos del lake |

**Cómo correrlo.** Con todo levantado (secciones 1 y 2):

```bash
docker compose --profile lake run --rm lake-preparar   # una vez, y después de cada entrenamiento nuevo
docker compose restart                                 # para que las capas lean la metadata
docker compose run --rm streaming-producer             # genera eventos que se guardan en el lake
```

En los logs de cada capa aparece `metadata leída de MLflow (lake_metadata.json)`. El contenido del
lake se ve en la consola de MinIO (`http://localhost:9001`, bucket `datalake`).

> **Si Airflow entrena una versión nueva**, su run todavía no tiene la metadata. Las capas funcionan
> igual (la calculan como antes y lo avisan en el log) hasta que se vuelva a correr `lake-preparar`.

**Diferencias con el mini TP 6:**
- El modelo no se copia a una carpeta `models/` del lake: MLflow ya lo guarda en MinIO y sigue
  siendo el registro de qué versión está en producción.
- El lake también guarda los eventos de streaming con su predicción, que antes se perdían al
  vencer la retención de Redpanda.
- El TP usa su propio bucket (`datalake`), separado del bucket `datalake-tp6` que usó el mini TP
  en el mismo MinIO.
