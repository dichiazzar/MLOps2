#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "Comenzamos a probar el stack..."
docker compose up -d --build

echo "Esperando a Airflow webserver..."
until curl -sf http://localhost:8080/health > /dev/null; do sleep 5; done

echo "Disparando training DAG..."
docker compose exec -T airflow-webserver airflow dags unpause train_xgb_pipeline
TRIGGER_JSON=$(docker compose exec -T airflow-webserver airflow dags trigger train_xgb_pipeline -o json | tail -n 1)
echo "$TRIGGER_JSON"
RUN_ID=$(docker compose exec -T airflow-webserver python3 -c "
import json, sys
print(json.loads('''$TRIGGER_JSON''')[0]['dag_run_id'])
")
echo "Se disparo run_id: ${RUN_ID:-unknown}"

echo "Esperando a instancia DAG que termine (chequeo cada 10s, hasta 5 min)..."
STATE="unknown"
for i in $(seq 1 30); do
  RUNS_JSON=$(docker compose exec -T airflow-webserver airflow dags list-runs -d train_xgb_pipeline -o json | tail -n 1)
  STATE=$(docker compose exec -T airflow-webserver python3 -c "
import json
runs = json.loads('''$RUNS_JSON''')
match = [r['state'] for r in runs if r['run_id'] == '$RUN_ID']
print(match[0] if match else 'unknown')
")
  echo "  run state: ${STATE:-unknown}"
  if [ "$STATE" = "success" ] || [ "$STATE" = "failed" ]; then
    break
  fi
  sleep 10
done

if [ "$STATE" != "success" ]; then
  echo "ERROR: DAG ${RUN_ID:-unknown} no fue exitoso (estado final: ${STATE:-unknown})"
  exit 1
fi

echo "Restarting API para levantar el modelo nuevo registrado..."
docker compose restart api
sleep 5

echo "Ejecutando /predict..."
curl -sf -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"name":"Maruti Swift Dzire VDI","year":2014,"km_driven":145500,"fuel":"Diesel","seller_type":"Individual","transmission":"Manual","owner":"First Owner","mileage":"23.4 kmpl","engine":"1248 CC","max_power":"74 bhp","torque":"190Nm@ 2000rpm","seats":5}' | tee /dev/stderr

echo
echo "Smoke test completado."
