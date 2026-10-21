FROM python:3.11-slim
WORKDIR /app
COPY speech_service/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY speech_service/ /app/speech_service/
EXPOSE 8001
CMD ["python", "-m", "uvicorn", "speech_service.app:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
