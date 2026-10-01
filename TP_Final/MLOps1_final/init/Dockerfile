FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY upload_dataset_to_minio.py .
CMD ["python", "upload_dataset_to_minio.py"]
