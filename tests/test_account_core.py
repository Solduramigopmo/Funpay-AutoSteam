import json
import pytest
from unittest.mock import MagicMock, patch
import requests

from FunPayAPI import Account
from FunPayAPI.common import exceptions, enums

def test_account_init():
    acc1 = Account("golden_key_1")
    assert acc1.golden_key == "golden_key_1"
    assert "Chrome" in acc1.user_agent
    assert acc1.is_initiated is False

    acc2 = Account("golden_key_2", user_agent="CustomAgent/2.0", requests_timeout=15)
    assert acc2.user_agent == "CustomAgent/2.0"
    assert acc2.requests_timeout == 15

def test_chat_id_private():
    # Int ID
    assert Account.chat_id_private(12345) is True
    # String digits
    assert Account.chat_id_private("12345") is True
    # Modern format users-{id1}-{id2}
    assert Account.chat_id_private("users-100-200") is True
    # Public or invalid format
    assert Account.chat_id_private("chat-public-room") is False
    assert Account.chat_id_private("something_else") is False
    assert Account.chat_id_private(None) is False

def test_method_headers_and_cookies(dummy_account):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {}
    mock_resp.cookies.get_dict.return_value = {}
    mock_resp.request = MagicMock(url="https://funpay.com/")

    with patch.object(dummy_account.session, "request", return_value=mock_resp) as mock_req:
        dummy_account.method("get", "https://funpay.com/", {}, {})
        
        _, kwargs = mock_req.call_args
        cookies = kwargs.get("cookies", {})
        headers = kwargs.get("headers", {})

        assert cookies["golden_key"] == "test_golden_key_12345"
        assert cookies["cookie_prefs"] == "1"
        assert headers.get("user-agent") == dummy_account.user_agent

def test_method_error_handling(dummy_account):
    # 403 raises UnauthorizedError
    mock_403 = MagicMock()
    mock_403.status_code = 403
    mock_403.headers = {}
    mock_403.cookies.get_dict.return_value = {}
    mock_403.request = MagicMock(url="https://funpay.com/")

    with patch.object(dummy_account.session, "request", return_value=mock_403):
        with pytest.raises(exceptions.UnauthorizedError):
            dummy_account.method("get", "https://funpay.com/", {}, {})

    # 500 raises RequestFailedError when raise_not_200=True
    mock_500 = MagicMock()
    mock_500.status_code = 500
    mock_500.headers = {}
    mock_500.cookies.get_dict.return_value = {}
    mock_500.request = MagicMock(url="https://funpay.com/")

    with patch.object(dummy_account.session, "request", return_value=mock_500):
        with pytest.raises(exceptions.RequestFailedError):
            dummy_account.method("get", "https://funpay.com/", {}, {}, raise_not_200=True)

def test_account_get_parsing(dummy_account):
    mock_html = """
    <!DOCTYPE html>
    <html lang="ru">
    <body data-app-data='{"locale": "ru", "userId": 987654, "csrf-token": "csrf_test_abc"}'>
        <div class="user-link-name">SuperTrader</div>
        <a class="menu-item-logout" href="https://funpay.com/account/logout?csrf=abc">Выход</a>
        <span class="badge badge-trade">5</span>
        <span class="badge badge-balance">1 250,50 ₽</span>
        <span class="badge badge-orders">2</span>
    </body>
    </html>
    """
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {}
    mock_resp.content = mock_html.encode("utf-8")
    mock_resp.cookies.get_dict.return_value = {"PHPSESSID": "new_phpsessid_789"}
    mock_resp.request = MagicMock(url="https://funpay.com/")

    with patch.object(dummy_account, "method", return_value=mock_resp):
        with patch.object(dummy_account, "_Account__setup_categories"):
            dummy_account.get()

    assert dummy_account.is_initiated is True
    assert dummy_account.id == 987654
    assert dummy_account.username == "SuperTrader"
    assert dummy_account.csrf_token == "csrf_test_abc"
    assert dummy_account.phpsessid == "new_phpsessid_789"
    assert dummy_account.active_sales == 5
    assert dummy_account.active_purchases == 2
    assert dummy_account.total_balance == 1250.50
    assert dummy_account.currency == enums.Currency.RUB

def test_get_payload_data_formatting(initiated_account):
    payload = initiated_account.get_payload_data(
        chats_data={111: "User1", 222: "User2"},
        last_order_event_tag="order_tag_123",
        last_msg_event_tag="msg_tag_456",
        buyer_viewing_ids=[555],
        request={"action": "test_action"}
    )
    objects = payload["objects"]
    types_in_objects = [obj["type"] for obj in objects]
    
    assert "chat_node" in types_in_objects
    assert "chat_bookmarks" in types_in_objects
    assert "orders_counters" in types_in_objects
    assert "c-p-u" in types_in_objects
    assert payload["request"] == {"action": "test_action"}

def test_abuse_runner_fallback_without_active_runner(initiated_account):
    # When runner is None or not running, abuse_runner directly calls runner_request
    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.json.return_value = {"objects": [], "response": None}

    with patch.object(initiated_account, "runner_request", return_value=mock_resp) as mock_req:
        res = initiated_account.abuse_runner(last_order_event_tag="tag1")
        assert res == mock_resp
        assert mock_req.called
