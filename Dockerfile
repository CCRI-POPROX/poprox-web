FROM python:3.11-slim

WORKDIR /app

RUN apt-get update
RUN apt-get upgrade -y
RUN apt-get install -y openssh-client git

# download public key for github.com
RUN mkdir -p -m 0600 ~/.ssh && ssh-keyscan github.com >> ~/.ssh/known_hosts

COPY requirements.txt requirements.txt
RUN --mount=type=ssh pip3 install -r requirements.txt

COPY . .

EXPOSE 8080
CMD gunicorn -b 0.0.0.0:8080 app:app --reload
