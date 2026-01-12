"""
Test directo del scraper de MercadoLibre.
Prueba con una URL real.

Uso: 
    docker-compose exec web python test_scraper_direct.py
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from products.models import Store
from scrapers.scraper_mercadolibre import MercadoLibreScraper

print("=" * 70)
print("TEST DIRECTO - SCRAPER MERCADOLIBRE")
print("=" * 70)

# Obtener o crear tienda
store, created = Store.objects.get_or_create(
    code='ML',
    defaults={
        'name': 'MercadoLibre',
        'base_url': 'https://www.mercadolibre.com.co',
        'is_active': True,
        'scraping_enabled': True
    }
)

print(f"\n✓ Tienda: {store.name}")

# Crear scraper
scraper = MercadoLibreScraper(store)

# Test 1: Buscar productos
print("\n" + "-" * 70)
print("Test 1: Buscando productos...")
print("-" * 70)

try:
    urls = scraper.search_products("laptop", max_results=5)
    print(f"✓ Encontrados {len(urls)} productos")
    
    for i, url in enumerate(urls, 1):
        print(f"  {i}. {url}")
        
    if not urls:
        print("\n⚠️ No se encontraron URLs. Probando con URL directa...")
        
        # Test 2: Probar con URL directa conocida
        print("\n" + "-" * 70)
        print("Test 2: Scrapeando URL directa...")
        print("-" * 70)
        
        # URL de ejemplo - REEMPLAZAR con una URL real actual
        test_url = "https://www.mercadolibre.com.co/"
        
        print(f"Probando con: {test_url}")
        print("\nIntentando hacer request...")
        
        soup = scraper.fetch_page(test_url)
        
        if soup:
            print("✓ Request exitoso")
            print(f"  HTML recibido: {len(str(soup))} caracteres")
            
            # Ver si hay productos en la página
            links = soup.find_all('a', href=True)
            product_links = [l['href'] for l in links if 'articulo.mercadolibre.com.co' in l.get('href', '')]
            
            print(f"\n  Enlaces de productos encontrados: {len(product_links)}")
            
            if product_links:
                print("\n  Primeros 3 enlaces:")
                for link in product_links[:3]:
                    print(f"    - {link}")
        else:
            print("✗ No se pudo hacer el request")
            print("\nPosibles causas:")
            print("  1. MercadoLibre está bloqueando requests")
            print("  2. Problema de conectividad desde el contenedor")
            print("  3. User-Agent siendo rechazado")
            
            print("\nIntentando request básico con requests...")
            import requests
            try:
                response = requests.get(test_url, timeout=10)
                print(f"✓ Request básico exitoso: {response.status_code}")
            except Exception as e:
                print(f"✗ Request básico falló: {str(e)}")
    
    else:
        # Si encontró URLs, probar scrapear la primera
        print("\n" + "-" * 70)
        print("Test 3: Scrapeando primer producto encontrado...")
        print("-" * 70)
        
        test_url = urls[0]
        print(f"URL: {test_url}")
        
        product_data = scraper.scrape_product_detail(test_url)
        
        if product_data:
            print("\n✓ Producto scrapeado exitosamente:")
            print(f"  Nombre: {product_data.get('name', 'N/A')}")
            print(f"  SKU: {product_data.get('sku', 'N/A')}")
            print(f"  Precio: ${product_data.get('current_price', 0)}")
            print(f"  Disponible: {product_data.get('is_available', False)}")
            print(f"  URL Imagen: {product_data.get('image_url', 'N/A')[:50]}...")
        else:
            print("✗ No se pudo scrapear el producto")

except Exception as e:
    print(f"\n✗ Error: {str(e)}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 70)
print("FIN DEL TEST")
print("=" * 70)
