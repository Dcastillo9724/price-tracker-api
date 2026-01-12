"""
Clase base para scrapers.

Responsabilidades:
- Crear/cerrar driver
- Crear y finalizar ScraperRun
- Logging estructurado de errores
- Helpers para persistir categorías en BD (árbol de 3 niveles)
"""

import logging
import traceback
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from django.db import transaction
from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait

from products.models import Category, Store
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

    # ----------------------------
    # Selenium lifecycle
    # ----------------------------
    def setup_driver(self) -> None:
        self.driver, self.wait = SeleniumConfig.create_driver(headless=self.headless)
        logger.info(f"Driver configurado para {self.store.name}")

    def teardown_driver(self) -> None:
        if self.driver:
            try:
                self.driver.quit()
                logger.info("Driver cerrado exitosamente")
            except Exception as e:
                logger.error(f"Error cerrando driver: {e}", exc_info=True)

    # ----------------------------
    # Abstract API
    # ----------------------------
    @abstractmethod
    def scrape_categories(self) -> List[Dict[str, Any]]:
        """Debe retornar árbol jerárquico de categorías."""
        raise NotImplementedError

    @abstractmethod
    def scrape_products(self, category_url: str) -> List[Dict[str, Any]]:
        """(A futuro) extraer productos."""
        raise NotImplementedError

    # ----------------------------
    # ScraperRun
    # ----------------------------
    def start_run(self, trigger_type: str = "MANUAL") -> ScraperRun:
        self.scraper_run = ScraperRun.objects.create(
            store=self.store,
            trigger_type=trigger_type,
            status=ScraperRun.Status.PENDING,
        )
        self.scraper_run.mark_as_running()
        logger.info(f"ScraperRun iniciado: {self.scraper_run.id} para {self.store.name}")
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

        logger.info(f"ScraperRun finalizado: {self.scraper_run.id} con estado {status}")

    # ----------------------------
    # Error logging
    # ----------------------------
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

        logger.error(f"Error registrado: {error_type} - {error_message}")

    # ----------------------------
    # Persistencia de categorías
    # ----------------------------
    def save_category(
        self,
        *,
        name: str,
        parent: Optional[Category],
        url: str = "",
    ) -> Category:
        """
        Guarda/actualiza categoría de forma idempotente.
        Unicidad efectiva: (store, parent, name)
        """
        obj, created = Category.objects.update_or_create(
            store=self.store,
            parent=parent,
            name=name,
            defaults={"url": url} if url else {},
        )

        # Si ya existía pero no tenía url y ahora sí, queda actualizada
        return obj

    @transaction.atomic
    def save_category_tree(self, tree: List[Dict[str, Any]]) -> int:
        """
        Persiste un árbol:
        parent -> block -> leaf(url)

        Retorna cantidad de nodos creados/actualizados (aprox).
        """
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

    # ----------------------------
    # Orquestación
    # ----------------------------
    def run(self, *, trigger_type: str = "MANUAL", scrape_type: str = "categories") -> ScraperRun:
        """
        Ejecuta scraping.
        scrape_type: 'categories' o 'products' (products por ahora no hace nada)
        """
        try:
            self.start_run(trigger_type=trigger_type)
            self.setup_driver()

            if scrape_type == "categories":
                logger.info(f"Iniciando scraping de categorías para {self.store.name}")
                tree = self.scrape_categories()
                logger.info(f"Categorías extraídas (padres): {len(tree)}")

                saved = self.save_category_tree(tree)
                logger.info(f"Nodos de categorías persistidos (aprox): {saved}")

            else:
                logger.warning("Scraping de products aún no implementado en run()")

            self.finish_run("COMPLETED")

        except Exception as e:
            logger.error(f"Error durante scraping: {str(e)}", exc_info=True)
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
