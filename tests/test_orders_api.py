import json
import pytest
from unittest.mock import MagicMock, patch
import requests

from FunPayAPI.common import exceptions, enums
from FunPayAPI.types import OrderShortcut, OrderStatuses

SAMPLE_ORDER_API_RESPONSE = {
    "status": "SUCCESS",
    "data": {
        "TEST_ORDER_99": {
            "order_uid": "TEST_ORDER_99",
            "status": "paid",
            "currency": "rub",
            "amount": "450.00",
            "section": {
                "local_id": 1086,
                "type_id": "lot"
            },
            "buyer": {
                "user_id": 111222,
                "name": "BuyerSteamUser"
            },
            "seller": {
                "user_id": 123456,
                "name": "TestSeller"
            },
            "chat": {
                "node_name": "users-111222-123456"
            },
            "type_data": {
                "amount": 1,
                "player": "steam_login_77",
                "secrets": [{"value": "secret_key_or_link"}],
                "fields": {
                    "login": {
                        "value": "steam_login_77",
                        "name": "Логин Steam",
                        "field_type_id": "text"
                    }
                }
            },
            "review": {
                "text": "Отличный продавец!",
                "rating": 5,
                "reply": "Спасибо за покупку!",
                "hidden": False
            }
        }
    }
}

def test_get_order_success(initiated_account):
    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = SAMPLE_ORDER_API_RESPONSE

    with patch.object(initiated_account, "method", return_value=mock_resp) as mock_method:
        order = initiated_account.get_order("TEST_ORDER_99")

        # Check call parameters
        mock_method.assert_called_once()
        args, kwargs = mock_method.call_args
        assert args[0] == "post"
        assert args[1] == "https://funpay.com/api/orders/get"

        # Check parsed Order fields
        assert order.id == "TEST_ORDER_99"
        assert order.status == enums.OrderStatuses.PAID
        assert order.price == 450.00
        assert order.currency == enums.Currency.RUB
        assert order.buyer_id == 111222
        assert order.buyer_username == "BuyerSteamUser"
        assert order.seller_id == 123456
        assert order.seller_username == "TestSeller"
        assert order.chat_id == "users-111222-123456"
        assert order.player == "steam_login_77"
        assert order.secrets == ["secret_key_or_link"]
        assert "login" in order.fields
        assert order.fields["login"].value == "steam_login_77"
        assert order.review.rating == 5
        assert order.review.text == "Отличный продавец!"

from datetime import datetime

def test_get_orders_by_ids_validation(initiated_account):
    # Empty order_ids
    with pytest.raises(ValueError):
        initiated_account.get_orders_by_ids()

    # More than 10 order_ids
    with pytest.raises(ValueError):
        initiated_account.get_orders_by_ids(*[f"ORDER_{i}" for i in range(11)])

def test_get_order_api_error_status(initiated_account):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.request.url = "https://funpay.com/api/orders/get"
    mock_resp.json.return_value = {"status": "ERROR", "msg": "Order not found"}

    with patch.object(initiated_account, "method", return_value=mock_resp):
        with pytest.raises(exceptions.RequestFailedError):
            initiated_account.get_order("NON_EXISTING")

def test_get_order_shortcut_with_and_without_cache(initiated_account):
    # Case 1: runner is None -> falls back to get_sales
    shortcut = OrderShortcut(
        "TEST_ORDER_1", "Steam Topup", 100.0, enums.Currency.RUB,
        "Buyer", 111, 55555, enums.OrderStatuses.PAID,
        datetime.now(), "Steam", None, "<html></html>"
    )
    with patch.object(initiated_account, "get_sales", return_value=(None, [shortcut], "ru", {})):
        res = initiated_account.get_order_shortcut("TEST_ORDER_1")
        assert res.id == "TEST_ORDER_1"

    # Case 2: runner with cached saved_orders
    runner_mock = MagicMock()
    runner_mock.saved_orders = {"TEST_ORDER_1": shortcut}
    initiated_account.runner = runner_mock
    res_cached = initiated_account.get_order_shortcut("TEST_ORDER_1")
    assert res_cached == shortcut

def test_refund_success_and_error(initiated_account):
    # Success
    mock_success = MagicMock()
    mock_success.status_code = 200
    mock_success.request.url = "https://funpay.com/orders/refund"
    mock_success.json.return_value = {"error": 0, "msg": "Возврат оформлен"}

    with patch.object(initiated_account, "method", return_value=mock_success) as mock_m:
        initiated_account.refund("ORDER_REFUND_1")
        args, kwargs = mock_m.call_args
        assert args[1] == "orders/refund"
        assert args[3]["id"] == "ORDER_REFUND_1"
        assert args[3]["csrf_token"] == initiated_account.csrf_token

    # Error
    mock_err = MagicMock()
    mock_err.status_code = 200
    mock_err.request.url = "https://funpay.com/orders/refund"
    mock_err.json.return_value = {"error": 1, "msg": "Заказ уже закрыт"}

    with patch.object(initiated_account, "method", return_value=mock_err):
        with pytest.raises(exceptions.RefundError):
            initiated_account.refund("ORDER_REFUND_2")
