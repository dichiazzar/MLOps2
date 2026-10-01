FROM apache/airflow:2.9.2-python3.11
COPY airflow/requirements.txt /requirements.txt
RUN pip install --no-cache-dir -r /requirements.txt
COPY common /opt/airflow/common
ENV PYTHONPATH=/opt/airflow
