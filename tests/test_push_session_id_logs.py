"""The push session id authorizes pushes to a phone, so it must not reach the log at any level."""

import logging
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from custom_components.domika import push_server_errors
from custom_components.domika.domika_logger import LOGGER
from custom_components.domika.ha_event import flow as ha_event_flow
from custom_components.domika.push_data_storage.models import PushData
from custom_components.domika.sessions import flow as sessions_flow
from custom_components.domika.sessions import router as sessions_router
from custom_components.domika.storage.models import AppSession, Sessions

from .conftest import add_session

SECRET = "PUSH-SESSION-SECRET"
SUBSCRIPTION = {"entity_id": "light.a", "attribute": "s", "need_push": 1}


@pytest.fixture
def all_logs(caplog):
    caplog.set_level(logging.DEBUG, logger="custom_components.domika")
    with patch.object(LOGGER, "LOG_LEVEL", "FINEST"):
        yield caplog
    records = caplog.get_records("call")
    assert records, "nothing was logged, so the check proves nothing"
    assert SECRET not in "\n".join(record.getMessage() for record in records)


def _response(status: int) -> MagicMock:
    response = MagicMock()
    response.status = status
    response.json = AsyncMock(return_value={})
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    context.__aexit__ = AsyncMock(return_value=False)
    return context


def test_models_keep_the_id_out_of_their_repr():
    assert SECRET not in repr(AppSession("s", "u", SECRET, None, "h"))
    assert SECRET not in repr(Sessions("s", SECRET))
    assert SECRET not in repr(PushData("e", "s", SECRET, "light.a", "s", "on", "c", 1, 0))


async def test_verifying_a_push_session(hass, app_sessions, all_logs):
    with (
        patch.object(sessions_router.sessions_flow, "verify_push_session", AsyncMock(return_value=SECRET)),
        patch.object(sessions_router, "async_get_clientsession"),
    ):
        await sessions_router._verify_push_session(hass, "s", "key", "hash")


async def test_checking_the_push_token(hass, app_sessions, all_logs):
    add_session(app_sessions, "s", "owner", push_token_hash="hash", push_session_id=SECRET)

    await sessions_router._check_push_token(hass, "s", "hash")


@pytest.mark.parametrize("result", [SECRET, push_server_errors.PushSessionIdNotFoundError()])
async def test_removing_a_push_session_from_the_router(hass, app_sessions, all_logs, result):
    flow = AsyncMock(side_effect=result) if isinstance(result, Exception) else AsyncMock(return_value=result)
    with (
        patch.object(sessions_router.sessions_flow, "remove_push_session", flow),
        patch.object(sessions_router, "async_get_clientsession"),
    ):
        await sessions_router._remove_push_session(hass, "s")


@pytest.mark.parametrize("status", [204, 401])
async def test_removing_a_push_session_on_the_server(app_sessions, all_logs, status):
    add_session(app_sessions, "s", "owner", push_session_id=SECRET)
    http_session = Mock()
    http_session.delete.return_value = _response(status)

    try:
        await sessions_flow.remove_push_session(http_session, "s", "https://push.test", None)
    except push_server_errors.PushSessionIdNotFoundError as error:
        LOGGER.error("Push server error. %s", error)


async def test_sending_and_queueing_pushes(hass, app_sessions, push_data, all_logs):
    add_session(app_sessions, "s", "owner", push_session_id=SECRET, subscriptions=[SUBSCRIPTION])
    http_session = Mock()
    http_session.post.return_value = _response(204)

    await ha_event_flow._send_push_data(http_session, "https://push.test", 10, "s", SECRET, {"light.a": {}})
    push_data.process_entity_changes(app_sessions.push_subscriptions(), "light.a", {"s": "on"}, "e", 1, "c", 0)
    with (
        patch.object(ha_event_flow, "_send_push_data", AsyncMock()),
        patch.object(ha_event_flow, "async_get_clientsession"),
    ):
        await ha_event_flow.process_push_data(hass)


async def test_sending_a_critical_push(hass, app_sessions, all_logs):
    new_state = Mock()
    new_state.as_compressed_state = {"s": "on", "a": {"device_class": "smoke"}}
    event = Mock()
    event.data = {"entity_id": "binary_sensor.smoke", "old_state": None, "new_state": new_state}
    event.time_fired_timestamp = 1

    with (
        patch.object(ha_event_flow, "_send_push_data", AsyncMock()),
        patch.object(ha_event_flow, "async_get_clientsession"),
        patch.object(ha_event_flow, "async_get_translations", AsyncMock(return_value={})),
        patch.object(ha_event_flow.critical_sensor_service, "check_notification_type", return_value=False),
        patch.object(ha_event_flow.critical_sensor_service, "critical_push_needed", return_value=True),
        patch.object(ha_event_flow, "_get_critical_alert_payload", return_value={}),
        patch.object(ha_event_flow.APP_SESSIONS_STORAGE, "get_app_sessions_with_push_session", return_value=[Sessions("s", SECRET)]),
        patch.object(ha_event_flow.PUSHDATA_STORAGE, "process_entity_changes"),
    ):
        await ha_event_flow.register_event(hass, event)


def test_storage_operations(app_sessions, all_logs):
    add_session(app_sessions, "s", "owner", push_session_id=SECRET, subscriptions=[SUBSCRIPTION])

    app_sessions.push_subscriptions()
    app_sessions.resubscribe_push("missing", {"light.a": {"s"}})
    app_sessions.remove_push_session("s")

