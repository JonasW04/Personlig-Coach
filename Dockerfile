FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

# Bind all interfaces (Railway routes to $PORT) and run the scheduler in-process.
ENV HOST=0.0.0.0 \
    PORT=8000 \
    RUN_SCHEDULER=true

EXPOSE 8000
CMD ["coach-web"]
