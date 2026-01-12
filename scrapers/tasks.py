"""
Tareas de Celery para scraping automático.

Define las tareas asíncronas que ejecutan los scrapers
de forma programada o manual.
"""

import logging
from celery import shared_task
from django.utils import timezone
from products.models import Store
from scrapers.models import ScraperRun
from scrapers.scraper_mercadolibre import MercadoLibreScraper
from scrapers.scraper_falabella import FalabellaScraper

logger = logging.getLogger(__name__)


# Mapeo de códigos de tienda a clases de scraper
SCRAPER_CLASSES = {
    'ML': MercadoLibreScraper,
    'FA': FalabellaScraper,
    # Agregar más scrapers aquí cuando estén implementados
    # 'EX': ExitoScraper,
    # 'AL': AlkostoScraper,
    # 'JU': JumboScraper,
}


@shared_task(bind=True, max_retries=3)
def scrape_store(self, store_id: int, trigger_type: str = 'SCHEDULED'):
    """
    Ejecuta el scraping para una tienda específica.
    
    Args:
        store_id: ID de la tienda a scrapear
        trigger_type: Tipo de ejecución ('MANUAL', 'SCHEDULED', 'API')
        
    Returns:
        Dict con resultados del scraping
    """
    try:
        # Obtener la tienda
        store = Store.objects.get(pk=store_id)
        
        # Verificar que el scraping esté habilitado
        if not store.is_active or not store.scraping_enabled:
            logger.warning(f"Scraping deshabilitado para {store.name}")
            return {
                'status': 'skipped',
                'message': f'Scraping deshabilitado para {store.name}'
            }
        
        # Obtener la clase de scraper apropiada
        scraper_class = SCRAPER_CLASSES.get(store.code)
        if not scraper_class:
            logger.error(f"No hay scraper implementado para {store.code}")
            return {
                'status': 'error',
                'message': f'No hay scraper implementado para {store.code}'
            }
        
        # Crear registro de ejecución
        scraper_run = ScraperRun.objects.create(
            store=store,
            trigger_type=trigger_type,
            task_id=self.request.id
        )
        
        logger.info(f"Iniciando scraping de {store.name} (Run ID: {scraper_run.id})")
        
        # Instanciar y ejecutar el scraper
        scraper = scraper_class(store)
        scraper.start_scraping(scraper_run)
        
        # Retornar resultados
        return {
            'status': 'success',
            'scraper_run_id': scraper_run.id,
            'store': store.name,
            'products_scraped': scraper_run.products_scraped,
            'products_created': scraper_run.products_created,
            'products_updated': scraper_run.products_updated,
            'errors_count': scraper_run.errors_count,
            'execution_time': scraper_run.execution_time.total_seconds() if scraper_run.execution_time else 0
        }
        
    except Store.DoesNotExist:
        logger.error(f"Tienda con ID {store_id} no encontrada")
        return {
            'status': 'error',
            'message': f'Tienda con ID {store_id} no encontrada'
        }
    
    except Exception as e:
        logger.error(f"Error en scraping de tienda {store_id}: {str(e)}", exc_info=True)
        
        # Reintentar en caso de error
        try:
            self.retry(countdown=60 * 5)  # Reintentar en 5 minutos
        except self.MaxRetriesExceededError:
            return {
                'status': 'failed',
                'message': str(e),
                'retries_exceeded': True
            }


@shared_task
def scrape_all_stores():
    """
    Ejecuta el scraping de todas las tiendas activas.
    
    Dispara una tarea por cada tienda de forma asíncrona.
    
    Returns:
        Dict con información de las tareas disparadas
    """
    active_stores = Store.objects.filter(
        is_active=True,
        scraping_enabled=True
    )
    
    logger.info(f"Iniciando scraping de {active_stores.count()} tiendas")
    
    tasks_started = []
    
    for store in active_stores:
        # Verificar que haya scraper implementado
        if store.code not in SCRAPER_CLASSES:
            logger.warning(f"No hay scraper para {store.name} ({store.code})")
            continue
        
        # Disparar tarea asíncrona para cada tienda
        task = scrape_store.delay(store.id, trigger_type='SCHEDULED')
        tasks_started.append({
            'store_id': store.id,
            'store_name': store.name,
            'task_id': task.id
        })
        
        logger.info(f"Tarea iniciada para {store.name}: {task.id}")
    
    return {
        'status': 'success',
        'tasks_started': len(tasks_started),
        'tasks': tasks_started
    }


@shared_task(bind=True)
def scrape_store_search(self, store_id: int, query: str, max_results: int = 50):
    """
    Busca y scrapea productos nuevos basándose en una búsqueda.
    
    Útil para agregar nuevos productos a la base de datos.
    
    Args:
        store_id: ID de la tienda
        query: Término de búsqueda
        max_results: Cantidad máxima de productos a scrapear
        
    Returns:
        Dict con resultados
    """
    try:
        store = Store.objects.get(pk=store_id)
        
        # Obtener scraper
        scraper_class = SCRAPER_CLASSES.get(store.code)
        if not scraper_class:
            return {
                'status': 'error',
                'message': f'No hay scraper implementado para {store.code}'
            }
        
        # Crear registro de ejecución
        scraper_run = ScraperRun.objects.create(
            store=store,
            trigger_type='API',
            task_id=self.request.id,
            notes=f'Búsqueda: {query}'
        )
        
        logger.info(f"Buscando productos en {store.name} para: {query}")
        
        # Ejecutar búsqueda
        scraper = scraper_class(store)
        scraper.scraper_run = scraper_run
        scraper.scraper_run.mark_as_running()
        
        scraper.scrape_search_results(query, max_results)
        
        # Finalizar
        if scraper.scraper_run.errors_count > 0:
            scraper.scraper_run.mark_as_partial()
        else:
            scraper.scraper_run.mark_as_completed()
        
        return {
            'status': 'success',
            'scraper_run_id': scraper_run.id,
            'store': store.name,
            'query': query,
            'products_found': scraper_run.products_scraped,
            'products_created': scraper_run.products_created,
            'errors': scraper_run.errors_count
        }
        
    except Exception as e:
        logger.error(f"Error en búsqueda de productos: {str(e)}", exc_info=True)
        return {
            'status': 'error',
            'message': str(e)
        }


@shared_task
def check_price_alerts():
    """
    Verifica las alertas de precio activas.
    
    Compara precios actuales con las alertas configuradas
    y las dispara si se cumplen las condiciones.
    
    Returns:
        Dict con alertas disparadas
    """
    from analytics.models import PriceAlert
    
    active_alerts = PriceAlert.objects.filter(
        is_active=True,
        triggered=False
    ).select_related('product')
    
    logger.info(f"Verificando {active_alerts.count()} alertas activas")
    
    triggered_count = 0
    
    for alert in active_alerts:
        try:
            # Verificar si debe dispararse
            if alert.check_and_trigger(alert.product.current_price):
                triggered_count += 1
                logger.info(f"Alerta disparada: {alert.product.name} - {alert.get_alert_type_display()}")
                
                # Aquí se podría enviar notificación por email, push, etc.
                # send_alert_notification(alert)
                
        except Exception as e:
            logger.error(f"Error verificando alerta {alert.id}: {str(e)}")
    
    return {
        'status': 'success',
        'alerts_checked': active_alerts.count(),
        'alerts_triggered': triggered_count
    }


@shared_task
def calculate_price_statistics():
    """
    Calcula estadísticas de precio para todos los productos.
    
    Genera registros de PriceStatistics para diferentes períodos.
    
    Returns:
        Dict con estadísticas calculadas
    """
    from analytics.models import PriceStatistics
    from products.models import Product
    from django.db.models import Min, Max, Avg, StdDev, Count
    from datetime import timedelta
    
    logger.info("Calculando estadísticas de precio")
    
    active_products = Product.objects.filter(is_active=True)
    stats_created = 0
    
    # Períodos a calcular
    periods = [
        ('7D', 7),
        ('30D', 30),
        ('90D', 90),
        ('365D', 365),
    ]
    
    for product in active_products:
        for period_code, days in periods:
            try:
                # Calcular fechas
                period_end = timezone.now()
                period_start = period_end - timedelta(days=days)
                
                # Obtener precios del período
                prices = product.prices.filter(
                    recorded_at__gte=period_start,
                    recorded_at__lte=period_end
                )
                
                if not prices.exists():
                    continue
                
                # Calcular métricas
                stats = prices.aggregate(
                    min_price=Min('price'),
                    max_price=Max('price'),
                    avg_price=Avg('price'),
                    volatility=StdDev('price'),
                    changes=Count('id')
                )
                
                # Contar días disponible vs sin stock
                days_available = prices.filter(is_available=True).count()
                days_out = prices.filter(is_available=False).count()
                
                # Crear o actualizar estadística
                PriceStatistics.objects.update_or_create(
                    product=product,
                    period=period_code,
                    period_start=period_start,
                    defaults={
                        'min_price': stats['min_price'],
                        'max_price': stats['max_price'],
                        'avg_price': stats['avg_price'],
                        'price_volatility': stats['volatility'],
                        'price_changes': stats['changes'],
                        'days_available': days_available,
                        'days_out_of_stock': days_out,
                        'period_end': period_end,
                        'calculated_at': timezone.now()
                    }
                )
                
                stats_created += 1
                
            except Exception as e:
                logger.error(f"Error calculando stats para {product.name}: {str(e)}")
    
    logger.info(f"Estadísticas calculadas: {stats_created}")
    
    return {
        'status': 'success',
        'statistics_created': stats_created,
        'products_processed': active_products.count()
    }


@shared_task
def cleanup_old_prices(days_to_keep: int = 90):
    """
    Limpia registros de precio antiguos para mantener la BD optimizada.
    
    Args:
        days_to_keep: Cantidad de días de historial a mantener
        
    Returns:
        Dict con cantidad de registros eliminados
    """
    from products.models import Price
    from datetime import timedelta
    
    cutoff_date = timezone.now() - timedelta(days=days_to_keep)
    
    # Contar registros a eliminar
    old_prices = Price.objects.filter(recorded_at__lt=cutoff_date)
    count = old_prices.count()
    
    # Eliminar
    old_prices.delete()
    
    logger.info(f"Eliminados {count} registros de precio antiguos")
    
    return {
        'status': 'success',
        'records_deleted': count,
        'cutoff_date': cutoff_date
    }
