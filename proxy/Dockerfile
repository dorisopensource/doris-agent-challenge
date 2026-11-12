FROM python:3.11-slim
WORKDIR /proxy
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY static ./static
COPY seed ./seed
EXPOSE 3000
CMD ["uvicorn", "--factory", "app.main:build", "--host", "0.0.0.0", "--port", "3000"]
