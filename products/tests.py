"""
Tests para products app.
"""

from django.test import TestCase
from django.utils import timezone
from decimal import Decimal
from products.models import Store, Category, Product, ProductListing, Price


class StoreModelTest(TestCase):
    """Tests para el modelo Store."""
    
    def setUp(self):
        self.store = Store.objects.create(
            name='MercadoLibre',
            code='ML',
            base_url='https://www.mercadolibre.com.co',
            is_active=True,
            scraping_enabled=True
        )
    
    def test_store_creation(self):
        """Test creación de tienda."""
        self.assertEqual(self.store.name, 'MercadoLibre')
        self.assertEqual(self.store.code, 'ML')
        self.assertTrue(self.store.is_active)
    
    def test_store_str(self):
        """Test __str__ de tienda."""
        self.assertEqual(str(self.store), 'MercadoLibre (ML)')
    
    def test_store_unique_code(self):
        """Test que el código sea único."""
        with self.assertRaises(Exception):
            Store.objects.create(
                name='Otra tienda',
                code='ML',  # Código duplicado
                base_url='https://example.com'
            )


class CategoryModelTest(TestCase):
    """Tests para el modelo Category."""
    
    def setUp(self):
        self.store = Store.objects.create(
            name='MercadoLibre',
            code='ML',
            base_url='https://www.mercadolibre.com.co'
        )

        self.parent = Category.objects.create(
            name='Electrónica',
            store=self.store
        )

        self.child = Category.objects.create(
            name='Laptops',
            parent=self.parent,
            store=self.store
        )

    
    def test_category_creation(self):
        """Test creación de categoría."""
        self.assertEqual(self.parent.name, 'Electrónica')
        self.assertIsNone(self.parent.parent)
    
    def test_category_hierarchy(self):
        """Test jerarquía de categorías."""
        self.assertEqual(self.child.parent, self.parent)
    
    def test_category_get_full_path(self):
        """Test obtener ruta completa."""
        self.assertEqual(self.child.get_full_path(), 'Electrónica > Laptops')
    
    def test_category_str(self):
        """Test __str__ de categoría."""
        self.assertEqual(str(self.child), 'Electrónica > Laptops')
        self.assertEqual(str(self.parent), 'Electrónica')


class ProductModelTest(TestCase):
    """Tests para el modelo Product."""
    
    def setUp(self):
        self.category = Category.objects.create(name='Laptops')
        self.product = Product.objects.create(
            name='Laptop HP Victus 15',
            brand='HP',
            model='Victus 15',
            description='Laptop gamer',
            category=self.category
        )
        
        # Crear tiendas
        self.ml = Store.objects.create(
            name='MercadoLibre',
            code='ML',
            base_url='https://www.mercadolibre.com.co'
        )
        self.fa = Store.objects.create(
            name='Falabella',
            code='FA',
            base_url='https://www.falabella.com.co'
        )
    
    def test_product_creation(self):
        """Test creación de producto."""
        self.assertEqual(self.product.name, 'Laptop HP Victus 15')
        self.assertEqual(self.product.brand, 'HP')
        self.assertEqual(self.product.category, self.category)
    
    def test_product_str(self):
        """Test __str__ de producto."""
        self.assertEqual(str(self.product), 'Laptop HP Victus 15')
    
    def test_get_best_price_no_listings(self):
        """Test obtener mejor precio sin listings."""
        best = self.product.get_best_price()
        self.assertIsNone(best)
    
    def test_get_best_price_with_listings(self):
        """Test obtener mejor precio con listings."""
        # Listing 1: ML $2,500,000
        listing1 = ProductListing.objects.create(
            product=self.product,
            store=self.ml,
            url='https://example.com/1'
        )
        Price.objects.create(
            listing=listing1,
            price=Decimal('2500000'),
            is_available=True
        )
        
        # Listing 2: FA $2,450,000 (mejor precio)
        listing2 = ProductListing.objects.create(
            product=self.product,
            store=self.fa,
            url='https://example.com/2'
        )
        Price.objects.create(
            listing=listing2,
            price=Decimal('2450000'),
            is_available=True
        )
        
        best = self.product.get_best_price()
        self.assertEqual(best, listing2)
    
    def test_get_price_range(self):
        """Test obtener rango de precios."""
        # Crear listings
        listing1 = ProductListing.objects.create(
            product=self.product,
            store=self.ml,
            url='https://example.com/1'
        )
        Price.objects.create(listing=listing1, price=Decimal('2500000'), is_available=True)
        
        listing2 = ProductListing.objects.create(
            product=self.product,
            store=self.fa,
            url='https://example.com/2'
        )
        Price.objects.create(listing=listing2, price=Decimal('2450000'), is_available=True)
        
        price_range = self.product.get_price_range()
        
        self.assertEqual(price_range['min'], Decimal('2450000'))
        self.assertEqual(price_range['max'], Decimal('2500000'))
        self.assertEqual(price_range['count'], 2)


class ProductListingModelTest(TestCase):
    """Tests para el modelo ProductListing."""
    
    def setUp(self):
        self.store = Store.objects.create(
            name='MercadoLibre',
            code='ML',
            base_url='https://www.mercadolibre.com.co'
        )
        self.product = Product.objects.create(
            name='Laptop HP Victus 15',
            brand='HP'
        )
        self.listing = ProductListing.objects.create(
            product=self.product,
            store=self.store,
            url='https://www.mercadolibre.com.co/producto',
            is_available=True
        )
    
    def test_listing_creation(self):
        """Test creación de listing."""
        self.assertEqual(self.listing.product, self.product)
        self.assertEqual(self.listing.store, self.store)
    
    def test_get_latest_price_no_prices(self):
        """Test obtener último precio sin precios."""
        latest = self.listing.get_latest_price()
        self.assertIsNone(latest)
    
    def test_get_latest_price_with_prices(self):
        """Test obtener último precio con precios."""
        # Precio antiguo
        Price.objects.create(
            listing=self.listing,
            price=Decimal('2600000'),
            recorded_at=timezone.now() - timezone.timedelta(days=2)
        )
        
        # Precio reciente
        recent_price = Price.objects.create(
            listing=self.listing,
            price=Decimal('2500000'),
            recorded_at=timezone.now()
        )
        
        latest = self.listing.get_latest_price()
        self.assertEqual(latest, recent_price)
    
    def test_get_discount_percentage_no_original(self):
        """Test descuento sin precio original."""
        Price.objects.create(
            listing=self.listing,
            price=Decimal('2500000')
        )
        
        discount = self.listing.get_discount_percentage()
        self.assertEqual(discount, 0)
    
    def test_get_discount_percentage_with_discount(self):
        """Test calcular porcentaje de descuento."""
        Price.objects.create(
            listing=self.listing,
            price=Decimal('2500000'),
            original_price=Decimal('3000000')
        )
        
        discount = self.listing.get_discount_percentage()
        self.assertEqual(discount, Decimal('16.67'))  # Comparar con Decimal


class PriceModelTest(TestCase):
    """Tests para el modelo Price."""
    
    def setUp(self):
        self.store = Store.objects.create(
            name='MercadoLibre',
            code='ML',
            base_url='https://www.mercadolibre.com.co'
        )
        self.product = Product.objects.create(name='Laptop HP')
        self.listing = ProductListing.objects.create(
            product=self.product,
            store=self.store,
            url='https://example.com'
        )
    
    def test_price_creation(self):
        """Test creación de precio."""
        price = Price.objects.create(
            listing=self.listing,
            price=Decimal('2500000'),
            original_price=Decimal('3000000'),
            is_available=True
        )
        
        self.assertEqual(price.listing, self.listing)
        self.assertEqual(price.price, Decimal('2500000'))
        self.assertTrue(price.is_available)
    
    def test_price_ordering(self):
        """Test que los precios estén ordenados por fecha desc."""
        # Crear precios en orden
        old_price = Price.objects.create(
            listing=self.listing,
            price=Decimal('2600000'),
            recorded_at=timezone.now() - timezone.timedelta(days=2)
        )
        
        new_price = Price.objects.create(
            listing=self.listing,
            price=Decimal('2500000'),
            recorded_at=timezone.now()
        )
        
        prices = list(Price.objects.all())
        self.assertEqual(prices[0], new_price)  # Más reciente primero
        self.assertEqual(prices[1], old_price)
    
    def test_price_str(self):
        """Test __str__ de precio."""
        price = Price.objects.create(
            listing=self.listing,
            price=Decimal('2500000')
        )
        
        self.assertIn('Laptop HP', str(price))
        self.assertIn('2500000', str(price))


class ProductListingIntegrationTest(TestCase):
    """Tests de integración para flujo completo."""
    
    def setUp(self):
        # Crear tiendas
        self.ml = Store.objects.create(
            name='MercadoLibre',
            code='ML',
            base_url='https://www.mercadolibre.com.co'
        )
        self.fa = Store.objects.create(
            name='Falabella',
            code='FA',
            base_url='https://www.falabella.com.co'
        )
        
        # Crear categoría
        self.category = Category.objects.create(name='Laptops')
        
        # Crear producto
        self.product = Product.objects.create(
            name='Laptop HP Victus 15',
            brand='HP',
            category=self.category
        )
    
    def test_product_in_multiple_stores(self):
        """Test producto en múltiples tiendas."""
        # Listing en ML
        ml_listing = ProductListing.objects.create(
            product=self.product,
            store=self.ml,
            url='https://ml.com/producto'
        )
        Price.objects.create(
            listing=ml_listing,
            price=Decimal('2500000'),
            is_available=True
        )
        
        # Listing en FA
        fa_listing = ProductListing.objects.create(
            product=self.product,
            store=self.fa,
            url='https://fa.com/producto'
        )
        Price.objects.create(
            listing=fa_listing,
            price=Decimal('2450000'),
            is_available=True
        )
        
        # Verificar que el producto tiene 2 listings
        self.assertEqual(self.product.listings.count(), 2)
        
        # Verificar mejor precio (Falabella)
        best = self.product.get_best_price()
        self.assertEqual(best.store, self.fa)
    
    def test_price_history_tracking(self):
        """Test seguimiento de historial de precios."""
        listing = ProductListing.objects.create(
            product=self.product,
            store=self.ml,
            url='https://example.com'
        )
        
        # Registrar 3 precios en diferentes momentos
        Price.objects.create(
            listing=listing,
            price=Decimal('2600000'),
            recorded_at=timezone.now() - timezone.timedelta(days=4)
        )
        Price.objects.create(
            listing=listing,
            price=Decimal('2550000'),
            recorded_at=timezone.now() - timezone.timedelta(days=2)
        )
        Price.objects.create(
            listing=listing,
            price=Decimal('2500000'),
            recorded_at=timezone.now()
        )
        
        # Verificar historial
        history = listing.price_history.all()
        self.assertEqual(history.count(), 3)
        
        # Verificar último precio
        latest = listing.get_latest_price()
        self.assertEqual(latest.price, Decimal('2500000'))