"""Commands and views acting on an app session must not accept another user's session."""

from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.websocket_api import ERR_UNAUTHORIZED

from custom_components.domika.api.push_resubscribe_view import DomikaAPIPushResubscribeView
from custom_components.domika.api.push_states_with_delay_view import DomikaAPIPushStatesWithDelayView
from custom_components.domika.ha_event import router as ha_event_router
from custom_components.domika.push_data_storage.models import PushData
from custom_components.domika.sessions import router as sessions_router
from custom_components.domika.subscription import router as subscription_router

from .conftest import add_session, make_connection

SUBSCRIPTION = {"entity_id": "light.a", "attribute": "s", "need_push": 1}


def _assert_rejected(connection) -> None:
    connection.send_error.assert_called_once()
    assert connection.send_error.call_args.args[1] == ERR_UNAUTHORIZED
    connection.send_result.assert_not_called()


async def test_remove_app_session_rejects_foreign_session(hass, app_sessions):
    add_session(app_sessions, "s", "owner")
    connection = make_connection("intruder")

    await sessions_router.websocket_domika_remove_app_session.__wrapped__(
        hass, connection, {"id": 1, "app_session_id": "s"},
    )

    _assert_rejected(connection)
    hass.data["domika"]["entry"].async_create_task.assert_not_called()


async def test_remove_app_session_accepts_other_user_session_on_same_device(hass, app_sessions):
    add_session(app_sessions, "previous_login", "old_user", push_token_hash="device")
    add_session(app_sessions, "current", "new_user", push_token_hash="device")
    connection = make_connection("new_user")

    await sessions_router.websocket_domika_remove_app_session.__wrapped__(
        hass, connection, {"id": 1, "app_session_id": "previous_login"},
    )

    connection.send_error.assert_not_called()
    hass.data["domika"]["entry"].async_create_task.assert_called_once()


async def test_remove_app_session_accepts_own_session(hass, app_sessions):
    add_session(app_sessions, "s", "owner")
    connection = make_connection("owner")

    await sessions_router.websocket_domika_remove_app_session.__wrapped__(
        hass, connection, {"id": 1, "app_session_id": "s"},
    )

    connection.send_error.assert_not_called()
    hass.data["domika"]["entry"].async_create_task.assert_called_once()


async def test_push_session_commands_reject_foreign_session(hass, app_sessions):
    add_session(app_sessions, "s", "owner", push_token_hash="device")
    commands = [
        (sessions_router.websocket_domika_update_push_token, {"push_token_hash": "device"}),
        (sessions_router.websocket_domika_remove_push_session, {}),
        (
            sessions_router.websocket_domika_update_push_session,
            {"original_transaction_id": "t", "push_token_hex": "p", "platform": "ios", "environment": "sandbox"},
        ),
        (
            sessions_router.websocket_domika_update_push_session_v2,
            {
                "original_transaction_id": "t",
                "push_token_hex": "p",
                "platform": "ios",
                "push_environment": "sandbox",
                "transaction_environment": "sandbox",
            },
        ),
        (
            sessions_router.websocket_domika_verify_push_session,
            {"verification_key": "k", "push_token_hash": "device"},
        ),
    ]
    for handler, extra in commands:
        connection = make_connection("intruder")
        await handler.__wrapped__(hass, connection, {"id": 1, "app_session_id": "s", **extra})
        _assert_rejected(connection)
    hass.data["domika"]["entry"].async_create_task.assert_not_called()


async def test_resubscribe_rejects_foreign_session(hass, app_sessions):
    add_session(app_sessions, "s", "owner", subscriptions=[SUBSCRIPTION])
    connection = make_connection("intruder")

    await subscription_router.websocket_domika_resubscribe.__wrapped__(
        hass, connection, {"id": 1, "app_session_id": "s", "subscriptions": {"light.b": {"s": 1}}},
    )

    _assert_rejected(connection)
    assert app_sessions._data["s"]["subscriptions"] == [SUBSCRIPTION]


async def test_confirm_event_rejects_foreign_session(hass, app_sessions, push_data):
    add_session(app_sessions, "s", "owner")
    push_data.insert(PushData("e1", "s", "p", "light.a", "s", "on", "c", 1, 0))
    connection = make_connection("intruder")

    await ha_event_router.websocket_domika_confirm_events.__wrapped__(
        hass, connection, {"id": 1, "app_session_id": "s", "event_ids": ["e1"]},
    )

    _assert_rejected(connection)
    assert len(push_data.storage) == 1


def _request(app_session_id: str, user_id: str, body: dict) -> MagicMock:
    user = MagicMock()
    user.id = user_id
    request = MagicMock()
    request.headers = {"X-App-Session-Id": app_session_id}
    request.json = AsyncMock(return_value=body)
    request.__getitem__.side_effect = {"hass_user": user}.__getitem__
    return request


async def test_push_resubscribe_view_rejects_foreign_session(hass, app_sessions):
    add_session(app_sessions, "s", "owner", subscriptions=[SUBSCRIPTION])
    request = _request("s", "intruder", {"subscriptions": {"light.a": ["x"]}})

    with patch("custom_components.domika.api.push_resubscribe_view.async_get_hass", return_value=hass):
        response = await DomikaAPIPushResubscribeView().post(request)

    assert response.status == HTTPStatus.UNAUTHORIZED
    assert app_sessions._data["s"]["subscriptions"] == [SUBSCRIPTION]


async def test_push_states_view_rejects_foreign_session(hass, app_sessions, push_data):
    add_session(app_sessions, "s", "owner")
    push_data.insert(PushData("e1", "s", "p", "light.a", "s", "on", "c", 1, 0))
    request = _request("s", "intruder", {"entity_id": "light.a"})

    with patch("custom_components.domika.api.push_states_with_delay_view.async_get_hass", return_value=hass):
        response = await DomikaAPIPushStatesWithDelayView().post(request)

    assert response.status == HTTPStatus.UNAUTHORIZED
    assert len(push_data.storage) == 1


async def test_push_states_view_accepts_own_session(hass, app_sessions, push_data):
    add_session(app_sessions, "s", "owner")
    request = _request("s", "owner", {"entity_id": "light.a"})

    with (
        patch("custom_components.domika.api.push_states_with_delay_view.async_get_hass", return_value=hass),
        patch("custom_components.domika.api.service.async_get_hass", return_value=hass),
    ):
        response = await DomikaAPIPushStatesWithDelayView().post(request)

    assert response.status == HTTPStatus.OK


def _update_app_session_message(app_session_id: str, push_token_hash: str = "") -> dict:
    return {
        "id": 1,
        "app_session_id": app_session_id,
        "push_token_hash": push_token_hash,
        "os_platform": "ios",
        "os_version": "27",
        "app_id": "app",
        "app_version": "1",
    }


async def _update_app_session(hass, connection, message: dict) -> dict:
    with patch.object(sessions_router, "_get_hass_network_properties", AsyncMock(return_value={})):
        await sessions_router.websocket_domika_update_app_session.__wrapped__(hass, connection, message)
    return connection.send_result.call_args.args[1]


async def test_update_app_session_keeps_another_users_session(hass, app_sessions):
    add_session(app_sessions, "victim", "owner", push_session_id="push", subscriptions=[SUBSCRIPTION])
    connection = make_connection("intruder")

    result = await _update_app_session(hass, connection, _update_app_session_message("victim"))

    victim = app_sessions.get_app_session("victim")
    assert victim is not None
    assert victim.user_id == "owner"
    assert victim.push_session_id == "push"
    assert result["app_session_id"] != "victim"
    assert app_sessions.get_app_session(result["app_session_id"]).user_id == "intruder"


# Signing in as another user on the same phone: the app offers its previous session id and removes the old one.
async def test_switching_accounts_on_a_device_still_cleans_up_the_old_session(hass, app_sessions):
    add_session(app_sessions, "previous_login", "old_user", push_token_hash="device")
    connection = make_connection("new_user")

    result = await _update_app_session(hass, connection, _update_app_session_message("previous_login", "device"))

    assert result["old_app_session_ids"] == ["previous_login"]
    removal = make_connection("new_user")
    await sessions_router.websocket_domika_remove_app_session.__wrapped__(
        hass, removal, {"id": 2, "app_session_id": "previous_login"},
    )
    removal.send_error.assert_not_called()
