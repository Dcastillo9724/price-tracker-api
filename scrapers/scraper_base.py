"""
Clase base para scrapers.

IMPORTANTE: Ahora trabaja con Product y ProductListing separados.
"""

import time
import logging
import requests
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
from django.utils import timezone
from django.conf import settings

from products.models import Store, Category, Product, ProductListing, Price
from scrapers.models import ScraperRun, ScraperError

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """
    Clase base para todos los scrapers.
    
    Maneja:
    - HTTP requests con rate limiting
    - Tracking de ScraperRun
    - Guardado de productos/listings
    - Registro de errores
    """
    
    def __init__(self, store: Store):
        self.store = store
        self.session = requests.Session()
        
        # Headers base
        ua = UserAgent()
        self.session.headers.update({
            'User-Agent': ua.random,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'es-CO,es;q=0.9',
        })
        
        # Config
        self.delay = getattr(settings, 'SCRAPING_DELAY', 2)
        self.max_retries = getattr(settings, 'MAX_RETRIES', 3)
        self.timeout = getattr(settings, 'REQUEST_TIMEOUT', 30)
        
        # Tracking
        self.scraper_run = None
    
    def start_scraping(self, scraper_run: Optional[ScraperRun] = None):
        """
        Inicia el proceso de scraping.
        
        Args:
            scraper_run: ScraperRun existente o None para crear uno nuevo
        """
        # Crear o usar ScraperRun existente
        if scraper_run:
            self.scraper_run = scraper_run
        else:
            self.scraper_run = ScraperRun.objects.create(
                store=self.store,
                trigger_type=ScraperRun.TriggerType.MANUAL
            )
        
        self.scraper_run.mark_as_running()
        
        try:
            # Ejecutar scraping
            logger.info(f"Iniciando scraping de {self.store.name}")
            self.scrape()
            
            # Marcar como completado
            if self.scraper_run.errors_count > 0:
                self.scraper_run.mark_as_partial()
            else:
                self.scraper_run.mark_as_completed()
            
            logger.info(f"Scraping completado: {self.scraper_run.products_scraped} productos")
            
        except Exception as e:
            logger.error(f"Error en scraping: {str(e)}", exc_info=True)
            self.scraper_run.mark_as_failed(str(e))
            raise
    
    def fetch_page(self, url: str, retries: int = 0) -> Optional[BeautifulSoup]:
        """Hace request y retorna BeautifulSoup."""
        try:
            time.sleep(self.delay)
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            return BeautifulSoup(response.content, 'lxml')
        
        except requests.RequestException as e:
            logger.warning(f"Error fetching {url}: {str(e)}")
            
            if hasattr(self, 'scraper_run') and self.scraper_run:
                self._log_error(
                    error_type=ScraperError.ErrorType.CONNECTION,
                    error_message=str(e),
                    url=url
                )
            
            if retries < self.max_retries:
                logger.info(f"Retry {retries + 1}/{self.max_retries}")
                time.sleep(self.delay * 2)
                return self.fetch_page(url, retries + 1)
            
            return None
    
    def get_or_create_category(self, category_name: str, parent=None, url: str = None) -> Optional[Category]:
        """
        Crea o obtiene categoría.
        
        Args:
            category_name: Nombre de la categoría
            parent: Categoría padre (opcional)
            url: URL de la categoría (opcional)
        """
        if not category_name:
            return None
        
        try:
            # Buscar por nombre y padre
            category = Category.objects.filter(
                name=category_name,
                parent=parent
            ).first()
            
            if not category:
                # Crear nueva
                category = Category.objects.create(
                    name=category_name,
                    url=url or '',
                    parent=parent,
                    is_active=True
                )
                logger.info(f"Categoría creada: {category_name}")
            elif url and not category.url:
                # Actualizar URL si no existe
                category.url = url
                category.save(update_fields=['url'])
            
            return category
        except Exception as e:
            logger.error(f"Error creando categoría {category_name}: {str(e)}")
            return None
    
    def save_or_update_product_and_listing(self, product_data: Dict) -> Optional[ProductListing]:
        """
        Guarda o actualiza Product + ProductListing.
        
        product_data debe contener:
        - name: nombre del producto
        - store_sku: SKU en la tienda
        - url: URL del listing
        - current_price: precio actual
        - is_available: disponibilidad
        - (opcional) brand, model, description, category, image_url, etc.
        """
        try:
            # 1. Buscar o crear PRODUCT
            product_name = product_data.get('name', 'Sin nombre').strip()
            brand = product_data.get('brand', '').strip()
            model = product_data.get('model', '').strip()
            
            # Buscar producto existente por nombre similar
            product = Product.objects.filter(name=product_name).first()
            
            if not product:
                # Crear producto nuevo
                product = Product.objects.create(
                    name=product_name,
                    brand=brand,
                    model=model,
                    description=product_data.get('description', ''),
                    category=product_data.get('category')
                )
                logger.debug(f"Producto creado: {product_name}")
            
            # 2. Buscar o crear LISTING
            store_sku = product_data.get('store_sku', product_data.get('sku', ''))
            
            listing, created = ProductListing.objects.get_or_create(
                store=self.store,
                store_sku=store_sku,
                defaults={
                    'product': product,
                    'url': product_data.get('url', ''),
                    'image_url': product_data.get('image_url', ''),
                    'current_price': product_data.get('current_price', 0),
                    'original_price': product_data.get('original_price'),
                    'is_available': product_data.get('is_available', True),
                    'stock_status': product_data.get('stock_status', ''),
                    'last_scraped_at': timezone.now()
                }
            )
            
            if not created:
                # Actualizar listing existente
                listing.url = product_data.get('url', listing.url)
                listing.image_url = product_data.get('image_url', listing.image_url)
                listing.current_price = product_data.get('current_price', listing.current_price)
                listing.original_price = product_data.get('original_price', listing.original_price)
                listing.is_available = product_data.get('is_available', True)
                listing.stock_status = product_data.get('stock_status', listing.stock_status)
                listing.last_scraped_at = timezone.now()
                listing.save()
            
            # 3. Registrar PRECIO en historial
            Price.objects.create(
                listing=listing,
                price=product_data.get('current_price', 0),
                original_price=product_data.get('original_price'),
                is_available=product_data.get('is_available', True),
                recorded_at=timezone.now()
            )
            
            # 4. Actualizar métricas de scraper_run
            if self.scraper_run:
                self.scraper_run.products_scraped += 1
                if created:
                    self.scraper_run.products_created += 1
                else:
                    self.scraper_run.products_updated += 1
                self.scraper_run.save(update_fields=[
                    'products_scraped', 'products_created', 'products_updated'
                ])
            
            logger.debug(f"Guardado: {product_name}")
            return listing
        
        except Exception as e:
            logger.error(f"Error guardando producto: {str(e)}")
            self._log_error(
                error_type=ScraperError.ErrorType.VALIDATION,
                error_message=str(e),
                url=product_data.get('url', ''),
                stack_trace=str(e)
            )
            return None
    
    def _log_error(self, error_type: str, error_message: str, url: str = '', stack_trace: str = '', listing=None):
        """Registra un error."""
        if not self.scraper_run:
            return
        
        try:
            ScraperError.objects.create(
                scraper_run=self.scraper_run,
                listing=listing,
                error_type=error_type,
                error_message=error_message[:500],
                stack_trace=stack_trace[:2000],
                url=url
            )
            
            self.scraper_run.errors_count += 1
            self.scraper_run.save(update_fields=['errors_count'])
        
        except Exception as e:
            logger.error(f"Error logging error: {str(e)}")
    
    @abstractmethod
    def scrape(self) -> Dict:
        """
        Método principal de scraping.
        
        Debe retornar un dict con:
        {
            'status': 'success' | 'failed',
            'products_scraped': int,
            'products_created': int,
            'products_updated': int,
            'errors_count': int
        }
        """
        pass
    
    @abstractmethod
    def scrape_product_detail(self, url: str) -> Optional[Dict]:
        """
        Scrapea un producto individual.
        
        Debe retornar dict con datos del producto o None si falla.
        """
        pass
    
    @abstractmethod
    def search_products(self, query: str, max_results: int = 50) -> List[str]:
        """
        Busca productos y retorna lista de URLs.
        
        Args:
            query: término de búsqueda
            max_results: cantidad máxima de resultados
        
        Returns:
            Lista de URLs de productos
        """
        pass