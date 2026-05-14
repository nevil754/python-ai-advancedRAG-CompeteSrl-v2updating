# Base image
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

#copy the rest of the code
COPY . .  

#set environment variables x fastapi, con questa env ogni output di python (stdout e stderr) viene renderizzato nel log del container
ENV PYTHONUNBUFFERED=1

#expose the port
EXPOSE 8000

#start the fastapi server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]