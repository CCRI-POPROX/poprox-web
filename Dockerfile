FROM python:3.11-slim

WORKDIR /app

RUN apt-get update
RUN apt-get upgrade -y
RUN apt-get install -y openssh-client git

COPY requirements.txt requirements.txt
RUN pip3 install -r requirements.txt

COPY . .

EXPOSE 8080
CMD gunicorn -b 0.0.0.0:8080 app:app --reload --timeout 120
