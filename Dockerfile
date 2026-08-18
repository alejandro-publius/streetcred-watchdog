# Cloud Run wants a container that starts fast and listens on $PORT.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

# Dependencies first, so a code edit does not reinstall the world.
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

# Cloud Run injects PORT. Defaulted so the image also runs locally unchanged.
ENV PORT=8080
EXPOSE 8080

# One image, two services. Cloud Run sets SERVICE=observer or SERVICE=actor, so
# the observer and the actor deploy from the same build and can never drift out
# of sync with each other's schema.
ENV SERVICE=observer
CMD exec uvicorn watchdog.server:app --host 0.0.0.0 --port ${PORT}
