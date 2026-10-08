FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY node_temperature/ node_temperature/
COPY config.default.ini .

ENTRYPOINT ["python", "-m", "node_temperature.main"]
CMD ["--config", "/app/config.ini"]
