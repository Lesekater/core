"""The tests for the calendar component."""

from __future__ import annotations

from collections.abc import Generator
from datetime import timedelta
from http import HTTPStatus
from typing import Any
from unittest.mock import Mock, patch

from freezegun import freeze_time
import pytest
from syrupy.assertion import SnapshotAssertion
import voluptuous as vol

from homeassistant.components import calendar, conversation
from homeassistant.components.calendar import (
    DOMAIN,
    SERVICE_GET_EVENTS,
    intent as calendar_intent,
)
from homeassistant.components.calendar.intent import INTENT_CALENDAR_GET_EVENTS
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceNotSupported
from homeassistant.helpers import intent
from homeassistant.setup import async_setup_component
import homeassistant.util.dt as dt_util

from .conftest import MockCalendarEntity, MockConfigEntry

from tests.common import async_mock_service
from tests.typing import ClientSessionGenerator, WebSocketGenerator


@pytest.fixture(name="frozen_time")
def mock_frozen_time() -> str | None:
    """Fixture to set a frozen time used in tests.

    This is needed so that it can run before other fixtures.
    """
    return None


@pytest.fixture(autouse=True)
def mock_set_frozen_time(frozen_time: str | None) -> Generator[None]:
    """Fixture to freeze time that also can work for other fixtures."""
    if not frozen_time:
        yield
    else:
        with freeze_time(frozen_time):
            yield


@pytest.fixture(name="setup_platform", autouse=True)
async def mock_setup_platform(
    hass: HomeAssistant,
    set_time_zone: None,
    frozen_time: str | None,
    mock_setup_integration: None,
    config_entry: MockConfigEntry,
) -> None:
    """Fixture to setup platforms used in the test and fixtures are set up in the right order."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()


@pytest.fixture(autouse=True)
async def setup_intents(hass: HomeAssistant) -> None:
    """Set up the intents."""
    assert await async_setup_component(hass, "homeassistant", {})
    await calendar_intent.async_setup_intents(hass)


@pytest.mark.parametrize(
    ("range_value"),
    [
        ("today"),
        ("week"),
    ],
)
async def test_calendar_get_events_intent(
    hass: HomeAssistant, range_value: str
) -> None:
    """Test the calendar get events intent."""
    calls = async_mock_service(
        hass,
        domain=calendar.DOMAIN,
        service=calendar.SERVICE_GET_EVENTS,
        schema=calendar.SERVICE_GET_EVENTS_SCHEMA,
        response={
            "calendar.test_calendar": {
                "events": [
                    {
                        "start": "2025-09-17",
                        "end": "2025-09-18",
                        "summary": "Home Assistant 12th birthday",
                        "description": "",
                    },
                    {
                        "start": "2025-09-17T14:00:00-05:00",
                        "end": "2025-09-18T15:00:00-05:00",
                        "summary": "Champagne",
                        "description": "",
                    },
                ]
            }
        },
        supports_response=SupportsResponse.ONLY,
    )

    now = dt_util.now()
    patch_now = patch.multiple(
        "homeassistant.util.dt",
        now=Mock(return_value=now),
    )
    patch_match_targets = patch(
        "homeassistant.helpers.intent.async_match_targets",
        return_value=Mock(
            is_match=True, states=[Mock(entity_id="calendar.test_calendar")]
        ),
    )

    with patch_now, patch_match_targets:
        response = await intent.async_handle(
            hass,
            DOMAIN,
            INTENT_CALENDAR_GET_EVENTS,
            {
                "calendar": {"value": "test_calendar"},
                "range": {"value": range_value},
            },
            assistant=conversation.DOMAIN,
        )

        assert len(calls) == 1
        call = calls[0]
        assert call.domain == calendar.DOMAIN
        assert call.service == calendar.SERVICE_GET_EVENTS
        assert call.data == {
            "entity_id": ["calendar.test_calendar"],
            "start_date_time": now,
            "end_date_time": (
                dt_util.start_of_local_day()
                + (timedelta(days=1) if range_value == "today" else timedelta(days=7))
            ),
        }

        assert response.speech_slots["events"] == [
            {
                "start": "2025-09-17",
                "end": "2025-09-18",
                "all_day": True,
                "summary": "Home Assistant 12th birthday",
                "description": "",
                "location": "",
                "recurring": None,
            },
            {
                "start": "2025-09-17T14:00:00-05:00",
                "end": "2025-09-18T15:00:00-05:00",
                "all_day": False,
                "summary": "Champagne",
                "description": "",
                "location": "",
                "recurring": None,
            },
        ]


async def test_events_http_api(
    hass: HomeAssistant, hass_client: ClientSessionGenerator
) -> None:
    """Test the calendar demo view."""
    client = await hass_client()
    start = dt_util.now()
    end = start + timedelta(days=1)
    response = await client.get(
        f"/api/calendars/calendar.calendar_1?start={start.isoformat()}&end={end.isoformat()}"
    )
    assert response.status == HTTPStatus.OK
    events = await response.json()
    assert events[0]["summary"] == "Future Event"


async def test_events_http_api_missing_fields(
    hass: HomeAssistant, hass_client: ClientSessionGenerator
) -> None:
    """Test the calendar demo view."""
    client = await hass_client()
    response = await client.get("/api/calendars/calendar.calendar_2")
    assert response.status == HTTPStatus.BAD_REQUEST


async def test_events_http_api_error(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    test_entities: list[MockCalendarEntity],
) -> None:
    """Test the calendar demo view."""
    client = await hass_client()
    start = dt_util.now()
    end = start + timedelta(days=1)

    test_entities[0].async_get_events.side_effect = HomeAssistantError("Failure")

    response = await client.get(
        f"/api/calendars/calendar.calendar_1?start={start.isoformat()}&end={end.isoformat()}"
    )
    assert response.status == HTTPStatus.INTERNAL_SERVER_ERROR
    assert await response.json() == {"message": "Error reading events: Failure"}


async def test_events_http_api_dates_wrong_order(
    hass: HomeAssistant, hass_client: ClientSessionGenerator
) -> None:
    """Test the calendar demo view."""
    client = await hass_client()
    start = dt_util.now()
    end = start + timedelta(days=-1)
    response = await client.get(
        f"/api/calendars/calendar.calendar_1?start={start.isoformat()}&end={end.isoformat()}"
    )
    assert response.status == HTTPStatus.BAD_REQUEST


async def test_calendars_http_api(
    hass: HomeAssistant, hass_client: ClientSessionGenerator
) -> None:
    """Test the calendar demo view."""
    client = await hass_client()
    response = await client.get("/api/calendars")
    assert response.status == HTTPStatus.OK
    data = await response.json()
    assert data == [
        {"entity_id": "calendar.calendar_1", "name": "Calendar 1"},
        {"entity_id": "calendar.calendar_2", "name": "Calendar 2"},
    ]


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (
            {
                "type": "calendar/event/create",
                "entity_id": "calendar.calendar_1",
                "event": {
                    "summary": "Bastille Day Party",
                    "dtstart": "1997-07-14T17:00:00+00:00",
                    "dtend": "1997-07-15T04:00:00+00:00",
                },
            },
            "not_supported",
        ),
        (
            {
                "type": "calendar/event/create",
                "entity_id": "calendar.calendar_99",
                "event": {
                    "summary": "Bastille Day Party",
                    "dtstart": "1997-07-14T17:00:00+00:00",
                    "dtend": "1997-07-15T04:00:00+00:00",
                },
            },
            "not_found",
        ),
        (
            {
                "type": "calendar/event/delete",
                "entity_id": "calendar.calendar_1",
                "uid": "some-uid",
            },
            "not_supported",
        ),
        (
            {
                "type": "calendar/event/delete",
                "entity_id": "calendar.calendar_99",
                "uid": "some-uid",
            },
            "not_found",
        ),
        (
            {
                "type": "calendar/event/update",
                "entity_id": "calendar.calendar_1",
                "uid": "some-uid",
                "event": {
                    "summary": "Bastille Day Party",
                    "dtstart": "1997-07-14T17:00:00+00:00",
                    "dtend": "1997-07-15T04:00:00+00:00",
                },
            },
            "not_supported",
        ),
        (
            {
                "type": "calendar/event/update",
                "entity_id": "calendar.calendar_99",
                "uid": "some-uid",
                "event": {
                    "summary": "Bastille Day Party",
                    "dtstart": "1997-07-14T17:00:00+00:00",
                    "dtend": "1997-07-15T04:00:00+00:00",
                },
            },
            "not_found",
        ),
    ],
)
async def test_unsupported_websocket(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, payload, code
) -> None:
    """Test unsupported websocket command."""
    client = await hass_ws_client(hass)
    await client.send_json(
        {
            "id": 1,
            **payload,
        }
    )
    resp = await client.receive_json()
    assert resp.get("id") == 1
    assert resp.get("error")
    assert resp["error"].get("code") == code


async def test_unsupported_create_event_service(hass: HomeAssistant) -> None:
    """Test unsupported service call."""
    await async_setup_component(hass, "homeassistant", {})
    with pytest.raises(
        ServiceNotSupported,
        match="Entity calendar.calendar_1 does not "
        "support action calendar.create_event",
    ):
        await hass.services.async_call(
            DOMAIN,
            "create_event",
            {
                "start_date_time": "1997-07-14T17:00:00+00:00",
                "end_date_time": "1997-07-15T04:00:00+00:00",
                "summary": "Bastille Day Party",
            },
            target={"entity_id": "calendar.calendar_1"},
            blocking=True,
        )


@pytest.mark.parametrize(
    ("date_fields", "expected_error", "error_match"),
    [
        (
            {},
            vol.error.MultipleInvalid,
            "must contain at least one of start_date, start_date_time, in",
        ),
        (
            {
                "start_date": "2022-04-01",
            },
            vol.error.MultipleInvalid,
            "Start and end dates must both be specified",
        ),
        (
            {
                "end_date": "2022-04-02",
            },
            vol.error.MultipleInvalid,
            "must contain at least one of start_date, start_date_time, in.",
        ),
        (
            {
                "start_date_time": "2022-04-01T06:00:00",
            },
            vol.error.MultipleInvalid,
            "Start and end datetimes must both be specified",
        ),
        (
            {
                "end_date_time": "2022-04-02T07:00:00",
            },
            vol.error.MultipleInvalid,
            "must contain at least one of start_date, start_date_time, in.",
        ),
        (
            {
                "start_date": "2022-04-01",
                "start_date_time": "2022-04-01T06:00:00",
                "end_date_time": "2022-04-02T07:00:00",
            },
            vol.error.MultipleInvalid,
            "must contain at most one of start_date, start_date_time, in.",
        ),
        (
            {
                "start_date_time": "2022-04-01T06:00:00",
                "end_date_time": "2022-04-01T07:00:00",
                "end_date": "2022-04-02",
            },
            vol.error.MultipleInvalid,
            "Start and end dates must both be specified",
        ),
        (
            {
                "start_date": "2022-04-01",
                "end_date_time": "2022-04-02T07:00:00",
            },
            vol.error.MultipleInvalid,
            "Start and end dates must both be specified",
        ),
        (
            {
                "start_date_time": "2022-04-01T07:00:00",
                "end_date": "2022-04-02",
            },
            vol.error.MultipleInvalid,
            "Start and end dates must both be specified",
        ),
        (
            {
                "in": {
                    "days": 2,
                    "weeks": 2,
                }
            },
            vol.error.MultipleInvalid,
            "two or more values in the same group of exclusion 'event_types'",
        ),
        (
            {
                "start_date": "2022-04-01",
                "end_date": "2022-04-02",
                "in": {
                    "days": 2,
                },
            },
            vol.error.MultipleInvalid,
            "must contain at most one of start_date, start_date_time, in.",
        ),
        (
            {
                "start_date_time": "2022-04-01T07:00:00",
                "end_date_time": "2022-04-01T07:00:00",
                "in": {
                    "days": 2,
                },
            },
            vol.error.MultipleInvalid,
            "must contain at most one of start_date, start_date_time, in.",
        ),
        (
            {
                "start_date_time": "2022-04-01T06:00:00+00:00",
                "end_date_time": "2022-04-01T07:00:00+01:00",
            },
            vol.error.MultipleInvalid,
            "Expected all values to have the same timezone",
        ),
        (
            {
                "start_date_time": "2022-04-01T07:00:00",
                "end_date_time": "2022-04-01T06:00:00",
            },
            vol.error.MultipleInvalid,
            "Expected minimum event duration",
        ),
        (
            {
                "start_date": "2022-04-02",
                "end_date": "2022-04-01",
            },
            vol.error.MultipleInvalid,
            "Expected minimum event duration",
        ),
        (
            {
                "start_date": "2022-04-01",
                "end_date": "2022-04-01",
            },
            vol.error.MultipleInvalid,
            "Expected minimum event duration",
        ),
    ],
    ids=[
        "missing_all",
        "missing_end_date",
        "missing_start_date",
        "missing_end_datetime",
        "missing_start_datetime",
        "multiple_start",
        "multiple_end",
        "missing_end_date",
        "missing_end_date_time",
        "multiple_in",
        "unexpected_in_with_date",
        "unexpected_in_with_datetime",
        "inconsistent_timezone",
        "incorrect_date_order",
        "incorrect_datetime_order",
        "dates_not_exclusive",
    ],
)
async def test_create_event_service_invalid_params(
    hass: HomeAssistant,
    date_fields: dict[str, Any],
    expected_error: type[Exception],
    error_match: str | None,
) -> None:
    """Test creating an event using the create_event service."""

    with pytest.raises(expected_error, match=error_match):
        await hass.services.async_call(
            "calendar",
            "create_event",
            {
                "summary": "Bastille Day Party",
                **date_fields,
            },
            target={"entity_id": "calendar.calendar_1"},
            blocking=True,
        )


@pytest.mark.parametrize(
    "frozen_time", ["2023-06-22 10:30:00+00:00"], ids=["frozen_time"]
)
@pytest.mark.parametrize(
    ("service", "expected"),
    [
        (
            SERVICE_GET_EVENTS,
            {
                "calendar.calendar_1": {
                    "events": [
                        {
                            "start": "2023-06-22T05:00:00-06:00",
                            "end": "2023-06-22T06:00:00-06:00",
                            "summary": "Future Event",
                            "description": "Future Description",
                            "location": "Future Location",
                        }
                    ]
                }
            },
        ),
    ],
)
@pytest.mark.parametrize(
    ("start_time", "end_time"),
    [
        ("2023-06-22T04:30:00-06:00", "2023-06-22T06:30:00-06:00"),
        ("2023-06-22T04:30:00", "2023-06-22T06:30:00"),
        ("2023-06-22T10:30:00Z", "2023-06-22T12:30:00Z"),
    ],
)
async def test_list_events_service(
    hass: HomeAssistant,
    start_time: str,
    end_time: str,
    service: str,
    expected: dict[str, Any],
) -> None:
    """Test listing events from the service call using exlplicit start and end time.

    This test uses a fixed date/time so that it can deterministically test the
    string output values.
    """

    response = await hass.services.async_call(
        DOMAIN,
        service,
        target={"entity_id": ["calendar.calendar_1"]},
        service_data={
            "entity_id": "calendar.calendar_1",
            "start_date_time": start_time,
            "end_date_time": end_time,
        },
        blocking=True,
        return_response=True,
    )
    assert response == expected


@pytest.mark.parametrize(
    ("service"),
    [
        SERVICE_GET_EVENTS,
    ],
)
@pytest.mark.parametrize(
    ("entity", "duration"),
    [
        # Calendar 1 has an hour long event starting in 30 minutes. No events in the
        # next 15 minutes, but it shows up an hour from now.
        ("calendar.calendar_1", "00:15:00"),
        ("calendar.calendar_1", "01:00:00"),
        # Calendar 2 has a active event right now
        ("calendar.calendar_2", "00:15:00"),
    ],
)
@pytest.mark.parametrize("frozen_time", ["2023-10-19 13:50:05"], ids=["frozen_time"])
async def test_list_events_service_duration(
    hass: HomeAssistant,
    entity: str,
    duration: str,
    service: str,
    snapshot: SnapshotAssertion,
) -> None:
    """Test listing events using a time duration."""
    response = await hass.services.async_call(
        DOMAIN,
        service,
        {
            "entity_id": entity,
            "duration": duration,
        },
        blocking=True,
        return_response=True,
    )
    assert response == snapshot


async def test_list_events_positive_duration(hass: HomeAssistant) -> None:
    """Test listing events requires a positive duration."""
    with pytest.raises(vol.Invalid, match="should be positive"):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_GET_EVENTS,
            {
                "entity_id": "calendar.calendar_1",
                "duration": "-01:00:00",
            },
            blocking=True,
            return_response=True,
        )


async def test_list_events_exclusive_fields(hass: HomeAssistant) -> None:
    """Test listing events specifying fields that are exclusive."""
    end = dt_util.now() + timedelta(days=1)

    with pytest.raises(vol.Invalid, match="at most one of"):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_GET_EVENTS,
            {
                "entity_id": "calendar.calendar_1",
                "end_date_time": end,
                "duration": "01:00:00",
            },
            blocking=True,
            return_response=True,
        )


async def test_list_events_missing_fields(hass: HomeAssistant) -> None:
    """Test listing events missing some required fields."""
    with pytest.raises(vol.Invalid, match="at least one of"):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_GET_EVENTS,
            {
                "entity_id": "calendar.calendar_1",
            },
            blocking=True,
            return_response=True,
        )
