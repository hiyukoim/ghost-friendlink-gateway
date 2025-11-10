FROM python:3.11-slim

WORKDIR /app
COPY app.py .
COPY app_ui/ app_ui/
COPY templates/ templates/
RUN mkdir -p static && cp -R templates/assets/. static/
RUN pip install flask requests PyJWT flask-limiter

EXPOSE ${PORT:-5000}
CMD ["python", "app.py"]
