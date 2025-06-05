FROM python:3.11-slim

WORKDIR /app

RUN apt-get update
RUN apt-get upgrade -y
RUN apt-get install -y git

COPY requirements.txt requirements.txt
RUN pip3 install -r requirements.txt

COPY . .

EXPOSE 80
CMD gunicorn -b 0.0.0.0:80 app:app --reload
