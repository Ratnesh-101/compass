# Compass Backend — Dockerfile
# Builds from the project root context (docker-compose sets context: .)

FROM python:3.12-slim

WORKDIR /app

# Install Python dependencies
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copy backend source
COPY backend/ ./backend/

# Expose the API port
EXPOSE 8000

# Default command — overridden by docker-compose for dev (--reload)
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
