import logging
import random
from typing import List, Optional

from django.core.management.base import BaseCommand
from django.db.models import Exists, OuterRef

from products.models import Category, Store
from scrapers.falabella import FalabellaScraper

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Scrapea productos de N categorías hoja aleatorias para una tienda"

    def add_arguments(self, parser):
        parser.add_argument("store_code", type=str)
        parser.add_argument("--headless", action="store_true", default=False)
        parser.add_argument("--trigger", type=str, default="MANUAL")
        parser.add_argument("--count", type=int, default=2)

    def _get_leaf_categories(self, store: Store) -> List[Category]:
        children_with_url = Category.objects.filter(
            parent=OuterRef("pk"),
            is_active=True,
            url__gt="",
        )

        qs = (
            Category.objects.filter(store=store, is_active=True, url__gt="")
            .annotate(has_leaf_children=Exists(children_with_url))
            .filter(has_leaf_children=False)
            .select_related("parent", "parent__parent")
        )
        return list(qs)

    def handle(self, *args, **options):
        store_code = (options["store_code"] or "").strip().upper()
        headless = bool(options["headless"])
        trigger = (options["trigger"] or "MANUAL").strip()
        count = int(options["count"] or 2)

        store: Optional[Store] = Store.objects.filter(code=store_code).first()
        if not store:
            self.stdout.write(self.style.ERROR(f"Tienda no encontrada: {store_code}"))
            return

        scraper = FalabellaScraper(store=store, headless=headless)
        run = scraper.start_run(trigger_type=trigger)
        scraper.setup_driver()

        try:
            leafs = self._get_leaf_categories(store)
            if not leafs:
                self.stdout.write(self.style.ERROR("No hay categorías hoja con url para esta tienda"))
                scraper.finish_run("FAILED")
                return

            if count > len(leafs):
                count = len(leafs)

            selected = random.sample(leafs, count)
            total_saved = 0
            total_scraped = 0

            for cat in selected:
                cat_path = cat.get_full_path() if hasattr(cat, "get_full_path") else cat.name
                self.stdout.write(f"Categoria: {cat_path}")
                self.stdout.write(f"URL: {cat.url}")

                items = scraper.scrape_products(cat.url)
                total_scraped += len(items)

                saved_here = 0
                for item in items:
                    listing = scraper.persist_product_snapshot(category=cat, product_data=item)
                    if listing:
                        saved_here += 1

                total_saved += saved_here
                self.stdout.write(f"Productos extraídos: {len(items)}")
                self.stdout.write(f"Productos persistidos: {saved_here}")

            if hasattr(run, "products_count"):
                run.products_count = total_saved
                run.save(update_fields=["products_count"])

            scraper.finish_run("COMPLETED")
            self.stdout.write(self.style.SUCCESS("Scraping de productos completado"))
            self.stdout.write(f"ScraperRun ID: {run.id}")
            self.stdout.write(f"Productos extraídos: {total_scraped}")
            self.stdout.write(f"Productos persistidos: {total_saved}")

        except Exception as e:
            scraper.log_error(error_type="OTHER", error_message=str(e))
            scraper.finish_run("FAILED")
            raise
        finally:
            scraper.teardown_driver()
