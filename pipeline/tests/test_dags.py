import sys
sys.path.insert(0, "pipeline")
import os
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://riffle:riffle@localhost/riffle")
os.environ.setdefault("MLFLOW_TRACKING_URI", "http://localhost:5000")
import pytest
from airflow.models import DagBag

@pytest.fixture(scope="module")
def dagbag():
    return DagBag(dag_folder="pipeline/dags", include_examples=False)

def test_gauge_ingest_dag_loads(dagbag):
    dag = dagbag.get_dag("gauge_ingest")
    assert dag is not None
    assert dagbag.import_errors == {}

def test_weather_ingest_dag_loads(dagbag):
    dag = dagbag.get_dag("weather_ingest")
    assert dag is not None

def test_condition_score_dag_loads(dagbag):
    dag = dagbag.get_dag("condition_score")
    assert dag is not None

def test_train_dag_loads(dagbag):
    dag = dagbag.get_dag("train")
    assert dag is not None

def test_gauge_ingest_has_expected_tasks(dagbag):
    dag = dagbag.get_dag("gauge_ingest")
    task_ids = {t.task_id for t in dag.tasks}
    assert "fetch_and_store_readings" in task_ids

def test_weather_ingest_has_expected_tasks(dagbag):
    dag = dagbag.get_dag("weather_ingest")
    task_ids = {t.task_id for t in dag.tasks}
    assert "fetch_and_store_weather" in task_ids

def test_condition_score_dag_schedule(dagbag):
    dag = dagbag.get_dag("condition_score")
    # Should run at 7:30am MT = 13:30 UTC
    assert "30 13" in dag.schedule_interval

def test_train_dag_is_weekly(dagbag):
    dag = dagbag.get_dag("train")
    assert "0 9" in dag.schedule_interval  # Monday 3am MT = 9am UTC
