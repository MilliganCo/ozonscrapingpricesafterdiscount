# Ozon Scraping Prices After Discount

> Public experimental source: see [PUBLICATION.md](PUBLICATION.md) for actual checks, known defects, restored modules and operational limits. Earlier audit decisions are historical.

Исследовательский Python/Playwright-скрипт для выборочной проверки карточек Ozon и извлечения витринных цен после скидок со страницы товара.

## Статус аудита

Держать private до legal/ToS review.

Причины:

- проект работает как web scraper конкретного marketplace;
- код содержит browser automation / anti-detection настройки;
- в текущем коде есть тестовые product URL;
- публичная публикация может выглядеть как обход ограничений площадки, даже если проект использовался для внутренней проверки цен.

## Что делает скрипт

- принимает список товарных URL;
- извлекает `product_id` из ссылок;
- проверяет наличие товара на странице;
- пытается достать текущую и исходную цену;
- сохраняет результаты во внешний CSV.

## Стек

- Python;
- Playwright;
- CSV output.

Ключевой файл: `ozon_webaspects_scraper_old_version.py`.

## Перед возможной публикацией

1. Проверить правила Ozon/marketplace ToS.
2. Заменить реальные/похожие product URL на neutral examples.
3. Удалить anti-detection формулировки и настройки, если нужен безопасный demo.
4. Добавить rate limits, CLI config и явное назначение для authorised/internal checks.
5. Выполнить full-history secret/data scan.

## License

Private до legal/security review.
