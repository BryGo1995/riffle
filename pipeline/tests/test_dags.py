import sys
sys.path.insert(0, "pipeline")
import os
os.environ.setdefault("AIRFLOW_HOME", "/tmp/airflow_test")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://riffle:riffle@localhost/riffle")
os.environ.setdefault("MLFLOW_TRACKING_URI", "http://localhost:5000")
import pytest
from airflow.models import DagBag


@pytest.fixture(scope="module")
def dagbag():
    return DagBag(dag_folder="pipeline/dags", include_examples=False)


def test_ingest_score_dag_loads(dagbag):
    dag = dagbag.get_dag("ingest_score")
    assert dag is not None
    assert dagbag.import_errors == {}


def test_train_dag_loads(dagbag):
    dag = dagbag.get_dag("train")
    assert dag is not None


def test_ingest_score_dag_is_hourly(dagbag):
    dag = dagbag.get_dag("ingest_score")
    assert dag.schedule_interval == "0 * * * *"


def test_ingest_score_dag_has_expected_tasks(dagbag):
    dag = dagbag.get_dag("ingest_score")
    task_ids = {t.task_id for t in dag.tasks}
    assert task_ids == {"fetch_weather", "fetch_gauge", "score_conditions"}


def test_score_conditions_depends_on_both_ingest_tasks(dagbag):
    dag = dagbag.get_dag("ingest_score")
    score_task = dag.get_task("score_conditions")
    upstream_ids = {t.task_id for t in score_task.upstream_list}
    assert "fetch_weather" in upstream_ids
    assert "fetch_gauge" in upstream_ids


def test_old_dags_removed(dagbag):
    assert dagbag.get_dag("gauge_ingest") is None
    assert dagbag.get_dag("weather_ingest") is None
    assert dagbag.get_dag("condition_score") is None
