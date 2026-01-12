"""
Comando de management para ejecutar scrapers.

Uso:
    python manage.py run_scraper <store_code> [--type=categories|products] [--headless]
"""

import logging
from django.core.management.base import BaseCommand, CommandError
from products.models import Store
from scrapers.falabella import FalabellaScraper

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Ejecuta el scraper para una tienda específica"

    def add_arguments(self, parser):
        parser.add_argument("store_code", type=str, help="Código de la tienda (ej: FA)")

        parser.add_argument(
            "--type",
            type=str,
            default="categories",
            choices=["categories", "products"],
            help="Tipo de scraping: categories o products",
        )

        parser.add_argument(
            "--headless",
            action="store_true",
            help="Ejecutar en modo headless (sin interfaz gráfica)",
        )

        parser.add_argument(
            "--trigger",
            type=str,
            default="MANUAL",
            choices=["MANUAL", "SCHEDULED", "API"],
            help="Tipo de trigger",
        )

    def handle(self, *args, **options):
        store_code = options["store_code"].upper()
        scrape_type = options["type"]
        headless = options["headless"]
        trigger = options["trigger"]

        self.stdout.write(self.style.SUCCESS(f"\n🚀 Iniciando scraper para tienda: {store_code}\n"))

        try:
            store = Store.objects.get(code=store_code)
        except Store.DoesNotExist:
            raise CommandError(f'Tienda con código "{store_code}" no existe')

        if not store.is_active:
            raise CommandError(f'Tienda "{store.name}" no está activa')

        if not store.scraping_enabled:
            raise CommandError(f'Scraping deshabilitado para "{store.name}"')

        scraper = self._get_scraper(store=store, headless=headless)
        if not scraper:
            raise CommandError(f'No hay scraper implementado para "{store.name}"')

        try:
            self.stdout.write(f"Tipo de scraping: {scrape_type}")
            self.stdout.write(f"Modo headless: {headless}")
            self.stdout.write(f"Trigger: {trigger}\n")

            scraper_run = scraper.run(trigger_type=trigger, scrape_type=scrape_type)

            self.stdout.write(self.style.SUCCESS("\n✅ Scraping completado exitosamente"))
            self.stdout.write(f"ScraperRun ID: {scraper_run.id}")
            self.stdout.write(f"Estado: {scraper_run.status}")
            self.stdout.write(f"Productos scrapeados: {scraper_run.products_scraped}")
            self.stdout.write(f"Errores: {scraper_run.errors_count}")
            self.stdout.write(f"Tasa de éxito: {scraper_run.get_success_rate()}%\n")

        except Exception as e:
            logger.error(f"Error en comando run_scraper: {e}", exc_info=True)
            raise CommandError(str(e))

    def _get_scraper(self, store: Store, headless: bool):
        scrapers = {
            "FA": FalabellaScraper,
        }
        scraper_class = scrapers.get(store.code)
        if not scraper_class:
            return None
        return scraper_class(store=store, headless=headless)
