from unittest import mock

import pytest

from background.web import app


@pytest.fixture
def client():
    return app.test_client()


def test_create_email_starts_task(client):
    with mock.patch("background.web.send_email_once") as task:
        task.delay.return_value.id = "task-id"
        response = client.post("/emails", json={"to": "user@example.com", "message_id": "m1"})
    assert response.status_code == 202
    assert response.get_json() == {"task_id": "task-id", "message_id": "m1"}
    task.delay.assert_called_once_with("m1", "user@example.com", "Привет", "Письмо из фоновой задачи")


def test_create_email_rejects_bad_address(client):
    with mock.patch("background.web.send_email_once") as task:
        response = client.post("/emails", json={"to": "не адрес"})
    assert response.status_code == 400
    task.delay.assert_not_called()


def test_report_with_summary_starts_chain(client):
    with mock.patch("background.web.chain") as chain:
        result = chain.return_value.apply_async.return_value
        result.id, result.parent.id = "summary-id", "report-id"
        response = client.post("/reports/summary")
    assert response.status_code == 202
    body = response.get_json()
    assert body["task_id"] == "summary-id" and body["report_task_id"] == "report-id"
