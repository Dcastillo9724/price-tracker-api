"""
Tests para el scraper de Falabella.

Estos tests pueden ejecutarse con:
    python manage.py test scrapers.tests.test_falabella
"""

from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase
from products.models import Category, Store
from scrapers.falabella import FalabellaScraper
from scrapers.models import ScraperRun


class FalabellaScraperTestCase(TestCase):
    """Tests para el scraper de Falabella."""
    
    def setUp(self):
        """Configuración inicial de tests."""
        self.store = Store.objects.create(
            name='Falabella',
            code='FA',
            base_url='https://www.falabella.com.co',
            is_active=True,
            scraping_enabled=True
        )
        self.scraper = FalabellaScraper(store=self.store, headless=True)
    
    def test_scraper_initialization(self):
        """Test que el scraper se inicializa correctamente."""
        self.assertEqual(self.scraper.store, self.store)
        self.assertTrue(self.scraper.headless)
        self.assertIsNone(self.scraper.scraper_run)
    
    def test_start_run_creates_scraper_run(self):
        """Test que start_run crea un ScraperRun."""
        run = self.scraper.start_run(trigger_type='MANUAL')
        
        self.assertIsInstance(run, ScraperRun)
        self.assertEqual(run.store, self.store)
        self.assertEqual(run.trigger_type, 'MANUAL')
        self.assertEqual(run.status, ScraperRun.Status.RUNNING)
    
    def test_save_category_creates_new_category(self):
        """Test que save_category crea una categoría nueva."""
        # Crear run para que el scraper funcione
        self.scraper.start_run()
        
        category = self.scraper.save_category(
            name='Electrónica',
            url='https://www.falabella.com.co/falabella-co/category/cat1'
        )
        
        self.assertIsInstance(category, Category)
        self.assertEqual(category.name, 'Electrónica')
        self.assertEqual(category.store, self.store)
        self.assertIsNone(category.parent)
    
    def test_save_category_with_parent(self):
        """Test que save_category crea categoría con padre."""
        self.scraper.start_run()
        
        parent = self.scraper.save_category(name='Electrónica')
        child = self.scraper.save_category(
            name='Computadores',
            parent=parent
        )
        
        self.assertEqual(child.parent, parent)
        self.assertEqual(child.store, self.store)
    
    def test_update_metrics(self):
        """Test que update_metrics actualiza correctamente."""
        run = self.scraper.start_run()
        
        self.scraper.update_metrics(scraped=5, created=3, updated=2)
        run.refresh_from_db()
        
        self.assertEqual(run.products_scraped, 5)
        self.assertEqual(run.products_created, 3)
        self.assertEqual(run.products_updated, 2)
    
    def test_log_error_creates_error_record(self):
        """Test que log_error crea un registro de error."""
        run = self.scraper.start_run()
        
        self.scraper.log_error(
            error_type='PARSE',
            error_message='Error de prueba',
            url='https://example.com'
        )
        
        run.refresh_from_db()
        self.assertEqual(run.errors_count, 1)
        self.assertEqual(run.errors.count(), 1)
        
        error = run.errors.first()
        self.assertEqual(error.error_type, 'PARSE')
        self.assertEqual(error.error_message, 'Error de prueba')
    
    def test_finish_run_completed(self):
        """Test que finish_run marca como completado."""
        run = self.scraper.start_run()
        self.scraper.finish_run('COMPLETED')
        run.refresh_from_db()
        
        self.assertEqual(run.status, ScraperRun.Status.COMPLETED)
        self.assertIsNotNone(run.finished_at)
        self.assertIsNotNone(run.execution_time)
    
    def test_finish_run_failed(self):
        """Test que finish_run marca como fallido."""
        run = self.scraper.start_run()
        self.scraper.finish_run('FAILED')
        run.refresh_from_db()
        
        self.assertEqual(run.status, ScraperRun.Status.FAILED)
    
    @patch('scrapers.falabella.SeleniumConfig.create_driver')
    def test_setup_driver(self, mock_create_driver):
        """Test que setup_driver configura el driver."""
        mock_driver = Mock()
        mock_wait = Mock()
        mock_create_driver.return_value = (mock_driver, mock_wait)
        
        self.scraper.setup_driver()
        
        self.assertEqual(self.scraper.driver, mock_driver)
        self.assertEqual(self.scraper.wait, mock_wait)
        mock_create_driver.assert_called_once_with(headless=True)
    
    def test_teardown_driver(self):
        """Test que teardown_driver cierra el driver."""
        mock_driver = Mock()
        self.scraper.driver = mock_driver
        
        self.scraper.teardown_driver()
        
        mock_driver.quit.assert_called_once()


class FalabellaScraperIntegrationTest(TestCase):
    """Tests de integración para scraping completo (sin Selenium real)."""
    
    def setUp(self):
        """Configuración inicial."""
        self.store = Store.objects.create(
            name='Falabella',
            code='FA',
            base_url='https://www.falabella.com.co',
            is_active=True,
            scraping_enabled=True
        )
        self.scraper = FalabellaScraper(store=self.store, headless=True)
    
    def test_save_categories_hierarchy(self):
        """Test guardar jerarquía completa de categorías."""
        self.scraper.start_run()
        
        # Datos simulados
        categories_data = [
            {
                "name": "Tecnología",
                "children": [
                    {
                        "name": "Computadores",
                        "children": [
                            {"name": "Laptops", "url": "https://example.com/laptops"},
                            {"name": "Desktops", "url": "https://example.com/desktops"}
                        ]
                    },
                    {
                        "name": "Celulares",
                        "children": [
                            {"name": "Smartphones", "url": "https://example.com/smartphones"}
                        ]
                    }
                ]
            }
        ]
        
        # Guardar categorías
        self.scraper._save_categories_to_db(categories_data)
        
        # Verificar que se crearon
        self.assertEqual(Category.objects.count(), 6)  # 1 padre + 2 hijos + 3 nietos
        
        # Verificar jerarquía
        parent = Category.objects.get(name='Tecnología', parent=None)
        child = Category.objects.get(name='Computadores', parent=parent)
        grandchild = Category.objects.get(name='Laptops', parent=child)
        
        self.assertEqual(parent.store, self.store)
        self.assertEqual(grandchild.url, 'https://example.com/laptops')
