FROM python:3.11-slim

WORKDIR /app
COPY app.py .
RUN pip install flask requests PyJWT

EXPOSE ${PORT:-5000}
CMD ["python", "app.py"]
