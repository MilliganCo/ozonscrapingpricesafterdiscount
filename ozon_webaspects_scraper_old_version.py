#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import json
import re
import time
import random
from typing import Optional, List
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# Тестовые ссылки
URLS = [
    "https://www.ozon.ru/product/3093214674",
    "https://www.ozon.ru/product/1573232610",
    "https://www.ozon.ru/product/1899938976",
]


def extract_product_id_from_url(url: str) -> Optional[str]:
    """
    Берём product_id из URL.
    Работает и для /product/1899938976, и для /product/slug-1899938976/.
    """
    path = urlparse(url).path  # напр. "/product/1899938976" или "/product/slug-1899938976/"
    m = re.search(r"(\d+)(?:/)?$", path)
    return m.group(1) if m else None


def check_product_availability(page) -> bool:
    """
    Проверяет, есть ли товар в наличии.
    Возвращает True если товар в наличии, False если нет.
    """
    try:
        page_text = page.inner_text("body").lower()
        
        # Ищем индикаторы отсутствия товара (более строгая проверка)
        out_of_stock_indicators = [
            "нет в наличии",
            "недоступен",
            "out of stock",
            "распродано",
            "закончился",
            "недоступен для заказа",
            "временно недоступен",
            "товар закончился",
            "нет в продаже",
        ]
        
        for indicator in out_of_stock_indicators:
            if indicator in page_text:
                return False
        
        # Ищем индикаторы наличия товара
        in_stock_indicators = [
            "в корзину",
            "купить",
            "добавить в корзину",
            "в наличии",
            "заказать",
        ]
        
        # Если есть хотя бы один индикатор наличия, считаем что товар есть
        found_in_stock = False
        for indicator in in_stock_indicators:
            if indicator in page_text:
                found_in_stock = True
                break
        
        # Если не нашли индикаторы наличия, но и не нашли индикаторы отсутствия,
        # проверяем наличие кнопки "В корзину" или "Купить" через селекторы
        if not found_in_stock:
            try:
                # Ищем кнопки покупки через селекторы
                buy_buttons = page.query_selector_all(
                    "button:has-text('В корзину'), button:has-text('Купить'), "
                    "[data-widget='cart'] button, [class*='AddToCart']"
                )
                if len(buy_buttons) > 0:
                    found_in_stock = True
            except Exception:
                pass
        
        return found_in_stock
    except Exception:
        # В случае ошибки считаем что товар есть (чтобы не пропустить товары из-за ошибок)
        return True


def extract_price_from_variant(variant: dict) -> Optional[int]:
    """
    Из одного варианта достаём цену.
    Приоритет: числовое поле variant["price"],
    если его нет — парсим строковое variant["data"]["price"] ("1 268 ₽").
    """
    # 1) число
    if "price" in variant and isinstance(variant["price"], (int, float)):
        return int(variant["price"])

    # 2) строка в data.price
    data = variant.get("data") or {}
    price_str = data.get("price")
    if price_str:
        digits = re.sub(r"\D", "", price_str)
        return int(digits) if digits else None

    return None


def extract_original_price_from_variant(variant: dict) -> Optional[int]:
    """
    Извлекает перечеркнутую цену (originalPrice) из варианта.
    """
    data = variant.get("data") or {}
    original_price_str = data.get("originalPrice")
    if original_price_str:
        digits = re.sub(r"\D", "", original_price_str)
        return int(digits) if digits else None
    return None


def get_price_from_page_text(page, url: str) -> Optional[int]:
    """
    Альтернативный метод: ищем цены напрямую в тексте страницы.
    Ищем все числа с символом ₽, исключаем перечеркнутые цены,
    и возвращаем минимальную.
    """
    product_id = extract_product_id_from_url(url)
    if not product_id:
        return None
    
    try:
        # Пробуем найти цены через различные селекторы
        price_selectors = [
            "[data-widget='webPrice']",
            "[data-widget='webCurrentPrice']",
            ".tsHeadline500Medium",
            "[class*='Price']",
            "[class*='price']",
        ]
        
        all_prices = []
        
        for selector in price_selectors:
            try:
                elements = page.query_selector_all(selector)
                for el in elements:
                    text = el.inner_text()
                    # Ищем цены в тексте элемента
                    price_pattern = r'(\d[\d\s]*)\s*₽'
                    matches = re.findall(price_pattern, text)
                    for match in matches:
                        digits = re.sub(r'\s', '', match)
                        try:
                            price = int(digits)
                            if 100 <= price <= 1000000:  # Разумный диапазон цен
                                all_prices.append(price)
                        except ValueError:
                            continue
            except Exception:
                continue
        
        # Если не нашли через селекторы, пробуем весь текст страницы
        if not all_prices:
            page_text = page.inner_text("body")
            price_pattern = r'(\d[\d\s]*)\s*₽'
            matches = re.findall(price_pattern, page_text)
            for match in matches:
                digits = re.sub(r'\s', '', match)
                try:
                    price = int(digits)
                    if 100 <= price <= 1000000:
                        all_prices.append(price)
                except ValueError:
                    continue
        
        if not all_prices:
            return None
        
        # Убираем дубликаты и возвращаем минимальную цену
        unique_prices = list(set(all_prices))
        return min(unique_prices)
    except Exception as e:
        print(f"    Ошибка при поиске цены в тексте: {e}")
        return None




def scrape_ozon_prices(
    urls: List[str],
    out_csv: str = "ozon_prices.csv",
    proxy: Optional[str] = None,
) -> None:
    with sync_playwright() as p:
        # Пробуем использовать реальный Chrome вместо Chromium для лучшей совместимости
        try:
            browser = p.chromium.launch(
                headless=True,
                channel="chrome",  # Используем реальный Chrome
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                ],
            )
        except Exception:
            # Если Chrome не найден, используем Chromium с улучшенными настройками
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                ],
            )

        # Создаем контекст с более реалистичными настройками
        context = browser.new_context(
            locale="ru-RU",
            timezone_id="Europe/Moscow",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
            extra_http_headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                "Accept-Encoding": "gzip, deflate, br, zstd",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Cache-Control": "max-age=0",
            },
        )
        
        # Удаляем признаки автоматизации
        page = context.new_page()
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            
            // Переопределяем plugins
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            
            // Переопределяем languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['ru-RU', 'ru', 'en-US', 'en']
            });
            
            // Переопределяем permissions
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );
        """)
        results: List[dict] = []

        for i, url in enumerate(urls, start=1):
            print(f"[{i}/{len(urls)}] Открываю {url!r}")
            price: Optional[int] = None

            try:
                # Сначала заходим на главную страницу Ozon для установки cookies
                if i == 1:
                    page.goto("https://www.ozon.ru", wait_until="domcontentloaded", timeout=30_000)
                    time.sleep(random.uniform(2.0, 4.0))
                
                # Переходим на страницу товара
                page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                
                # Имитируем человеческое поведение: небольшие задержки и движения мыши
                time.sleep(random.uniform(2.0, 4.0))
                
                # Прокручиваем страницу постепенно, как человек
                page.evaluate("""
                    () => {
                        const scrollStep = 200;
                        const scrollDelay = 50;
                        let currentPosition = 0;
                        const maxPosition = document.body.scrollHeight / 2;
                        
                        const scrollInterval = setInterval(() => {
                            currentPosition += scrollStep;
                            window.scrollBy(0, scrollStep);
                            if (currentPosition >= maxPosition) {
                                clearInterval(scrollInterval);
                            }
                        }, scrollDelay);
                    }
                """)
                time.sleep(random.uniform(1.5, 2.5))
                
                # Возвращаемся наверх
                page.evaluate("window.scrollTo({ top: 0, behavior: 'smooth' })")
                time.sleep(random.uniform(2.0, 3.0))
                
                # Ждем загрузки динамического контента
                try:
                    page.wait_for_load_state("networkidle", timeout=10_000)
                except PlaywrightTimeoutError:
                    pass  # Игнорируем, если не загрузилось

                # Проверяем, не попали ли мы на challenge страницу
                page_title = page.title()
                page_url = page.url
                
                if "Доступ ограничен" in page_title or "challenge" in page_url.lower() or "abt-challenge" in page.content():
                    print("    Обнаружена challenge страница, ждем...")
                    # Ждем и пробуем обновить страницу
                    time.sleep(random.uniform(5.0, 8.0))
                    page.reload(wait_until="domcontentloaded", timeout=30_000)
                    time.sleep(random.uniform(3.0, 5.0))
                    
                    # Проверяем снова
                    if "Доступ ограничен" in page.title() or "challenge" in page.url.lower():
                        print("    Не удалось обойти challenge, пропускаем...")
                        price = None
                    else:
                        # Продолжаем парсинг
                        is_available = check_product_availability(page)
                        if not is_available:
                            print("    Товар отсутствует в наличии, пропускаем")
                            price = None
                        else:
                            price = get_price_from_page_text(page, url)
                else:
                    # Сохраняем HTML страницы для первой ссылки (для отладки)
                    if i == 1:
                        html_content = page.content()
                        debug_filename = f"debug_page_{extract_product_id_from_url(url)}.html"
                        with open(debug_filename, "w", encoding="utf-8") as f:
                            f.write(html_content)
                        print(f"    HTML страницы сохранен в {debug_filename!r}")

                    # Проверяем наличие товара
                    is_available = check_product_availability(page)
                    if not is_available:
                        print("    Товар отсутствует в наличии, пропускаем")
                        price = None
                    else:
                        # Ищем цену
                        price = get_price_from_page_text(page, url)

            except PlaywrightTimeoutError:
                print("    TIMEOUT: страница грузится слишком долго")
            except Exception as e:
                print(f"    ERROR: {e!r}")

            print(f"    Найденная цена: {price}")
            results.append(
                {
                    "url": url,
                    "product_id": extract_product_id_from_url(url),
                    "price": price,
                }
            )

            time.sleep(random.uniform(2.0, 5.0))

        browser.close()

    # Сохраняем результат
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["url", "product_id", "ozon_card_price"])
        writer.writeheader()
        for result in results:
            writer.writerow({
                "url": result["url"],
                "product_id": result["product_id"],
                "ozon_card_price": result["price"],
            })

    print(f"\nГотово. Результат записан в {out_csv!r}")


if __name__ == "__main__":
    scrape_ozon_prices(URLS)
