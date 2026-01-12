"""
Tests para scrapers app.
"""

from django.test import TestCase
from django.utils import timezone
from decimal import Decimal
from datetime import timedelta

from scrapers.models import ScraperRun, ScraperError
from products.models import Store, Product, ProductListing


class ScraperRunModelTest(TestCase):
    """Tests para el modelo ScraperRun."""
    
    def setUp(self):
        self.store = Store.objects.create(
            name='MercadoLibre',
            code='ML',
            base_url='https://www.mercadolibre.com.co',
            is_active=True,
            scraping_enabled=True
        )
    
    def test_scraper_run_creation(self):
        """Test creación de ejecución de scraping."""
        run = ScraperRun.objects.create(
            store=self.store,
            status=ScraperRun.Status.PENDING,
            trigger_type=ScraperRun.TriggerType.MANUAL
        )
        
        self.assertEqual(run.store, self.store)
        self.assertEqual(run.status, ScraperRun.Status.PENDING)
        self.assertEqual(run.trigger_type, ScraperRun.TriggerType.MANUAL)
        self.assertEqual(run.products_scraped, 0)
        self.assertEqual(run.errors_count, 0)
    
    def test_scraper_run_str(self):
        """Test __str__ de scraper run."""
        run = ScraperRun.objects.create(
            store=self.store,
            status=ScraperRun.Status.COMPLETED
        )
        
        self.assertIn('MercadoLibre', str(run))
        self.assertIn('COMPLETED', str(run))
    
    def test_mark_as_running(self):
        """Test marcar como ejecutando."""
        run = ScraperRun.objects.create(
            store=self.store,
            status=ScraperRun.Status.PENDING
        )
        
        run.mark_as_running()
        run.refresh_from_db()
        
        self.assertEqual(run.status, ScraperRun.Status.RUNNING)
        self.assertIsNotNone(run.started_at)
    
    def test_mark_as_completed(self):
        """Test marcar como completado."""
        run = ScraperRun.objects.create(
            store=self.store,
            status=ScraperRun.Status.RUNNING
        )
        
        run.mark_as_completed()
        run.refresh_from_db()
        
        self.assertEqual(run.status, ScraperRun.Status.COMPLETED)
        self.assertIsNotNone(run.finished_at)
        self.assertIsNotNone(run.execution_time)
    
    def test_mark_as_failed(self):
        """Test marcar como fallido."""
        run = ScraperRun.objects.create(
            store=self.store,
            status=ScraperRun.Status.RUNNING
        )
        
        error_msg = "Error de conexión"
        run.mark_as_failed(error_msg)
        run.refresh_from_db()
        
        self.assertEqual(run.status, ScraperRun.Status.FAILED)
        self.assertEqual(run.notes, error_msg)
        self.assertIsNotNone(run.finished_at)
    
    def test_get_success_rate_no_products(self):
        """Test tasa de éxito sin productos."""
        run = ScraperRun.objects.create(
            store=self.store,
            products_scraped=0,
            errors_count=0
        )
        
        self.assertEqual(run.get_success_rate(), 0)
    
    def test_get_success_rate_all_successful(self):
        """Test tasa de éxito 100%."""
        run = ScraperRun.objects.create(
            store=self.store,
            products_scraped=10,
            errors_count=0
        )
        
        self.assertEqual(run.get_success_rate(), 100.0)
    
    def test_get_success_rate_partial(self):
        """Test tasa de éxito parcial."""
        run = ScraperRun.objects.create(
            store=self.store,
            products_scraped=10,
            errors_count=2
        )
        
        # (10 - 2) / 10 * 100 = 80%
        self.assertEqual(run.get_success_rate(), 80.0)
    
    def test_execution_time_calculation(self):
        """Test cálculo de tiempo de ejecución."""
        run = ScraperRun.objects.create(
            store=self.store,
            status=ScraperRun.Status.RUNNING,
            started_at=timezone.now() - timedelta(minutes=5)
        )
        
        run.mark_as_completed()
        run.refresh_from_db()
        
        self.assertIsNotNone(run.execution_time)
        self.assertGreater(run.execution_time.total_seconds(), 0)


class ScraperErrorModelTest(TestCase):
    """Tests para el modelo ScraperError."""
    
    def setUp(self):
        self.store = Store.objects.create(
            name='MercadoLibre',
            code='ML',
            base_url='https://www.mercadolibre.com.co'
        )
        
        self.scraper_run = ScraperRun.objects.create(
            store=self.store,
            status=ScraperRun.Status.RUNNING
        )
        
        self.product = Product.objects.create(name='Laptop HP')
        self.listing = ProductListing.objects.create(
            product=self.product,
            store=self.store,
            store_sku='ML123',
            url='https://example.com'
        )
    
    def test_scraper_error_creation(self):
        """Test creación de error de scraping."""
        error = ScraperError.objects.create(
            scraper_run=self.scraper_run,
            listing=self.listing,
            error_type=ScraperError.ErrorType.CONNECTION,
            error_message='Timeout al conectar',
            url='https://example.com/producto'
        )
        
        self.assertEqual(error.scraper_run, self.scraper_run)
        self.assertEqual(error.listing, self.listing)
        self.assertEqual(error.error_type, ScraperError.ErrorType.CONNECTION)
        self.assertFalse(error.is_resolved)
    
    def test_scraper_error_str(self):
        """Test __str__ de scraper error."""
        error = ScraperError.objects.create(
            scraper_run=self.scraper_run,
            error_type=ScraperError.ErrorType.PARSE,
            error_message='Error parseando HTML'
        )
        
        self.assertIn('PARSE', str(error))
        self.assertIn('MercadoLibre', str(error))
    
    def test_scraper_error_without_listing(self):
        """Test error sin listing asociado."""
        error = ScraperError.objects.create(
            scraper_run=self.scraper_run,
            error_type=ScraperError.ErrorType.CONNECTION,
            error_message='Error general',
            listing=None
        )
        
        self.assertIsNone(error.listing)
    
    def test_error_ordering(self):
        """Test que los errores estén ordenados por fecha desc."""
        # Error antiguo
        old_error = ScraperError.objects.create(
            scraper_run=self.scraper_run,
            error_type=ScraperError.ErrorType.PARSE,
            error_message='Error 1',
            occurred_at=timezone.now() - timedelta(hours=2)
        )
        
        # Error reciente
        new_error = ScraperError.objects.create(
            scraper_run=self.scraper_run,
            error_type=ScraperError.ErrorType.CONNECTION,
            error_message='Error 2',
            occurred_at=timezone.now()
        )
        
        errors = list(ScraperError.objects.all())
        self.assertEqual(errors[0], new_error)  # Más reciente primero
        self.assertEqual(errors[1], old_error)


class ScraperRunIntegrationTest(TestCase):
    """Tests de integración para flujo completo de scraping."""
    
    def setUp(self):
        self.store = Store.objects.create(
            name='MercadoLibre',
            code='ML',
            base_url='https://www.mercadolibre.com.co',
            is_active=True,
            scraping_enabled=True
        )
        
        self.product = Product.objects.create(name='Laptop HP')
        self.listing = ProductListing.objects.create(
            product=self.product,
            store=self.store,
            store_sku='ML123',
            url='https://example.com'
        )
    
    def test_successful_scraping_run(self):
        """Test ejecución exitosa de scraping."""
        # Crear run
        run = ScraperRun.objects.create(
            store=self.store,
            status=ScraperRun.Status.PENDING,
            trigger_type=ScraperRun.TriggerType.MANUAL
        )
        
        # Iniciar
        run.mark_as_running()
        
        # Simular scraping exitoso
        run.products_scraped = 10
        run.products_created = 3
        run.products_updated = 7
        run.errors_count = 0
        run.save()
        
        # Completar
        run.mark_as_completed()
        run.refresh_from_db()
        
        self.assertEqual(run.status, ScraperRun.Status.COMPLETED)
        self.assertEqual(run.products_scraped, 10)
        self.assertEqual(run.get_success_rate(), 100.0)
    
    def test_scraping_run_with_errors(self):
        """Test ejecución con errores."""
        # Crear run
        run = ScraperRun.objects.create(
            store=self.store,
            status=ScraperRun.Status.RUNNING
        )
        
        # Simular scraping con errores
        run.products_scraped = 10
        run.products_created = 5
        run.products_updated = 3
        run.errors_count = 2
        run.save()
        
        # Registrar errores
        ScraperError.objects.create(
            scraper_run=run,
            listing=self.listing,
            error_type=ScraperError.ErrorType.CONNECTION,
            error_message='Timeout'
        )
        
        ScraperError.objects.create(
            scraper_run=run,
            error_type=ScraperError.ErrorType.PARSE,
            error_message='Invalid HTML'
        )
        
        # Verificar
        self.assertEqual(run.errors.count(), 2)
        self.assertEqual(run.get_success_rate(), 80.0)
    
    def test_failed_scraping_run(self):
        """Test ejecución fallida."""
        run = ScraperRun.objects.create(
            store=self.store,
            status=ScraperRun.Status.RUNNING
        )
        
        error_message = "Error crítico: no se pudo conectar"
        run.mark_as_failed(error_message)
        run.refresh_from_db()
        
        self.assertEqual(run.status, ScraperRun.Status.FAILED)
        self.assertEqual(run.notes, error_message)
    
    def test_multiple_runs_for_store(self):
        """Test múltiples ejecuciones para una tienda."""
        # Crear 3 runs
        run1 = ScraperRun.objects.create(
            store=self.store,
            status=ScraperRun.Status.COMPLETED,
            started_at=timezone.now() - timedelta(days=3)
        )
        
        run2 = ScraperRun.objects.create(
            store=self.store,
            status=ScraperRun.Status.COMPLETED,
            started_at=timezone.now() - timedelta(days=2)
        )
        
        run3 = ScraperRun.objects.create(
            store=self.store,
            status=ScraperRun.Status.RUNNING,
            started_at=timezone.now()
        )
        
        # Verificar
        runs = self.store.scraper_runs.all()
        self.assertEqual(runs.count(), 3)
        
        # Verificar orden (más reciente primero)
        self.assertEqual(runs[0], run3)
        self.assertEqual(runs[1], run2)
        self.assertEqual(runs[2], run1)


class ScraperMetricsTest(TestCase):
    """Tests para métricas de scraping."""
    
    def setUp(self):
        self.store = Store.objects.create(
            name='MercadoLibre',
            code='ML',
            base_url='https://www.mercadolibre.com.co'
        )
    
    def test_scraper_run_metrics_increment(self):
        """Test incremento de métricas."""
        run = ScraperRun.objects.create(
            store=self.store,
            status=ScraperRun.Status.RUNNING
        )
        
        # Simular scraping
        run.products_scraped += 1
        run.products_created += 1
        run.save()
        
        run.products_scraped += 1
        run.products_updated += 1
        run.save()
        
        run.refresh_from_db()
        
        self.assertEqual(run.products_scraped, 2)
        self.assertEqual(run.products_created, 1)
        self.assertEqual(run.products_updated, 1)
    
    def test_error_count_tracking(self):
        """Test seguimiento de conteo de errores."""
        run = ScraperRun.objects.create(
            store=self.store,
            status=ScraperRun.Status.RUNNING,
            products_scraped=5
        )
        
        # Agregar errores
        for i in range(3):
            ScraperError.objects.create(
                scraper_run=run,
                error_type=ScraperError.ErrorType.CONNECTION,
                error_message=f'Error {i}'
            )
            run.errors_count += 1
            run.save()
        
        run.refresh_from_db()
        
        self.assertEqual(run.errors_count, 3)
        self.assertEqual(run.errors.count(), 3)
        self.assertEqual(run.get_success_rate(), 40.0)  # (5-3)/5 * 100


class ScraperErrorResolutionTest(TestCase):
    """Tests para resolución de errores."""
    
    def setUp(self):
        self.store = Store.objects.create(
            name='Falabella',
            code='FA',
            base_url='https://www.falabella.com.co'
        )
        
        self.run = ScraperRun.objects.create(
            store=self.store,
            status=ScraperRun.Status.COMPLETED
        )
    
    def test_mark_error_as_resolved(self):
        """Test marcar error como resuelto."""
        error = ScraperError.objects.create(
            scraper_run=self.run,
            error_type=ScraperError.ErrorType.PARSE,
            error_message='Error parseando',
            is_resolved=False
        )
        
        # Marcar como resuelto
        error.is_resolved = True
        error.save()
        error.refresh_from_db()
        
        self.assertTrue(error.is_resolved)
    
    def test_filter_unresolved_errors(self):
        """Test filtrar errores no resueltos."""
        # Crear errores resueltos y no resueltos
        ScraperError.objects.create(
            scraper_run=self.run,
            error_type=ScraperError.ErrorType.CONNECTION,
            error_message='Error 1',
            is_resolved=True
        )
        
        ScraperError.objects.create(
            scraper_run=self.run,
            error_type=ScraperError.ErrorType.PARSE,
            error_message='Error 2',
            is_resolved=False
        )
        
        ScraperError.objects.create(
            scraper_run=self.run,
            error_type=ScraperError.ErrorType.TIMEOUT,
            error_message='Error 3',
            is_resolved=False
        )
        
        # Filtrar no resueltos
        unresolved = ScraperError.objects.filter(is_resolved=False)
        
        self.assertEqual(unresolved.count(), 2)