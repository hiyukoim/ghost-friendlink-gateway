FROM python:3.11-slim

WORKDIR /app
COPY app.py .
COPY ghost_gateway/ ghost_gateway/
COPY app_ui/ app_ui/
COPY templates/ templates/
# Version is baked in via ghost_gateway/VERSION; no script execution needed here.
RUN mkdir -p static && cp -R templates/assets/. static/
RUN pip install flask requests PyJWT flask-limiter

EXPOSE ${PORT:-5000}
CMD ["python", "app.py"]
