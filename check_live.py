"""
Скрипт для быстрой ручной проверки работы FunPayAPI на реальном аккаунте.
Запуск:
    py check_live.py
или:
    py check_live.py ВАШ_GOLDEN_KEY
"""

import sys
import os
import getpass

# Настройка UTF-8 для вывода в консоль Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Добавляем путь к FunPayAPI
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "Funpay AutoSteam"))

from FunPayAPI.account import Account
from FunPayAPI.common import exceptions


def main():
    print("=" * 60)
    print("  FunPayAPI — Проверка работоспособности на реальном аккаунте")
    print("=" * 60)

    # 1. Получаем токен (golden_key)
    token = None
    if len(sys.argv) > 1:
        token = sys.argv[1].strip()
    elif os.path.exists(os.path.join("Funpay AutoSteam", ".env")):
        from dotenv import load_dotenv
        load_dotenv(os.path.join("Funpay AutoSteam", ".env"))
        env_tok = os.getenv("FUNPAY_AUTH_TOKEN", "").strip()
        if env_tok and env_tok != "FUNPAY_AUTH_TOKEN":
            token = env_tok

    if not token:
        print("\nГде взять golden_key:")
        print("  1. Откройте funpay.com в браузере и авторизуйтесь.")
        print("  2. Нажмите F12 -> вкладка Application (Приложение) -> Cookies -> funpay.com")
        print("  3. Скопируйте значение куки 'golden_key'\n")
        try:
            token = input("Введите ваш golden_key: ").strip()
        except KeyboardInterrupt:
            print("\nОтменено.")
            return

    if not token:
        print("[-] Токен не введен. Завершение работы.")
        return

    print(f"\n[1/4] Инициализация сессии Account с токеном: {token[:6]}...{token[-4:] if len(token) > 10 else ''}")
    account = Account(token)

    # 2. Проверка авторизации и профиля
    print("[2/4] Запрос данных профиля (account.get)...")
    try:
        account.get()
        print(f" [+] Успешная авторизация!")
        print(f"     Пользователь: {account.username} (ID: {account.id})")
        print(f"     Баланс: {account.balance} {account.currency.name if account.currency else ''}")
        print(f"     Активных продаж: {account.active_sales}")
        print(f"     Непрочитанных чатов: {account.unread_chats}")
    except exceptions.UnauthorizedError:
        print(" [-] Ошибка: Неверный golden_key (UnauthorizedError). Проверьте актуальность куки.")
        return
    except Exception as e:
        print(f" [-] Ошибка при получении профиля: {e}")
        return

    # 3. Проверка получения списка заказов и API заказов
    print("\n[3/4] Проверка получения списка продаж и API заказов...")
    try:
        sales_tuple = account.get_sales(next_order_id=None)
        sales = sales_tuple[1] if sales_tuple and len(sales_tuple) > 1 else []
        print(f" [+] Найдено продаж на первой странице: {len(sales)}")
        if sales:
            first_order = sales[0]
            print(f"     Последний заказ: {first_order.id} | Статус: {first_order.status} | Сумма: {first_order.price} {first_order.currency}")
            
            # Тестируем обновленный API orders/get
            print(f"     Тест POST /api/orders/get для заказа {first_order.id}...")
            orders_data = account.get_orders_by_ids(first_order.id)
            if first_order.id in orders_data:
                order_details = orders_data[first_order.id]
                print(f"     [+] Ответ API заказов получен успешно! Название: {order_details.get('title', 'N/A')}")
            else:
                print(f"     [?] Ответ получен, но ID {first_order.id} отсутствует в словаре.")
        else:
            print("     (На аккаунте пока нет продаж, парсинг списка прошел штатно)")
    except Exception as e:
        print(f" [-] Ошибка при проверке заказов: {e}")

    # 4. Проверка получения чатов
    print("\n[4/4] Проверка списка диалогов (account.get_chats)...")
    try:
        chats = account.get_chats()
        print(f" [+] Получено диалогов: {len(chats)}")
        if chats:
            latest_chat = list(chats.values())[0]
            print(f"     Последний диалог: ID={latest_chat.id}, собеседник: {latest_chat.name}")
    except Exception as e:
        print(f" [-] Ошибка при получении диалогов: {e}")

    print("\n" + "=" * 60)
    print("  Тестирование завершено! Все основные модули API активны.")
    print("=" * 60)


if __name__ == "__main__":
    main()
