# Diseño de arquitectura — TP integrador MLOps II

## Un modelo, cuatro puertas de entrada

El pipeline de entrenamiento y el modelo registrado (`xgb_best` en MLflow) no cambian. Lo que se rediseña es la capa de acceso: cuatro formas distintas de llegar al mismo modelo, cada una practicada en un mini-TP y pensada para un tipo de cliente distinto.

## Vista general

Arriba, el núcleo que no cambia: el pipeline de datos y entrenamiento, y el modelo servido desde el registry. Abajo, los cuatro caminos nuevos hacia ese núcleo — el protocolo y el patrón de tráfico cambian; el modelo detrás es siempre el mismo.

![Diagrama de arquitectura: núcleo compartido (Airflow → MLflow Registry → Modelo cargado) con cuatro capas de acceso independientes — API REST, GraphQL, gRPC y Streaming — cada una con su patrón de tráfico y su tipo de cliente. La capa de Streaming se expande en su propio mecanismo: productor → consumidor → ventana deslizante → alerta de drift.](diagrama-arquitectura.png)

*El pipeline de Airflow entrena y registra el modelo en MLflow una sola vez; las cuatro capas de abajo son formas distintas de invocarlo. Streaming es la excepción estructural: no espera una pregunta, consume un flujo y agrega métricas por ventana hasta disparar una alerta.*

## Las cuatro capas, en detalle

Cada capa aplica lo practicado en su mini-TP correspondiente, servido sobre el mismo `xgb_best` del TP integrador.

### REST

**Petición → respuesta simple**
*unario · sincrónico*

Un cliente manda las features de un caso y espera una predicción. Es el patrón más simple y más estándar: pensado para consumidores externos o integraciones de terceros que no negocian el protocolo con vos.

`clase1/Practica/API_MLOPS2.ipynb`

### GraphQL

**Consulta a medida**
*unario · el cliente elige la forma*

El cliente pide exactamente los campos que necesita (predicción, métricas del modelo, metadata de versión) en una sola consulta. Útil para un dashboard interno que combina varias vistas del mismo modelo sin multiplicar endpoints.

`clase2/Practica/mini_tp2_actividad.ipynb`

### gRPC

**Llamada interna de alto rendimiento**
*unario + streaming · binario*

Contrato tipado (`.proto`), canal persistente, payload binario. Pensado para que otro servicio interno de la plataforma llame al modelo a alto volumen y baja latencia — no para hablarle directo desde un navegador.

`clase3/Practica/mini_tp3_actividad.ipynb`

### Streaming

**Inferencia sobre un flujo**
*continuo · sin pregunta explícita*

No hay cliente que pregunte: un consumidor puntúa cada evento a medida que llega desde un topic, y agrega throughput, p95 y un indicador de drift por ventana — disparando una alerta si la distribución de entrada se corre de lo esperado.

`clase4/Practica/mini_tp4_actividad.ipynb`
