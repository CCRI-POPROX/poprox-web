# Poprox Project

## How to run the project on your local system

#### Python Dependencies

If you want to run the project, you'll need python installed on your computer. We recommend setting up a virtual environment. The easiest way to do this is with conda:

```bash
conda create -n poprox-web python=3.11
```

Then switch to the now created conda environment

```bash
conda activate poprox-web
```

To install all the required packages -

```bash
pip install -r requirements.txt
```

#### Other dependencies

You will also need the poprox-storage project for a development database. See instructions there on setup and execution.

Additionally you will need an `.env` file. A template of this is available, but some settings must be gotten from other developers.

#### Running
You can run it like any other Flask app
```bash
python poprox-web/app.py
# OR use
flask --app <app_name> run
```
