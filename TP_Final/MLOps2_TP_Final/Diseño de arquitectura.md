# Diseño de arquitectura — TP integrador MLOps II

## Un modelo, cuatro puertas de entrada

El pipeline de entrenamiento y el modelo registrado (`xgb_best` en MLflow) no cambian. Lo que se rediseña es la capa de acceso: cuatro formas distintas de llegar al mismo modelo, cada una practicada en un mini-TP y pensada para un tipo de cliente distinto.

## Vista general

Arriba, el núcleo que no cambia: el pipeline de datos y entrenamiento, y el modelo servido desde el registry. Abajo, los cuatro caminos nuevos hacia ese núcleo — el protocolo y el patrón de tráfico cambian; el modelo detrás es siempre el mismo.

![Diagrama de arquitectura: núcleo compartido (Airflow → MLflow Registry → Modelo cargado) con cuatro capas de acceso independientes — API REST, GraphQL, gRPC y Streaming — cada una con su patrón de tráfico y su tipo de cliente. La capa de Streaming se expande en su propio mecanismo: productor → consumidor → ventana deslizante → alerta de drift. Abajo, el entrenamiento federado: un servidor Flower que coordina rondas de FedAvg con tres concesionarias y registra el modelo aparte en MLflow. Al final, el Data Lake en MinIO: el bucket datalake con las zonas raw y curated, y mlflow-artifacts como zona de modelos. Entre el núcleo y las capas, una franja de seguridad (clase 7) que atraviesa las cuatro: JWT con roles, validación, límites, auditoría y hash del modelo; gRPC solo con TLS y streaming con firma HMAC y cuarentena (DLQ).](diagrama-arquitectura.png)

*El pipeline de Airflow entrena y registra el modelo en MLflow una sola vez; las cuatro capas de abajo son formas distintas de invocarlo. Streaming es la excepción estructural: no espera una pregunta, consume un flujo y agrega métricas por ventana hasta disparar una alerta. Los bloques de abajo no son capas de acceso: el entrenamiento federado (clase 5) y el Data Lake donde quedan guardados los datos (clase 6).*

## Las cuatro capas, en detalle

Cada capa aplica lo practicado en su mini-TP correspondiente, servido sobre el mismo `xgb_best` del TP integrador.

### REST

**Petición → respuesta simple**
*unario · sincrónico*

Un cliente manda las features de un caso y espera una predicción. Es el patrón más simple y más estándar: pensado para consumidores externos o integraciones de terceros que no negocian el protocolo con vos.

[`clase1/API_MLOPS2.ipynb`](../../clase1/API_MLOPS2.ipynb)

### GraphQL

**Consulta a medida**
*unario · el cliente elige la forma*

El cliente pide exactamente los campos que necesita (predicción, métricas del modelo, metadata de versión) en una sola consulta. Útil para un dashboard interno que combina varias vistas del mismo modelo sin multiplicar endpoints.

[`clase2/mini_tp2_actividad.ipynb`](../../clase2/mini_tp2_actividad.ipynb)

### gRPC

**Llamada interna de alto rendimiento**
*unario + streaming · binario*

Contrato tipado (`.proto`), canal persistente, payload binario. Pensado para que otro servicio interno de la plataforma llame al modelo a alto volumen y baja latencia — no para hablarle directo desde un navegador.

[`clase3/mini_tp3_actividad.ipynb`](../../clase3/mini_tp3_actividad.ipynb)

### Streaming

**Inferencia sobre un flujo**
*continuo · sin pregunta explícita*

No hay cliente que pregunte: un consumidor puntúa cada evento a medida que llega desde un topic, y agrega throughput, p95 y un indicador de drift por ventana — disparando una alerta si la distribución de entrada se corre de lo esperado.

[`clase4/mini_tp4_actividad.ipynb`](../../clase4/mini_tp4_actividad.ipynb)

## Entrenamiento federado (clase 5)

**Otra forma de entrenar, no otra puerta de entrada**
*por rondas · los datos no se mueven*

Las cuatro capas de arriba cambian cómo se **pide** una predicción. El federado cambia cómo se
**entrena** el modelo: pensado para el caso en que cada concesionaria tiene sus propios datos de
ventas y no quiere (o no puede) compartirlos con las demás.

- Un **servidor** Flower coordina rondas de **FedAvg**; tres **clientes** (concesionarias), cada
  uno en su propio contenedor, entrenan con sus datos y devuelven solo los pesos del modelo.
- Antes de entrenar, el servidor arma un esquema común (marcas principales, media y desvío)
  pidiendo a los clientes solo **conteos y sumas**, nunca filas.
- Cada ronda se mide el error con un set de test del servidor y se registra en **MLflow**, junto
  con la comparación contra el mismo modelo entrenado de forma centralizada.
- El modelo resultante se registra como `linreg_federado`, **separado** de `xgb_best`: es un
  experimento de entrenamiento, no reemplaza al modelo que sirven las cuatro capas.

[`clase5/mini_tp5_federado_actividad.ipynb`](../../clase5/mini_tp5_federado_actividad.ipynb)

## Data Lake (clase 6)

**El piso común de la plataforma**
*datos en reposo · zonas · un dueño por bucket*

Las capas de arriba mueven datos (pedidos, eventos, pesos). El Data Lake es donde esos datos
**quedan guardados**, organizados por zonas para no convertirse en un depósito desordenado. Se arma
sobre el mismo MinIO del TP integrador:

- **Bucket `datalake` (datos):** zona `raw` con el dataset crudo y los eventos de streaming, y zona
  `curated` con las features listas para entrenar, en Parquet.
- **Bucket `mlflow-artifacts` (modelos):** MLflow ya guardaba ahí cada versión de `xgb_best`.
  Funciona como la zona de modelos del lake, y MLflow sigue siendo el registro de qué versión está
  en producción. No se crea un segundo registro, para que no puedan contradecirse.
- **Metadata del modelo:** las marcas principales y el orden de las columnas se guardan una vez en
  el mismo run de MLflow que el modelo. Las capas la leen al arrancar en vez de recalcularla.
- **Streaming con memoria:** el consumidor guarda cada evento con su predicción en `raw`, separado
  por fecha. Redpanda borra los eventos al vencer la retención; el lake los conserva.
- **GraphQL sobre el lake:** la query `prediccionesStreaming` lee esos archivos, usando el lake como
  origen de verdad.

[`clase6/mini_tp6_actividad.ipynb`](../../clase6/mini_tp6_actividad.ipynb)

## Seguridad (clase 7)

**Los mismos controles en las cuatro puertas y en el lake**
*transversal · defensa en profundidad · SAIF*

Cada clase sumó una forma nueva de llegar al modelo o a los datos, y con ella una superficie de
ataque. La clase 7 las asegura a todas con el marco **SAIF** (Secure AI Framework). La idea central
es la **coherencia de controles**: las cuatro capas sirven el mismo modelo, así que si una queda
más débil que las otras, el atacante entra por esa.

- Un único módulo, `seguridad/compartido/seguridad.py`, se copia en cada imagen (como
  `predict.py`): mismos tokens, mismos roles, misma validación y mismo formato de auditoría.
- Cada capa lo aplica con el mecanismo de su protocolo: un middleware alrededor de la API REST de
  MLOps1 (sin modificarla), permisos por campo y extensiones en GraphQL, un interceptor en gRPC y
  la validación de cada evento en el consumidor de streaming.
- El lake deja de usar la credencial de administrador: cada servicio tiene su usuario de MinIO,
  con permiso solo para lo que necesita. Esto, junto con el hash del modelo, protege la cadena de
  suministro del modelo.

| Control | Amenaza | Elemento de SAIF |
|---|---|---|
| JWT con rol en REST, GraphQL y gRPC (misma tabla de permisos) | acceso no autorizado | Bases sólidas |
| Validación estricta con rangos de train | inyección, entradas fuera de dominio | Bases sólidas |
| Límite por usuario (REST), costo y profundidad (GraphQL), tamaño y lote (gRPC) | abuso, DoS, extracción del modelo | Automatizar defensas |
| Introspección apagada | reconocimiento de la API | Bases sólidas |
| TLS en gRPC | *man-in-the-middle*, robo del token | Bases sólidas |
| Firma HMAC por productor, anti-replay, DLQ y alerta | envenenamiento, productores no autorizados | Automatizar defensas + Detectar y actuar |
| Un usuario de MinIO por servicio, sin borrado, lake versionado | acceso excesivo, servicio comprometido | Bases sólidas + Coherencia de controles |
| Hash del modelo verificado antes de cargarlo | manipulación del artefacto | Bases sólidas (cadena de suministro) |
| Auditoría de las 4 capas en el lake + query `auditoria` | uso indebido sin rastro | Detectar y actuar + gobernanza |

**Fuera de alcance** (pendiente): agregación robusta y usuario propio para el federado; Airflow y
MLflow con `minioadmin`; mTLS en gRPC; límite de pedidos distribuido; gestión de secretos con un
*secret manager*.

[`clase7/`](../../clase7/) (seis notebooks del Mini-TP 7, uno por capa)

## Diagrama

El diagrama se edita en [`diagrama-arquitectura.svg`](./diagrama-arquitectura.svg) (texto, con
comentarios de cómo sumar una clase nueva) y se exporta a PNG con Edge, desde esta carpeta:

```powershell
& "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --headless --disable-gpu --hide-scrollbars --window-size=1150,1667 --screenshot="$pwd\diagrama-arquitectura.png" "$pwd\diagrama-arquitectura.svg"
```

Si se agranda el diagrama, cambiar `--window-size` por el nuevo ancho y alto del SVG.
