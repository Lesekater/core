"""Tests for the todo intents."""

import pytest

from homeassistant.components import conversation
from homeassistant.components.todo import DOMAIN, TodoListEntity, intent as todo_intent
from homeassistant.const import ATTR_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent
from homeassistant.setup import async_setup_component

from . import create_mock_platform


@pytest.fixture(autouse=True)
async def setup_intents(hass: HomeAssistant) -> None:
    """Set up the intents."""
    assert await async_setup_component(hass, "homeassistant", {})
    await todo_intent.async_setup_intents(hass)


async def test_list_items_intent(
    hass: HomeAssistant,
    test_entity: TodoListEntity,
) -> None:
    """Test the list items intent."""

    await create_mock_platform(hass, [test_entity])
    test_entity._attr_name = "entity1"

    response = await intent.async_handle(
        hass,
        DOMAIN,
        todo_intent.INTENT_LIST_LIST_ITEMS,
        {ATTR_NAME: {"value": "entity1"}},
        assistant=conversation.DOMAIN,
    )
    assert response.response_type == intent.IntentResponseType.QUERY_ANSWER

    results = response.as_dict()["data"]["success"]

    assert len(results) == 1
    assert results[0]["name"] == "Item #1"


async def test_list_items_intent_raises(
    hass: HomeAssistant,
) -> None:
    """Test errors with the list items intent."""

    # Try to list items from list that does not exist
    with pytest.raises(intent.MatchFailedError):
        await intent.async_handle(
            hass,
            "test",
            todo_intent.INTENT_LIST_LIST_ITEMS,
            {ATTR_NAME: {"value": "This list does not exist"}},
            assistant=conversation.DOMAIN,
        )
