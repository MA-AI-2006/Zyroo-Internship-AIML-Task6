FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV DOCFLOW_DATA_DIR=/data
VOLUME /data
EXPOSE 8501 8000
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
