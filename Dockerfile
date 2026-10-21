FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY driver_temperature/ driver_temperature/
# Beside the module, where device_info.py looks first (a checkout run uses the repo-root file).
COPY manifest.json driver_temperature/manifest.json
COPY config.default.ini .

# The release workflow passes the git release tag. Unset (a local build) reports "dev".
ARG DEVICE_VERSION
ENV DEVICE_VERSION=${DEVICE_VERSION}

ENTRYPOINT ["python", "-m", "driver_temperature.main"]
CMD ["--config", "/app/config.ini"]
