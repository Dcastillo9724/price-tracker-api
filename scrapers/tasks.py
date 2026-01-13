import logging
import traceback
from typing import Dict, Any, Optional

from celery import shared_task
from django.db import transaction
from django.db.models import Exists, OuterRef

from products.models import Store, Category
from scrapers.models import ScraperRun
from scrapers.falabella import FalabellaScraper

logger = logging.getLogger(__name__)


def _get_store_or_raise(store_code: str) -> Store:
    code = (store_code or "").strip().upper()
    store = Store.objects.filter(code=code).first()
    if not store:
        raise ValueError(f"Tienda no encontrada: {code}")
    return store


def _leaf_categories_qs(store: Store):
    children_with_url = Category.objects.filter(
        parent=OuterRef("pk"),
        is_active=True,
        url__gt="",
    )
    return (
        Category.objects.filter(store=store, is_active=True, url__gt="")
        .annotate(has_leaf_children=Exists(children_with_url))
        .filter(has_leaf_children=False)
        .select_related("parent", "parent__parent")
    )


@shared_task(bind=True, autoretry_for=(), retry_backoff=False)
def run_categories_task(self, store_code: str, headless: bool = True, trigger_type: str = "API") -> Dict[str, Any]:
    store = _get_store_or_raise(store_code)

    scraper = FalabellaScraper(store=store, headless=headless)
    run = scraper.start_run(trigger_type=trigger_type)
    scraper.setup_driver()

    try:
        tree = scraper.scrape_categories()
        saved = scraper.save_category_tree(tree)

        run.status = ScraperRun.Status.COMPLETED
        run.save(update_fields=["status"])

        return {
            "scraper_run_id": run.id,
            "store_code": store.code,
            "status": "COMPLETED",
            "parents_count": len(tree),
            "nodes_saved": saved,
        }

    except Exception as e:
        scraper.log_error(
            error_type="OTHER",
            error_message=str(e),
            url=store.base_url,
            stack_trace=traceback.format_exc(),
        )
        scraper.finish_run("FAILED")
        raise

    finally:
        scraper.teardown_driver()


@shared_task(bind=True, autoretry_for=(), retry_backoff=False)
def run_products_task(
    self,
    store_code: str,
    headless: bool = True,
    trigger_type: str = "API",
    limit_categories: Optional[int] = None,
) -> Dict[str, Any]:
    store = _get_store_or_raise(store_code)

    scraper = FalabellaScraper(store=store, headless=headless)
    run = scraper.start_run(trigger_type=trigger_type)
    scraper.setup_driver()

    try:
        qs = _leaf_categories_qs(store)
        if limit_categories:
            qs = qs[: int(limit_categories)]

        leafs = list(qs)
        if not leafs:
            scraper.finish_run("COMPLETED")
            return {
                "scraper_run_id": run.id,
                "store_code": store.code,
                "status": "COMPLETED",
                "categories_total": 0,
                "products_scraped": 0,
                "products_persisted": 0,
            }

        total_scraped = 0
        total_persisted = 0

        for cat in leafs:
            items = scraper.scrape_products(cat.url)
            total_scraped += len(items)

            persisted_here = 0
            for item in items:
                listing = scraper.persist_product_snapshot(category=cat, product_data=item)
                if listing:
                    persisted_here += 1

            total_persisted += persisted_here

            if hasattr(run, "products_scraped"):
                run.products_scraped = total_scraped
                run.save(update_fields=["products_scraped"])

        if hasattr(run, "products_count"):
            run.products_count = total_persisted
            run.save(update_fields=["products_count"])

        scraper.finish_run("COMPLETED")

        return {
            "scraper_run_id": run.id,
            "store_code": store.code,
            "status": "COMPLETED",
            "categories_total": len(leafs),
            "products_scraped": total_scraped,
            "products_persisted": total_persisted,
        }

    except Exception as e:
        scraper.log_error(
            error_type="OTHER",
            error_message=str(e),
            url=store.base_url,
            stack_trace=traceback.format_exc(),
        )
        scraper.finish_run("FAILED")
        raise

    finally:
        scraper.teardown_driver()