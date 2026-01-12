"""
Scraper para Falabella Colombia.

Navega categorías y extrae información de productos directamente
desde el HTML/JSON embebido en las páginas.
"""

import json
import logging
from typing import Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from products.models import Store, Category
from scrapers.models import ScraperError
from .scraper_base import BaseScraper

logger = logging.getLogger(__name__)


class FalabellaScraper(BaseScraper):
    """
    Scraper para Falabella Colombia.
    
    Extrae productos navegando por categorías y parseando el JSON
    embebido en __NEXT_DATA__.
    """
    
    BASE_URL = 'https://www.falabella.com.co'
    
    # Categorías con jerarquía: {nombre: (path, padre)}
    CATEGORIES = {
        'tecnologia': ('/tecnologia', None),
        'computacion': ('/tecnologia/computacion', 'tecnologia'),
        'celulares': ('/tecnologia/celulares-y-telefonia', 'tecnologia'),
        'electrodomesticos': ('/electrodomesticos', None),
    }
    
    def __init__(self, store: Store):
        """
        Inicializa el scraper de Falabella.
        
        Args:
            store: Instancia del modelo Store
        """
        super().__init__(store)
        
        # Headers específicos de Falabella
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'es-CO,es;q=0.9',
            'Referer': self.BASE_URL,
        })
    
    def scrape(self):
        """
        Método principal de scraping.
        
        SOLO CREA CATEGORÍAS - MODO DEBUG.
        """
        logger.info(f"Iniciando scraping de categorías de Falabella")
        
        try:
            # Primero obtener la home para ver categorías reales
            home_url = self.BASE_URL
            soup = self.fetch_page(home_url)
            
            if not soup:
                logger.error("No se pudo cargar la home de Falabella")
                return
            
            # Extraer links de categorías desde el menú
            category_links = self._extract_category_links(soup)
            
            logger.info(f"========== CATEGORÍAS EXTRAÍDAS ==========")
            for cat_name, cat_url in category_links.items():
                logger.info(f"  '{cat_name}' -> {cat_url}")
            logger.info(f"========== TOTAL: {len(category_links)} ==========")
            
            # NO CREAR NADA AÚN - SOLO MOSTRAR
            logger.info("No se creó nada - modo debug")
        
        except Exception as e:
            logger.error(f"Error general en scraping: {str(e)}")
            raise
    
    def _extract_category_links(self, soup: BeautifulSoup) -> Dict[str, str]:
        """
        Extrae links de categorías desde la home.
        
        Args:
            soup: BeautifulSoup de la home
            
        Returns:
            Dict {nombre_categoria: url}
        """
        categories = {}
        
        try:
            # Buscar links en el menú principal
            nav_links = soup.find_all('a', href=True)
            
            # Lista blanca de categorías válidas
            valid_categories = [
                'tecnologia', 'tecnología',
                'electro', 'electrohogar', 'electrodomesticos', 'electrodomésticos',
                'celular', 'celulares',
                'computador', 'computadores', 'computacion', 'computación'
            ]
            
            for link in nav_links:
                href = link.get('href', '')
                text = link.get_text(strip=True).lower()
                
                # Filtrar solo categorías válidas
                if not text or len(text) < 3:
                    continue
                
                # Verificar que sea una categoría válida
                is_valid = any(cat in text for cat in valid_categories)
                
                if not is_valid:
                    continue
                
                # Verificar que la URL sea de categoría (no filtros de marca)
                if 'f.product.brandName' in href:  # Esto es filtro de marca, NO categoría
                    continue
                
                full_url = urljoin(self.BASE_URL, href)
                categories[text] = full_url
                logger.debug(f"Categoría encontrada: {text} -> {full_url}")
            
            return categories
            
        except Exception as e:
            logger.error(f"Error extrayendo categorías: {str(e)}")
            return {}
    
    def scrape_category(self, url: str, category: Optional[Category] = None) -> List[Dict]:
        """
        Scrapea una página de categoría completa.
        
        Args:
            url: URL de la categoría
            category: Categoría de Django
            
        Returns:
            Lista de productos encontrados
        """
        products = []
        
        try:
            # Obtener página
            soup = self.fetch_page(url)
            if not soup:
                return products
            
            # Buscar el script con __NEXT_DATA__
            next_data = self._extract_next_data(soup)
            if not next_data:
                logger.error(f"No se encontró __NEXT_DATA__ en {url}")
                return products
            
            # Extraer productos del JSON
            product_list = self._parse_products_from_next_data(next_data)
            
            logger.info(f"Encontrados {len(product_list)} productos en JSON")
            
            # Procesar cada producto
            for product_data in product_list:
                try:
                    # Agregar categoría
                    product_data['category'] = category
                    
                    # Guardar producto y listing
                    listing = self.save_or_update_product_and_listing(product_data)
                    
                    if listing:
                        products.append(product_data)
                    
                except Exception as e:
                    logger.error(f"Error procesando producto: {str(e)}")
                    self._log_error(
                        error_type=ScraperError.ErrorType.VALIDATION,
                        error_message=f"Error guardando producto: {str(e)}",
                        url=product_data.get('url', url)
                    )
            
            return products
            
        except Exception as e:
            logger.error(f"Error scrapeando categoría {url}: {str(e)}")
            self._log_error(
                error_type=ScraperError.ErrorType.PARSE,
                error_message=str(e),
                url=url
            )
            return products
    
    def _extract_next_data(self, soup: BeautifulSoup) -> Optional[Dict]:
        """
        Extrae el JSON de __NEXT_DATA__ del HTML.
        
        Args:
            soup: BeautifulSoup de la página
            
        Returns:
            Dict con los datos o None
        """
        try:
            # Buscar por ID
            script = soup.find('script', {'id': '__NEXT_DATA__'})
            if not script:
                # Buscar por tipo
                script = soup.find('script', {'type': 'application/json'}, string=lambda t: '__NEXT_DATA__' in str(t) if t else False)
            
            if not script:
                # Buscar todos los scripts y ver si alguno tiene la estructura
                all_scripts = soup.find_all('script', {'type': 'application/json'})
                logger.debug(f"Encontrados {len(all_scripts)} scripts tipo application/json")
                
                for s in all_scripts:
                    if s.string and 'props' in s.string and 'pageProps' in s.string:
                        script = s
                        logger.info("Encontrado __NEXT_DATA__ sin ID estándar")
                        break
            
            if not script:
                logger.error("No se encontró ningún script con datos de Next.js")
                return None
            
            data = json.loads(script.string)
            return data
            
        except Exception as e:
            logger.error(f"Error parseando __NEXT_DATA__: {str(e)}")
            return None
    
    def _parse_products_from_next_data(self, next_data: Dict) -> List[Dict]:
        """
        Extrae lista de productos del __NEXT_DATA__.
        
        Args:
            next_data: Dict con __NEXT_DATA__
            
        Returns:
            Lista de dicts con información de productos
        """
        products = []
        
        try:
            # Navegar estructura de __NEXT_DATA__
            props = next_data.get('props', {})
            page_props = props.get('pageProps', {})
            
            # Buscar productos en diferentes ubicaciones posibles
            results = (
                page_props.get('results', []) or
                page_props.get('products', []) or
                page_props.get('items', [])
            )
            
            logger.debug(f"Encontrados {len(results)} items en __NEXT_DATA__")
            
            for item in results:
                try:
                    product_info = self._parse_product_item(item)
                    if product_info:
                        products.append(product_info)
                except Exception as e:
                    logger.error(f"Error parseando item: {str(e)}")
                    continue
            
            return products
            
        except Exception as e:
            logger.error(f"Error extrayendo productos de __NEXT_DATA__: {str(e)}")
            return products
    
    def _parse_product_item(self, item: Dict) -> Optional[Dict]:
        """
        Parsea un item individual de producto.
        
        Args:
            item: Dict con datos del producto
            
        Returns:
            Dict con información estructurada o None
        """
        try:
            # ID/SKU del producto
            store_sku = (
                item.get('productId') or
                item.get('id') or
                item.get('sku') or
                ''
            )
            
            if not store_sku:
                return None
            
            # Nombre
            name = (
                item.get('displayName') or
                item.get('name') or
                item.get('title') or
                'Sin nombre'
            )
            
            # URL
            url_path = item.get('url') or item.get('link') or ''
            if url_path and not url_path.startswith('http'):
                url = urljoin(self.BASE_URL, url_path)
            else:
                url = url_path or f"{self.BASE_URL}/product/{store_sku}"
            
            # Precios - puede ser dict o lista
            prices = item.get('prices', [])
            
            # Si es lista, tomar primer elemento
            if isinstance(prices, list):
                prices = prices[0] if len(prices) > 0 else {}
            
            # Precio actual - puede ser número o lista
            current_price_raw = (
                prices.get('price') or
                prices.get('originalPrice') or
                item.get('price') or
                0
            )
            
            # Si es lista, tomar primer elemento
            if isinstance(current_price_raw, list):
                current_price = current_price_raw[0] if len(current_price_raw) > 0 else 0
            else:
                current_price = current_price_raw
            
            # Precio original - puede ser número o lista
            original_price_raw = prices.get('originalPrice')
            
            if original_price_raw:
                if isinstance(original_price_raw, list):
                    original_price = original_price_raw[0] if len(original_price_raw) > 0 else None
                else:
                    original_price = original_price_raw
                
                # Solo usar si es mayor al actual
                if original_price and float(original_price) > float(current_price):
                    original_price = float(original_price)
                else:
                    original_price = None
            else:
                original_price = None
            
            # Imagen
            image_url = ''
            if 'media' in item:
                media = item['media']
                if isinstance(media, list) and len(media) > 0:
                    image_url = media[0].get('url', '')
                elif isinstance(media, dict):
                    image_url = media.get('url', '')
            elif 'image' in item:
                image_url = item['image']
            
            # Marca
            brand = item.get('brand', '')
            
            # Disponibilidad
            is_available = item.get('isAvailable', True)
            stock_status = item.get('stockStatus', '')
            
            return {
                'name': name,
                'store_sku': str(store_sku),
                'url': url,
                'current_price': float(current_price),
                'original_price': original_price,
                'image_url': image_url,
                'brand': brand,
                'is_available': is_available,
                'stock_status': stock_status,
            }
            
        except Exception as e:
            logger.error(f"Error parseando item de producto: {str(e)}", exc_info=True)
            return None
    
    def scrape_product_detail(self, url: str) -> Optional[Dict]:
        """
        Scrapea detalle de un producto individual.
        
        Args:
            url: URL del producto
            
        Returns:
            Dict con información del producto o None
        """
        try:
            soup = self.fetch_page(url)
            if not soup:
                return None
            
            next_data = self._extract_next_data(soup)
            if not next_data:
                return None
            
            # Extraer información de producto individual
            props = next_data.get('props', {})
            page_props = props.get('pageProps', {})
            product = page_props.get('product', {})
            
            if not product:
                return None
            
            return self._parse_product_item(product)
            
        except Exception as e:
            logger.error(f"Error scrapeando detalle de {url}: {str(e)}")
            self._log_error(
                error_type=ScraperError.ErrorType.PARSE,
                error_message=str(e),
                url=url
            )
            return None
    
    def search_products(self, query: str, max_results: int = 50) -> List[str]:
        """
        Busca productos por término.
        
        Args:
            query: Término de búsqueda
            max_results: Máximo de resultados
            
        Returns:
            Lista de URLs de productos
        """
        # TODO: Implementar búsqueda específica
        logger.warning("Búsqueda no implementada aún")
        return []