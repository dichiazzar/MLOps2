# Capas de acceso: REST · GraphQL · gRPC · Streaming (+ entrenamiento federado, Data Lake y seguridad)

Implementación de [`Diseño de arquitectura.md`](./Diseño%20de%20arquitectura.md): cuatro formas de
acceder al mismo modelo (`xgb_best`) del TP integrador (`../MLOps1_final`), una por cada mini-TP de
la cursada. Ninguna capa reimplementa la carga ni el scoring del modelo — todas reusan
`api/app/predict.py` y `common/` de `MLOps1_final` sin copiarlos (desde la clase 6, con un
`predict.py` de MLOps2 que lee la metadata del modelo de MLflow, ver sección 5, y desde la clase 7
verifica el hash del modelo antes de cargarlo, ver sección 6).

Además incluye:
- el **entrenamiento federado** de la clase 5 (sección 4): no es una capa de acceso sino otra
  forma de **entrenar** un modelo, sin juntar los datos en un solo lugar;
- el **Data Lake** de la clase 6 (sección 5): datos organizados por zonas en MinIO, la memoria
  durable del streaming y MLflow como zona de modelos;
- la **seguridad** de la clase 7 (sección 6): token con rol en todas las capas, validación,
  límites, TLS en gRPC, firma de los eventos de streaming, un usuario de MinIO por servicio,
  integridad del modelo y auditoría.

**Presentación del TP:** [Google Slides](https://docs.google.com/presentation/d/1fZpvGuIXBnAO-tiywhd0E4AE7SJbv0w5XVqIrQOPSNQ/edit) · en PowerPoint: [presentacion/TP Final MLOps II.pptx](./presentacion/TP%20Final%20MLOps%20II.pptx).

| Capa | Puerto (esta carpeta) | Origen del código | Qué demuestra |
|---|---|---|---|
| **REST** | 8010 | `rest_service/` → mismo código de `../MLOps1_final/api` (no se reimplementa), Dockerfile propio | petición → respuesta simple ([`clase1/API_MLOPS2.ipynb`](../../clase1/API_MLOPS2.ipynb)) |
| **GraphQL** | 8001 | `graphql_service/` | el cliente elige qué campos pedir ([`clase2/mini_tp2_actividad.ipynb`](../../clase2/mini_tp2_actividad.ipynb)) |
| **gRPC** | 50051 | `grpc_service/` | contrato tipado + unary + server-streaming ([`clase3/mini_tp3_actividad.ipynb`](../../clase3/mini_tp3_actividad.ipynb)) |
| **Streaming** | — (consume de Redpanda) | `streaming_service/` | scoring online + métricas por ventana + alerta de drift ([`clase4/mini_tp4_actividad.ipynb`](../../clase4/mini_tp4_actividad.ipynb)) |
| **Federado** | — (interno, se corre a mano) | `federated_service/` | entrenar sin mover los datos: FedAvg con Flower, IID / non-IID / ruido ([`clase5/mini_tp5_federado_actividad.ipynb`](../../clase5/mini_tp5_federado_actividad.ipynb)) |
| **Data Lake** | — (MinIO, bucket `datalake`) | `datalake/` | zonas raw/curated, metadata del modelo en MLflow, streaming guardado en el lake ([`clase6/mini_tp6_actividad.ipynb`](../../clase6/mini_tp6_actividad.ipynb)) |
| **Seguridad** | — (transversal a todas las capas) | `seguridad/` | JWT con roles, validación, límites, TLS, firma HMAC, acceso mínimo, integridad del modelo y auditoría, siguiendo SAIF ([`clase7/`](../../clase7/)) |

> REST no es una capa nueva: reusa el mismo código que ya existía en `MLOps1_final/api`, solo
> expuesto acá en el puerto 8010 (no 8000) para poder levantar las 4 capas desde este único
> compose sin chocar de puerto si `MLOps1_final` también tiene su propia API arriba a la vez.
> Tiene un Dockerfile propio para usar el `predict.py` de MLOps2 y, desde la clase 7, para servir la
> API envuelta por la capa de seguridad (sin modificar su código).
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

Después, en esta carpeta, preparar los secretos y la seguridad (una vez, ver sección 6):

```bash
cd ../MLOps2_TP_Final
cp .env.example .env        # y cambiar los valores (el comando para generar secretos está en el archivo)
docker compose --profile seguridad run --rm --build seguridad-certs   # certificado TLS de gRPC
docker compose --profile seguridad run --rm seguridad-minio           # usuarios de MinIO y bucket datalake
```

Y preparar el Data Lake (ver sección 5). Además de la metadata del modelo, registra su **hash** y
los rangos de entrada que usan las capas para validar los autos:

```bash
docker compose --profile lake run --rm --build lake-preparar
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

Desde la clase 7 **todas las capas piden un token** con un rol (ver sección 6). Primero emitir uno
(dura 60 minutos; los roles con permisos son `analista` y `admin`):

```bash
# Git Bash / Linux
TOKEN=$(docker compose --profile manual run --rm emitir-token jaime analista | tail -1)
```

```powershell
# PowerShell
$TOKEN = docker compose --profile manual run --rm emitir-token jaime analista | Select-Object -Last 1
```

En Windows CMD, correr `docker compose --profile manual run --rm emitir-token jaime analista`,
copiar el token que imprime y hacer `set TOKEN=<el token>`.

Para probar los permisos, emitir también uno de `admin` (por ejemplo `emitir-token ana admin`).

**REST** \
Git Bash / Linux — `curl -X POST http://localhost:8010/predict -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{
  "name": "Maruti Swift Dzire VDI",
  "year": 2014,
  "km_driven": 145500,
  "fuel": "Diesel",
  "seller_type": "Individual",
  "transmission": "Manual",
  "owner": "First Owner",
  "mileage": "23.4 kmpl",
  "engine": "1248 CC",
  "max_power": "74 bhp",
  "torque": "190Nm@ 2000rpm",
  "seats": 5
}'`

windows CMD (no powershell) — `curl -X POST http://localhost:8010/predict -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"name\": \"Maruti Swift Dzire VDI\", \"year\": 2014, \"km_driven\": 145500, \"fuel\": \"Diesel\", \"seller_type\": \"Individual\", \"transmission\": \"Manual\", \"owner\": \"First Owner\", \"mileage\": \"23.4 kmpl\", \"engine\": \"1248 CC\", \"max_power\": \"74 bhp\", \"torque\": \"190Nm@ 2000rpm\", \"seats\": 5}"`

PowerShell:

```powershell
$auto = @{ name = "Maruti Swift Dzire VDI"; year = 2014; km_driven = 145500; fuel = "Diesel"
           seller_type = "Individual"; transmission = "Manual"; owner = "First Owner"
           mileage = "23.4 kmpl"; engine = "1248 CC"; max_power = "74 bhp"
           torque = "190Nm@ 2000rpm"; seats = 5 } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8010/predict `
  -Headers @{ Authorization = "Bearer $TOKEN" } -ContentType "application/json" -Body $auto
```

Son los mismos endpoints y el mismo payload que `MLOps1_final/api` (ver su README). Sin token
responde `401`; con un año 3000 o un motor ilegible, `422`. `GET /health` y `/docs` son públicos.

**GraphQL** — `POST http://localhost:8001/graphql` con el header `Authorization: Bearer <token>`
(con curl, o con un cliente como Postman, Insomnia o Altair). GraphiQL está apagado: sin
introspección no sirve (ver sección 6).

Git Bash / Linux — `curl -s http://localhost:8001/graphql -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"query": "{ modelInfo { modelName modelVersion nFeatures } }"}'`

windows CMD (no powershell) — `curl -s http://localhost:8001/graphql -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"query\": \"{ modelInfo { modelName modelVersion nFeatures } }\"}"`

PowerShell:

```powershell
$q = @{ query = "{ modelInfo { modelName modelVersion nFeatures } }" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8001/graphql `
  -Headers @{ Authorization = "Bearer $TOKEN" } -ContentType "application/json" -Body $q | ConvertTo-Json -Depth 5
```

Otras consultas para mandar en el campo `query`:

```graphql
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

# clase 7: registro de auditoría de una capa (solo con un token de rol admin)
query {
  auditoria(capa: "rest", limite: 10) {
    total
    items { ts usuario rol accion resultado detalle }
  }
}
```

**gRPC** — solo acepta conexiones con **TLS**. El cliente de ejemplo verifica el servidor con la
CA de prueba y manda el token:

```bash
docker compose exec -e TOKEN="$TOKEN" grpc python -m app.client_example     # Git Bash / Linux
docker compose exec -e TOKEN=%TOKEN% grpc python -m app.client_example       # Windows CMD
docker compose exec -e TOKEN=$TOKEN grpc python -m app.client_example        # PowerShell
```

**Streaming** — el consumidor ya está escuchando el topic `autos`. El productor de prueba firma cada
evento con la clave de su concesionaria (incluye un cambio de distribución a mitad de camino, para
ver la alerta de drift):

```bash
docker compose run --rm streaming-producer
docker compose logs -f streaming-consumer
```

Los logs muestran throughput, p95, la media de `km_driven` por ventana y cuántos eventos fueron a
cuarentena (`dlq=N`); a mitad de la corrida del productor debería aparecer `⚠ ALERTA DE DRIFT`.
Además, cada 500 eventos (o tras 10 s sin eventos) aparece
`Lake: N eventos guardados en s3://datalake/raw/streaming/...` (clase 6).

Para ver la defensa contra eventos falsos (clase 7): `docker compose run --rm streaming-producer
python -m app.producer --modo ataque` manda eventos sin firma, alterados, repetidos, viejos y con
datos absurdos. Van a `raw/dlq/` y al topic `autos-dlq`, y aparece `⚠ ALERTA DLQ` en los logs.

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
├── raw/dlq/fecha=AAAA-MM-DD/lote-*.jsonl          eventos en cuarentena, con el motivo (clase 7)
├── raw/auditoria/capa=<capa>/fecha=.../*.jsonl    registro de auditoría de cada capa (clase 7)
└── curated/car_dekho/car_features.parquet         features + target, con columna split train/test
```

Desde la clase 7 el bucket `datalake` tiene **versionado**: si alguien sobrescribe un objeto, la
versión anterior queda. Cada servicio usa su propio usuario de MinIO, con permiso solo para lo que
necesita (ver sección 6).

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
| `lake-preparar` | Copia el dataset crudo a `raw`, guarda las features en `curated` y agrega al run del modelo en Production la metadata y (clase 7) el hash del modelo con los rangos de entrada. El bucket lo crea `seguridad-minio`. Se puede correr varias veces |
| las 4 capas | Bajan el modelo de MLflow, verifican su hash (clase 7) y leen su metadata del mismo run |
| `streaming-consumer` | Guarda cada evento con su predicción en `raw/streaming/`, separado por fecha, por lotes de 500 (o tras 10 s sin eventos). Usa un grupo de consumidores y confirma a Redpanda hasta dónde leyó recién después de guardar cada lote: si se reinicia, sigue desde ahí sin perder los eventos que tenía juntados |
| `graphql` | La query `prediccionesStreaming` lee esos archivos del lake |

**Cómo correrlo.** Con todo levantado (secciones 1 y 2):

```bash
docker compose --profile lake run --rm lake-preparar   # una vez, y después de cada entrenamiento nuevo
docker compose restart                                 # para que las capas lean la metadata
docker compose run --rm streaming-producer             # genera eventos que se guardan en el lake
```

En los logs de cada capa aparecen `integridad verificada (seguridad_modelo.json)` y
`metadata leída de MLflow (lake_metadata.json)`. El contenido del lake se ve en la consola de MinIO
(`http://localhost:9001`, bucket `datalake`).

> **Si Airflow entrena una versión nueva**, su run todavía no tiene la metadata ni el hash. Hasta que
> se vuelva a correr `lake-preparar`, las capas calculan la metadata como antes, y el modelo se carga
> sin verificar (con un warning) solo si `EXIGIR_INTEGRIDAD=false`. Con `true` no se carga (sección 6).

**Diferencias con el mini TP 6:**
- El modelo no se copia a una carpeta `models/` del lake: MLflow ya lo guarda en MinIO y sigue
  siendo el registro de qué versión está en producción.
- El lake también guarda los eventos de streaming con su predicción, que antes se perdían al
  vencer la retención de Redpanda.
- El TP usa su propio bucket (`datalake`), separado del bucket `datalake-tp6` que usó el mini TP
  en el mismo MinIO.

## 6. Seguridad (clase 7)

**Idea.** Las 4 capas exponen el mismo modelo, así que tienen que tener **los mismos controles**:
si una queda abierta, el atacante entra por esa. Todo el código común está en un solo archivo,
[`seguridad/compartido/seguridad.py`](./seguridad/compartido/seguridad.py), que se copia en cada
imagen (igual que `predict.py`). Cada capa lo aplica con el mecanismo de su protocolo. Es lo
practicado en los seis notebooks del Mini-TP 7 ([`clase7/`](../../clase7/)), siguiendo el marco
**SAIF** (ver [`Diseño de arquitectura.md`](./Diseño%20de%20arquitectura.md)).

**Preparación** (una vez, con el stack de `MLOps1_final` levantado; ver sección 1):

| Paso | Qué hace |
|---|---|
| `cp .env.example .env` | Secretos y ajustes del TP: `JWT_SECRET`, cuánto dura un token (`JWT_MINUTOS`, 60), pedidos por minuto en REST (`LIMITE_POR_MINUTO`, 60), claves de las concesionarias (`HMAC_CLAVES`), usuarios de MinIO y `EXIGIR_INTEGRIDAD`. El `.env` no se sube al repo, y cada contenedor recibe solo las variables que usa |
| `seguridad-certs` | Crea una CA de prueba y el certificado TLS del servidor gRPC en el volumen `certs` |
| `seguridad-minio` | Crea un usuario de MinIO por servicio con su política, el bucket `datalake` y su versionado |

**Roles** (una sola tabla para todas las capas):

| Acción | `analista` | `admin` |
|---|---|---|
| Predecir (REST `/predict`, GraphQL `predict`, gRPC) | sí | sí |
| Ver el modelo (`/model/info`, `modelInfo`) | sí | sí |
| Ver predicciones de streaming (`prediccionesStreaming`) | sí | sí |
| Ver predicciones de otros usuarios (`/predictions/recent`) | no | sí |
| Ver la auditoría (`auditoria`) | no | sí |

Cualquier otro rol (por ejemplo `invitado`) no puede hacer nada.

**Qué controla cada capa:**

| Capa | Control | Si falla |
|---|---|---|
| REST | token y rol (middleware alrededor de la API de MLOps1, sin modificarla) | `401` / `403` |
| REST | body de 16 KB como máximo · auto válido y dentro de los rangos de train · 60 pedidos por minuto por usuario | `413` / `422` / `429` |
| GraphQL | token y permiso **por campo** | error `no autorizado` solo en ese campo |
| GraphQL | consultas de más de 10.000 caracteres o más de 30 fragmentos | `400` antes de analizarla (evita la "bomba de fragmentos") |
| GraphQL | introspección apagada · profundidad máxima 5 · costo máximo 200 (`predict` cuesta 10, las listas se multiplican por `limite`) | la consulta se rechaza antes de ejecutarse |
| gRPC | solo TLS · token y rol (interceptor) | `UNAVAILABLE` / `UNAUTHENTICATED` / `PERMISSION_DENIED` |
| gRPC | mensajes de 1 MB y lotes de 100 autos como máximo · auto válido | `RESOURCE_EXHAUSTED` / `INVALID_ARGUMENT` |
| Streaming | mensaje que no es JSON · firma HMAC con la clave de la concesionaria · anti-replay (`_id` repetido o `_ts` fuera de la ventana) · auto válido | el evento no se puntúa: va a `autos-dlq` y a `raw/dlq/` (`dlq_firma`, `dlq_replay`, `dlq_esquema`) |
| Streaming | si más del 20 % de los últimos 50 eventos va a cuarentena | `⚠ ALERTA DLQ` en el log (posible ataque) |
| Lake | un usuario de MinIO por servicio, sin permiso de borrado, bucket versionado | `AccessDenied` |

**Integridad del modelo.** `lake-preparar` guarda en el run de MLflow del modelo el SHA-256 de sus
archivos (`seguridad_modelo.json`). Al arrancar, cada capa baja el modelo, calcula su hash y lo
compara **antes** de cargarlo: si alguien lo cambió, no se carga. En ese caso REST responde
`503` (y su `/health` muestra `model_loaded: false`), GraphQL devuelve un error, y gRPC y el
consumidor de streaming no arrancan (se reinician hasta que se corrija). Funciona porque las capas solo pueden **leer**
el bucket de modelos, y cada contenedor recibe solo sus propios secretos (no el `.env` entero): un
servicio comprometido no puede cambiar ni el modelo ni su hash. Ojo: la API de MLflow no tiene
autenticación dentro de la red Docker, así que quien llegue a esa red podría cambiar qué versión
está en Production (queda fuera de alcance, ver abajo).

| `EXIGIR_INTEGRIDAD` | Si el run no tiene `seguridad_modelo.json` | Uso |
|---|---|---|
| `false` (el `.env.example`) | se carga igual, con un warning en el log | desarrollo |
| `true` (si la variable no está) | **no** se carga | producción |

En los dos casos, si el hash existe y no coincide, el modelo no se carga.

**Auditoría.** Cada capa guarda en el lake (`raw/auditoria/capa=<capa>/fecha=.../`) quién hizo
qué y con qué resultado: fecha y hora, usuario, rol, acción, código de respuesta, hash de la entrada
y versión del modelo. Los datos del auto **no** se guardan: solo su hash (el detalle de un
rechazo puede nombrar el campo que falló, por ejemplo `year`). Se consulta con la query `auditoria`
de GraphQL (solo `admin`) o en la consola de MinIO.

**Cómo verificarlo:**

```bash
# tests unitarios (sin servicios; usa el dataset de MLOps1_final)
docker compose --profile manual run --rm --build seguridad-tests

# demo de ataques contra las capas levantadas (la versión del Mini-TP 7 sobre el sistema real)
docker compose --profile manual run --rm demo-ataques --integridad
```

El demo prueba cada capa con tokens vencidos, roles sin permiso, datos absurdos, consultas
costosas, mensajes gigantes, canales sin TLS, eventos falsos y accesos al lake fuera de la política.
Imprime una línea por prueba y termina con `TODO OK`, o con la lista de lo que falló y código de
salida 1. La prueba de integridad altera una **copia local** del modelo: nunca toca el modelo en
Production.

**Fuera de alcance** (pendiente para una próxima iteración):
- El **federado** sigue con FedAvg y `minioadmin`: le faltan la agregación robusta (mediana,
  *clipping*) del Mini-TP 7 y un usuario de MinIO propio.
- **Airflow y MLflow** (de `MLOps1_final`) siguen usando `minioadmin`, y la API de MLflow no tiene
  autenticación.
- gRPC usa TLS pero no **mTLS**: el cliente se identifica con el token, no con un certificado.
- El límite de pedidos por usuario existe solo en **REST**, y es **por contenedor** (en memoria).
  GraphQL y gRPC se protegen por costo y por tamaño, pero no cuentan pedidos por usuario. Con
  varias réplicas, el límite habría que llevarlo a Redis o a un API gateway.
- Si falla la verificación del modelo, gRPC y el consumidor de streaming se reinician en bucle en
  vez de quedar levantados respondiendo "no disponible", como hace REST.
- Los secretos están en un `.env`. En producción irían a un gestor de secretos (Vault, AWS
  Secrets Manager) y los certificados los emitiría una CA interna.
