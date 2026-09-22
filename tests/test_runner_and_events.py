import time
import pytest
from unittest.mock import MagicMock, patch

from FunPayAPI import Account
from FunPayAPI.updater.runner import Runner
from FunPayAPI.updater import events
from FunPayAPI.common import exceptions, enums
from FunPayAPI.types import OrderShortcut, OrderStatuses, Currency

def test_runner_init_checks(dummy_account, initiated_account):
    # Uninitiated account should raise AccountNotInitiatedError
    with pytest.raises(exceptions.AccountNotInitiatedError):
        Runner(dummy_account)

    # Initiated account should succeed
    runner = Runner(initiated_account)
    assert runner.is_running is False
    assert initiated_account.runner == runner

    # Attaching second runner should fail
    with pytest.raises(Exception):
        Runner(initiated_account)

def test_runner_mark_and_update(initiated_account):
    runner = Runner(initiated_account)
    runner.mark_as_by_bot(chat_id=123, message_id=999)
    assert runner.by_bot_ids[123] == [999]

    runner.update_last_message(chat_id=123, message_id=999, message_text="Hello")
    assert runner.runner_last_messages[123] == [999, 999, "Hello"]

from datetime import datetime

def test_runner_parse_order_updates(initiated_account):
    runner = Runner(initiated_account)
    
    order1 = OrderShortcut("ORDER_1", "Desc 1", 100.0, Currency.RUB, "User1", 10, 55555,
                           OrderStatuses.PAID, datetime.now(), "Steam", None, "<html></html>")
    order2 = OrderShortcut("ORDER_2", "Desc 2", 200.0, Currency.RUB, "User2", 20, 55555,
                           OrderStatuses.PAID, datetime.now(), "Steam", None, "<html></html>")

    # First fetch: InitialOrderEvent
    with patch.object(initiated_account, "get_sales", return_value=(None, [order1], "ru", {})):
        evs1 = runner.parse_order_updates({"tag": "order_tag_1", "data": {"buyer": 0, "seller": 1}})
        initial_orders = [e for e in evs1 if isinstance(e, events.InitialOrderEvent)]
        assert len(initial_orders) == 1
        assert initial_orders[0].order.id == "ORDER_1"

    # Second fetch: new order added -> NewOrderEvent
    with patch.object(initiated_account, "get_sales", return_value=(None, [order1, order2], "ru", {})):
        evs2 = runner.parse_order_updates({"tag": "order_tag_2", "data": {"buyer": 0, "seller": 2}})
        new_orders = [e for e in evs2 if isinstance(e, events.NewOrderEvent)]
        assert len(new_orders) == 1
        assert new_orders[0].order.id == "ORDER_2"

    # Third fetch: order1 status changes to CLOSED -> OrderStatusChangedEvent
    order1_closed = OrderShortcut("ORDER_1", "Desc 1", 100.0, Currency.RUB, "User1", 10, 55555,
                                  OrderStatuses.CLOSED, datetime.now(), "Steam", None, "<html></html>")
    with patch.object(initiated_account, "get_sales", return_value=(None, [order1_closed, order2], "ru", {})):
        evs3 = runner.parse_order_updates({"tag": "order_tag_3", "data": {"buyer": 0, "seller": 1}})
        status_changed = [e for e in evs3 if isinstance(e, events.OrderStatusChangedEvent)]
        assert len(status_changed) == 1
        assert status_changed[0].order.id == "ORDER_1"
        assert status_changed[0].order.status == OrderStatuses.CLOSED

def test_runner_parse_chat_updates(initiated_account):
    runner = Runner(initiated_account)
    runner.make_msg_requests = False  # test shortcut events

    mock_chat_html = """
    <div class="chat-bookmarks">
        <a class="contact-item" data-id="555" data-node-msg="10" data-user-msg="10">
            <div class="media-user-name">Interlocutor</div>
            <div class="contact-item-message">Привет! Товар получен.</div>
        </a>
    </div>
    """

    chat_obj_data = {
        "type": "chat_bookmarks",
        "tag": "tag_chats_1",
        "data": {"html": mock_chat_html}
    }

    # First request: InitialChatEvent
    evs = runner.parse_chat_updates(chat_obj_data)
    assert any(isinstance(e, events.InitialChatEvent) for e in evs)

    # Transition from first request to subsequent requests
    runner._Runner__first_request = False

    # Second request with new message ID: LastChatMessageChangedEvent & ChatsListChangedEvent
    mock_chat_html2 = """
    <div class="chat-bookmarks">
        <a class="contact-item" data-id="555" data-node-msg="11" data-user-msg="11">
            <div class="media-user-name">Interlocutor</div>
            <div class="contact-item-message">Спасибо огромное!</div>
        </a>
    </div>
    """
    chat_obj_data2 = {
        "type": "chat_bookmarks",
        "tag": "tag_chats_2",
        "data": {"html": mock_chat_html2}
    }
    evs2 = runner.parse_chat_updates(chat_obj_data2)
    assert any(isinstance(e, events.LastChatMessageChangedEvent) for e in evs2)
    assert any(isinstance(e, events.ChatsListChangedEvent) for e in evs2)

def test_runner_listen_autostart_and_yield(initiated_account):
    runner = Runner(initiated_account)
    assert runner.is_running is False

    mock_updates = {
        "objects": [{
            "type": "orders_counters",
            "tag": "tag_ord",
            "data": {"buyer": 0, "seller": 0}
        }]
    }

    with patch.object(runner, "get_updates", return_value=mock_updates):
        with patch.object(initiated_account, "get_sales", return_value=(None, [], "ru", {})):
            # Listen should auto-start the loop thread and yield events
            gen = runner.listen(requests_delay=0.01)
            ev = next(gen)
            assert runner.is_running is True
            assert isinstance(ev, events.OrdersListChangedEvent) or ev is not None
