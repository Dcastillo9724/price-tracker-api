"""
Clase base para scrapers.

Responsabilidades:
- Crear/cerrar driver
- Crear y finalizar ScraperRun
- Logging estructurado de errores
- Helpers para persistir categorías en BD (árbol de 3 niveles)
- Persistencia idempotente de snapshots de productos y precios
"""

import logging
import traceback
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any, Dict, List, Optional

from django.db import IntegrityError, transaction
from django.utils import timezone
from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait

from products.models import Category, Price, Product, ProductListing, Store
from scrapers.models import ScraperError, ScraperRun
from .selenium_config import SeleniumConfig

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    def __init__(self, store: Store, headless: bool = False):
        self.store = store
        self.headless = headless
        self.driver: Optional[webdriver.Chrome] = None
        self.wait: Optional[WebDriverWait] = None
        self.scraper_run: Optional[ScraperRun] = None


    def setup_driver(self) -> None:
        self.driver, self.wait = SeleniumConfig.create_driver(headless=self.headless)
        logger.info("Driver configurado para %s", self.store.name)

    def teardown_driver(self) -> None:
        if self.driver:
            try:
                self.driver.quit()
                logger.info("Driver cerrado exitosamente")
            except Exception as e:
                logger.error("Error cerrando driver: %s", e, exc_info=True)

    @abstractmethod
    def scrape_categories(self) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def scrape_products(self, category_url: str) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def start_run(self, trigger_type: str = "MANUAL") -> ScraperRun:
        self.scraper_run = ScraperRun.objects.create(
            store=self.store,
            trigger_type=trigger_type,
            status=ScraperRun.Status.PENDING,
        )
        self.scraper_run.mark_as_running()
        logger.info("ScraperRun iniciado: %s para %s", self.scraper_run.id, self.store.name)
        return self.scraper_run

    def finish_run(self, status: str = "COMPLETED") -> None:
        if not self.scraper_run:
            return

        if status == "COMPLETED":
            self.scraper_run.mark_as_completed()
        elif status == "FAILED":
            self.scraper_run.mark_as_failed()
        elif status == "PARTIAL":
            self.scraper_run.mark_as_partial()

        logger.info("ScraperRun finalizado: %s con estado %s", self.scraper_run.id, status)

    def log_error(
        self,
        error_type: str,
        error_message: str,
        url: str = "",
        stack_trace: str = "",
    ) -> None:
        if not self.scraper_run:
            logger.warning("No hay ScraperRun activo para registrar error")
            return

        ScraperError.objects.create(
            scraper_run=self.scraper_run,
            error_type=error_type,
            error_message=error_message,
            url=url,
            stack_trace=stack_trace,
        )

        self.scraper_run.errors_count += 1
        self.scraper_run.save(update_fields=["errors_count"])

        logger.error("Error registrado: %s - %s", error_type, error_message)

    def save_category(
        self,
        *,
        name: str,
        parent: Optional[Category],
        url: str = "",
    ) -> Category:
        obj, _created = Category.objects.update_or_create(
            store=self.store,
            parent=parent,
            name=name,
            defaults={"url": url} if url else {},
        )
        return obj

    @transaction.atomic
    def save_category_tree(self, tree: List[Dict[str, Any]]) -> int:
        count = 0

        for parent_data in tree:
            parent_name = (parent_data.get("name") or "").strip()
            if not parent_name:
                continue

            parent_cat = self.save_category(name=parent_name, parent=None, url="")
            count += 1

            for block_data in parent_data.get("children", []):
                block_name = (block_data.get("name") or "").strip()
                if not block_name:
                    continue

                block_cat = self.save_category(name=block_name, parent=parent_cat, url="")
                count += 1

                for leaf in block_data.get("children", []):
                    leaf_name = (leaf.get("name") or "").strip()
                    leaf_url = (leaf.get("url") or "").strip()
                    if not leaf_name:
                        continue

                    self.save_category(name=leaf_name, parent=block_cat, url=leaf_url)
                    count += 1

        return count


    @staticmethod
    def _to_decimal(value: Any) -> Optional[Decimal]:
        if value is None:
            return None
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value)).quantize(Decimal("0.01"))
        except Exception:
            return None

    @transaction.atomic
    def persist_product_snapshot(
        self,
        *,
        category: Category,
        product_data: Dict[str, Any],
    ) -> Optional[ProductListing]:
        """
        Idempotente por (product, store) usando update_or_create.
        Crea siempre un registro Price si hay price.
        """
        name = (product_data.get("name") or "").strip()
        url = (product_data.get("url") or "").strip()
        price = self._to_decimal(product_data.get("price"))
        original_price = self._to_decimal(product_data.get("original_price"))
        is_available = bool(product_data.get("is_available", True))

        if not name or not url or price is None:
            return None

        product, _ = Product.objects.get_or_create(
            name=name,
            category=category,
            defaults={
                "brand": (product_data.get("brand") or "").strip(),
                "model": (product_data.get("model") or "").strip(),
                "description": (product_data.get("description") or "").strip(),
                "is_active": True,
            },
        )

        listing, _ = ProductListing.objects.update_or_create(
            product=product,
            store=self.store,
            defaults={
                "url": url,
                "is_available": is_available,
                "stock_status": (product_data.get("stock_status") or "").strip(),
                "is_active": True,
                "last_scraped_at": timezone.now(),
            },
        )

        if original_price is not None and original_price <= price:
            original_price = None

        try:
            Price.objects.create(
                listing=listing,
                price=price,
                original_price=original_price,
                is_available=is_available,
            )
        except IntegrityError as e:
            # Si por alguna razón hay colisión rara, no tumbamos el run
            self.log_error(
                error_type="DB",
                error_message=str(e),
                url=url,
                stack_trace=traceback.format_exc(),
            )

        return listing

    def run(self, *, trigger_type: str = "MANUAL", scrape_type: str = "categories") -> ScraperRun:
        try:
            self.start_run(trigger_type=trigger_type)
            self.setup_driver()

            if scrape_type == "categories":
                logger.info("Iniciando scraping de categorías para %s", self.store.name)
                tree = self.scrape_categories()
                logger.info("Categorías extraídas (padres): %s", len(tree))

                saved = self.save_category_tree(tree)
                logger.info("Nodos de categorías persistidos (aprox): %s", saved)
            else:
                logger.warning("Scraping de products aún no implementado en run()")

            self.finish_run("COMPLETED")

        except Exception as e:
            logger.error("Error durante scraping: %s", str(e), exc_info=True)
            self.log_error(
                error_type="OTHER",
                error_message=str(e),
                stack_trace=traceback.format_exc(),
            )
            if self.scraper_run:
                self.finish_run("FAILED")

        finally:
            self.teardown_driver()

        return self.scraper_run
