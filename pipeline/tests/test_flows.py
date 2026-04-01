import sys
sys.path.insert(0, "pipeline")
import pytest
from prefect.flows import Flow
from prefect.tasks import Task

from flows.ingest_score import (
    ingest_score_flow,
    fetch_weather_task,
    fetch_gauge_task,
    score_conditions_task,
)
from flows.train import train_flow, train_and_promote_task


# --- Flow type and name ---

def test_ingest_score_is_prefect_flow():
    assert isinstance(ingest_score_flow, Flow)


def test_ingest_score_flow_name():
    assert ingest_score_flow.name == "ingest-score"


def test_train_is_prefect_flow():
    assert isinstance(train_flow, Flow)


def test_train_flow_name():
    assert train_flow.name == "train"


# --- Task types ---

def test_fetch_weather_is_prefect_task():
    assert isinstance(fetch_weather_task, Task)


def test_fetch_gauge_is_prefect_task():
    assert isinstance(fetch_gauge_task, Task)


def test_score_conditions_is_prefect_task():
    assert isinstance(score_conditions_task, Task)


def test_train_and_promote_is_prefect_task():
    assert isinstance(train_and_promote_task, Task)


# --- Retry configuration ---

def test_fetch_weather_task_retries():
    assert fetch_weather_task.retries == 2


def test_fetch_gauge_task_retries():
    assert fetch_gauge_task.retries == 2


def test_score_conditions_task_retries():
    assert score_conditions_task.retries == 1


def test_train_and_promote_task_retries():
    assert train_and_promote_task.retries == 1


# --- Deployment construction ---

def test_ingest_score_deployment_name():
    deployment = ingest_score_flow.to_deployment(name="ingest-score", cron="0 * * * *")
    assert deployment.name == "ingest-score"


def test_train_deployment_name():
    deployment = train_flow.to_deployment(name="train", cron="0 9 * * 1")
    assert deployment.name == "train"
