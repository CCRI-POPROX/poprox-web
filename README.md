# Poprox Project

## How to run the project on your local system

If you just want to run the project, you need to have conda installed.
We recommend that you create a new conda environment with the following command:

```bash
conda create -n myenv python=3.11
```

Then switch to the now created conda environment

```bash
conda activate myenv
```

To install all the required packages -

Setup database requirement:

```bash
pip install -r poprox-db/requirements-dev.txt
```

Setup serverless requirement:

```bash
pip install -r poprox-serverless/poprox_serverless/requirements.txt
```

Setup web requirement:

```bash
pip install -r poprox-web/requirements.txt
```

Also, install docker if not there yet. You can verify if you have docker setup correctly by running

```bash
sudo service docker start
sudo docker run hello-world
```

Now you are ready to run the application.

You can run it like any other Flask app
```bash
python poprox-web/app.py
# OR use
flask --app <app_name> run
```
