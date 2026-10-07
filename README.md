# MLOps 2 - Trabajos Prácticos

Repositorio con los trabajos prácticos de la materia **Operaciones de Aprendizaje de Máquina II (MLOps 2)**, CEIA - FIUBA.

**Autor:** Rodolfo Di Chiazza

## Contenido

```
TPs/
├── clase1/      Mini TP 1: modelo servido con una API REST
├── clase2/      Mini TP 2: metadatos del modelo con GraphQL
├── clase3/      Mini TP 3: modelo servido con gRPC
├── clase4/      Mini TP 4: modelo aplicado sobre un flujo de datos (streaming)
├── clase5/      Mini TP 5: aprendizaje federado (FedAvg)
├── clase6/      Mini TP 6: modelo guardado y servido desde un Data Lake (MinIO)
└── TP_Final/
    ├── MLOps1_final/                         TP final de MLOps 1 (base de referencia)
    └── MLOps2_TP_Final/   TP final de MLOps 2 (en progreso)
```

## Mini TPs (clase 1 a clase 6)

Son 6 trabajos chicos, uno por clase. Todos están terminados. Cada uno es un notebook de Jupyter.

| Carpeta | Notebook | Tema |
|---|---|---|
| clase1 | `API_MLOPS2.ipynb` | Crear una API REST para servir el modelo |
| clase2 | `mini_tp2_actividad.ipynb` | Mostrar los datos del modelo con GraphQL y compararlo con REST |
| clase3 | `mini_tp3_actividad.ipynb` | Servir el modelo con gRPC |
| clase4 | `mini_tp4_actividad.ipynb` | Predecir sobre un flujo continuo de eventos |
| clase5 | `mini_tp5_federado_actividad.ipynb` | Entrenar con aprendizaje federado y comparar contra el entrenamiento normal |
| clase6 | `mini_tp6_actividad.ipynb` | Subir el modelo a un Data Lake (MinIO) y cargarlo desde ahí para predecir |

## TP Final

### MLOps1_final

Es el TP final completo de la materia anterior (MLOps 1). Se usa como **base** para el TP de esta materia.

- Modelo XGBoost que predice el precio de autos usados (dataset "Car Dekho").
- Todo corre en Docker: Airflow entrena el modelo, MLflow lo guarda, y una API REST hace las predicciones.
- Cómo levantarlo: ver [TP_Final/MLOps1_final/README.md](TP_Final/MLOps1_final/README.md).

### MLOps2_TP_Final

Es el TP integrador de **esta materia (MLOps 2)**. Usa el mismo modelo de MLOps 1, pero agrega lo visto en las clases de MLOps 2.

Ofrece **4 formas distintas de pedirle predicciones al mismo modelo**:

| Forma | Puerto | Clase donde se vio |
|---|---|---|
| REST | 8010 | Clase 1 |
| GraphQL | 8001 | Clase 2 |
| gRPC | 50051 | Clase 3 |
| Streaming (Redpanda) | - | Clase 4 |

Además incluye el **entrenamiento federado** de la clase 5: un servidor y 3 clientes en Docker, con Flower, que entrenan un modelo sin juntar los datos en un solo lugar.

- Todas usan el mismo código de predicción de MLOps 1, sin copiarlo.
- Necesita que el stack de MLOps1_final esté corriendo y con el modelo ya entrenado.
- Cómo levantarlo y probarlo: ver [TP_Final/MLOps2_TP_Final/README.md](TP_Final/MLOps2_TP_Final/README.md).
- Diseño general: ver [Diseño de arquitectura.md](TP_Final/MLOps2_TP_Final/Diseño%20de%20arquitectura.md).

> **Estado:** incluye lo visto en las clases 1 a 5. Lo de la clase 6 (Data Lake) **todavía no está agregado** al TP final.
