import pytest
from unittest.mock import MagicMock, patch
import requests

from FunPayAPI.common import exceptions, enums
from FunPayAPI import types

def test_send_message_with_chat_msg_text(initiated_account):
    mock_resp = MagicMock()
    mock_resp.request.url = "https://funpay.com/runner/"
    mock_resp.status_code = 200
    mock_resp.content = b""
    mock_resp.json.return_value = {
        "response": {"error": None},
        "objects": [{
            "type": "chat_node",
            "tag": "msg_tag_123",
            "data": {
                "node": {"id": 55555, "name": "BuyerUser", "silent": False},
                "messages": [{
                    "id": 999111,
                    "html": '<div class="chat-msg-item"><div class="chat-msg-text">Здравствуйте! Заказ готов.</div></div>'
                }]
            }
        }]
    }

    with patch.object(initiated_account, "abuse_runner", return_value=mock_resp):
        msg = initiated_account.send_message(55555, "Здравствуйте! Заказ готов.")
        assert msg.id == 999111
        assert msg.text == "Здравствуйте! Заказ готов."
        assert msg.chat_id == 55555
        assert msg.tag == "msg_tag_123"

def test_send_message_with_fallback_selector(initiated_account):
    # Older selector .message-text
    mock_resp = MagicMock()
    mock_resp.request.url = "https://funpay.com/runner/"
    mock_resp.status_code = 200
    mock_resp.content = b""
    mock_resp.json.return_value = {
        "response": {"error": None},
        "objects": [{
            "type": "chat_node",
            "tag": "msg_tag_456",
            "data": {
                "node": {"id": "users-10-20", "silent": False},
                "messages": [{
                    "id": 888222,
                    "html": '<div class="chat-msg-item"><div class="message-text">Текст из старого селектора</div></div>'
                }]
            }
        }]
    }

    with patch.object(initiated_account, "abuse_runner", return_value=mock_resp):
        msg = initiated_account.send_message("users-10-20", "Привет")
        assert msg.id == 888222
        assert msg.text == "Текст из старого селектора"

def test_send_message_with_empty_messages_list(initiated_account):
    # If messages list is empty in response, it should not raise IndexError
    mock_resp = MagicMock()
    mock_resp.request.url = "https://funpay.com/runner/"
    mock_resp.status_code = 200
    mock_resp.content = b""
    mock_resp.json.return_value = {
        "response": {"error": None},
        "objects": [{
            "type": "chat_node",
            "tag": "msg_tag_789",
            "data": {
                "node": {"id": 77777, "silent": False},
                "messages": []
            }
        }]
    }

    with patch.object(initiated_account, "abuse_runner", return_value=mock_resp):
        msg = initiated_account.send_message(77777, "Fallback test")
        assert msg.id == 0
        assert msg.text == "Fallback test"
        assert msg.chat_id == 77777

def test_send_message_flood_error(initiated_account):
    mock_resp = MagicMock()
    mock_resp.request.url = "https://funpay.com/runner/"
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "response": {"error": "Нельзя отправлять сообщения слишком часто."},
        "objects": []
    }

    with patch.object(initiated_account, "abuse_runner", return_value=mock_resp):
        with pytest.raises(exceptions.MessageNotDeliveredError):
            initiated_account.send_message(12345, "Спам")
        assert initiated_account.last_flood_err_time > 0

def test_parse_messages_system_and_badges(initiated_account):
    raw_messages = [
        # System message (author 0)
        {
            "id": 1,
            "author": 0,
            "html": '<div role="alert">Покупатель Buyer123 оплатил заказ #ABCDEF12. Buyer123, не забудьте потом нажать кнопку «Подтвердить выполнение заказа».</div>'
        },
        # Message with support badge
        {
            "id": 2,
            "author": 888,
            "html": """
            <div class="media-user-name">
                <a href="/users/888/">SupportAgent</a>
                <span class="chat-msg-author-label label label-success">поддержка</span>
            </div>
            <div class="chat-msg-text">Здравствуйте, техподдержка слушает.</div>
            """
        },
        # Regular user message
        {
            "id": 3,
            "author": 999,
            "html": '<div class="chat-msg-text">Когда будет выдан товар?</div>'
        }
    ]

    parsed = initiated_account._Account__parse_messages(raw_messages, chat_id=12345)
    assert len(parsed) == 3

    # System message check
    assert parsed[0].author_id == 0
    assert "оплатил заказ" in parsed[0].text
    assert parsed[0].type == enums.MessageTypes.ORDER_PURCHASED

    # Support message check
    assert parsed[1].author_id == 888
    assert parsed[1].is_support is True
    assert parsed[1].is_employee is True
    assert "техподдержка слушает" in parsed[1].text

    # User message check
    assert parsed[2].author_id == 999
    assert parsed[2].text == "Когда будет выдан товар?"
    assert parsed[2].type == enums.MessageTypes.NON_SYSTEM
