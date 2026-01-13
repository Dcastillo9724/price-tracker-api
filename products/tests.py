"""
Tests para la app products.

Enfoque:
- Tests unitarios de modelos (comportamiento y reglas clave).
- Tests de integración livianos (flujo: producto -> listing -> prices).
- Assertions específicas (IntegrityError / ValidationError) en vez de Exception genérico.
- Evitar flakiness: usar timestamps controlados con timezone.now() y orderings explícitos.

Nota:
- Si usas mis cambios de models.py (constraints + clean), algunos tests se vuelven más estrictos
  (por ejemplo, original_price < price debe fallar).
"""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from products.models import Category, Price, Product, ProductListing, Store


class StoreModelTest(TestCase):
    """Tests para Store."""

    def setUp(self) -> None:
        self.store = Store.objects.create(
            name="MercadoLibre",
            code="ML",
            base_url="https://www.mercadolibre.com.co",
            is_active=True,
            scraping_enabled=True,
        )

    def test_store_creation(self) -> None:
        self.assertEqual(self.store.name, "MercadoLibre")
        self.assertEqual(self.store.code, "ML")
        self.assertTrue(self.store.is_active)
        self.assertTrue(self.store.scraping_enabled)

    def test_store_str(self) -> None:
        self.assertEqual(str(self.store), "MercadoLibre (ML)")

    def test_store_unique_code(self) -> None:
        with self.assertRaises(IntegrityError):
            Store.objects.create(
                name="Otra tienda",
                code="ML",  # duplicado
                base_url="https://example.com",
            )


class CategoryModelTest(TestCase):
    """Tests para Category (jerarquía + reglas)."""

    def setUp(self) -> None:
        self.store = Store.objects.create(
            name="MercadoLibre",
            code="ML",
            base_url="https://www.mercadolibre.com.co",
        )
        self.other_store = Store.objects.create(
            name="Falabella",
            code="FA",
            base_url="https://www.falabella.com.co",
        )

        self.parent = Category.objects.create(
            name="Electrónica",
            store=self.store,
        )
        self.child = Category.objects.create(
            name="Laptops",
            parent=self.parent,
            store=self.store,
        )

    def test_category_creation(self) -> None:
        self.assertEqual(self.parent.name, "Electrónica")
        self.assertIsNone(self.parent.parent)
        self.assertEqual(self.parent.store, self.store)

    def test_category_hierarchy(self) -> None:
        self.assertEqual(self.child.parent, self.parent)
        self.assertEqual(self.child.store, self.store)

    def test_category_get_full_path(self) -> None:
        self.assertEqual(self.child.get_full_path(), "Electrónica > Laptops")

    def test_category_str_contains_store_code(self) -> None:
        self.assertIn("ML", str(self.child))
        self.assertIn("Electrónica", str(self.child))
        self.assertIn("Laptops", str(self.child))

        self.assertIn("ML", str(self.parent))
        self.assertIn("Electrónica", str(self.parent))

    def test_category_parent_must_be_same_store(self) -> None:
        """
        Si tu model.clean valida coherencia de tienda, esto debe fallar.

        Ojo: clean() no corre automáticamente en save().
        Para validar regla de dominio, usamos full_clean().
        """
        invalid = Category(
            name="Gaming",
            store=self.other_store,
            parent=self.parent,  # parent pertenece a otra tienda
        )
        with self.assertRaises(ValidationError):
            invalid.full_clean()


class ProductModelTest(TestCase):
    """Tests para Product: best_price / range."""

    def setUp(self) -> None:
        self.ml = Store.objects.create(
            name="MercadoLibre",
            code="ML",
            base_url="https://www.mercadolibre.com.co",
        )
        self.fa = Store.objects.create(
            name="Falabella",
            code="FA",
            base_url="https://www.falabella.com.co",
        )
        self.category = Category.objects.create(name="Laptops", store=self.ml)
        self.product = Product.objects.create(
            name="Laptop HP Victus 15",
            brand="HP",
            model="Victus 15",
            description="Laptop gamer",
            category=self.category,
        )

    def test_product_creation(self) -> None:
        self.assertEqual(self.product.name, "Laptop HP Victus 15")
        self.assertEqual(self.product.brand, "HP")
        self.assertEqual(self.product.category, self.category)

    def test_product_str(self) -> None:
        self.assertEqual(str(self.product), "Laptop HP Victus 15")

    def test_get_best_price_no_listings(self) -> None:
        self.assertIsNone(self.product.get_best_price())

    def test_get_best_price_with_listings(self) -> None:
        listing1 = ProductListing.objects.create(
            product=self.product,
            store=self.ml,
            url="https://example.com/1",
        )
        Price.objects.create(listing=listing1, price=Decimal("2500000"), is_available=True)

        listing2 = ProductListing.objects.create(
            product=self.product,
            store=self.fa,
            url="https://example.com/2",
        )
        Price.objects.create(listing=listing2, price=Decimal("2450000"), is_available=True)

        best = self.product.get_best_price()
        self.assertEqual(best, listing2)

    def test_get_best_price_ignores_unavailable_prices(self) -> None:
        """
        Si el último precio del listing está marcado como no disponible,
        no debe contarse como candidato.
        """
        listing1 = ProductListing.objects.create(
            product=self.product,
            store=self.ml,
            url="https://example.com/1",
        )
        Price.objects.create(listing=listing1, price=Decimal("2000000"), is_available=False)

        best = self.product.get_best_price()
        self.assertIsNone(best)

    def test_get_price_range(self) -> None:
        listing1 = ProductListing.objects.create(
            product=self.product,
            store=self.ml,
            url="https://example.com/1",
        )
        Price.objects.create(listing=listing1, price=Decimal("2500000"), is_available=True)

        listing2 = ProductListing.objects.create(
            product=self.product,
            store=self.fa,
            url="https://example.com/2",
        )
        Price.objects.create(listing=listing2, price=Decimal("2450000"), is_available=True)

        price_range = self.product.get_price_range()
        self.assertIsNotNone(price_range)
        assert price_range is not None

        self.assertEqual(price_range["min"], Decimal("2450000"))
        self.assertEqual(price_range["max"], Decimal("2500000"))
        self.assertEqual(int(price_range["count"]), 2)


class ProductListingModelTest(TestCase):
    """Tests para ProductListing: latest_price / descuento."""

    def setUp(self) -> None:
        self.store = Store.objects.create(
            name="MercadoLibre",
            code="ML",
            base_url="https://www.mercadolibre.com.co",
        )
        self.product = Product.objects.create(name="Laptop HP Victus 15", brand="HP")
        self.listing = ProductListing.objects.create(
            product=self.product,
            store=self.store,
            url="https://www.mercadolibre.com.co/producto",
            is_available=True,
        )

    def test_listing_creation(self) -> None:
        self.assertEqual(self.listing.product, self.product)
        self.assertEqual(self.listing.store, self.store)

    def test_get_latest_price_no_prices(self) -> None:
        self.assertIsNone(self.listing.get_latest_price())

    def test_get_latest_price_with_prices(self) -> None:
        old = Price.objects.create(
            listing=self.listing,
            price=Decimal("2600000"),
            recorded_at=timezone.now() - timezone.timedelta(days=2),
        )
        recent = Price.objects.create(
            listing=self.listing,
            price=Decimal("2500000"),
            recorded_at=timezone.now(),
        )

        latest = self.listing.get_latest_price()
        self.assertEqual(latest, recent)
        self.assertNotEqual(latest, old)

    def test_get_discount_percentage_no_original(self) -> None:
        Price.objects.create(listing=self.listing, price=Decimal("2500000"))
        self.assertEqual(self.listing.get_discount_percentage(), Decimal("0"))

    def test_get_discount_percentage_with_discount(self) -> None:
        Price.objects.create(
            listing=self.listing,
            price=Decimal("2500000"),
            original_price=Decimal("3000000"),
        )
        self.assertEqual(self.listing.get_discount_percentage(), Decimal("16.67"))


class PriceModelTest(TestCase):
    """Tests para Price: ordering, str y reglas de descuento."""

    def setUp(self) -> None:
        self.store = Store.objects.create(
            name="MercadoLibre",
            code="ML",
            base_url="https://www.mercadolibre.com.co",
        )
        self.product = Product.objects.create(name="Laptop HP")
        self.listing = ProductListing.objects.create(
            product=self.product,
            store=self.store,
            url="https://example.com",
        )

    def test_price_creation(self) -> None:
        price = Price.objects.create(
            listing=self.listing,
            price=Decimal("2500000"),
            original_price=Decimal("3000000"),
            is_available=True,
        )
        self.assertEqual(price.listing, self.listing)
        self.assertEqual(price.price, Decimal("2500000"))
        self.assertTrue(price.is_available)

    def test_price_ordering_desc(self) -> None:
        old_price = Price.objects.create(
            listing=self.listing,
            price=Decimal("2600000"),
            recorded_at=timezone.now() - timezone.timedelta(days=2),
        )
        new_price = Price.objects.create(
            listing=self.listing,
            price=Decimal("2500000"),
            recorded_at=timezone.now(),
        )

        prices = list(Price.objects.all())
        self.assertEqual(prices[0], new_price)
        self.assertEqual(prices[1], old_price)

    def test_price_str(self) -> None:
        price = Price.objects.create(listing=self.listing, price=Decimal("2500000"))
        s = str(price)
        self.assertIn("Laptop HP", s)
        self.assertIn("2500000", s)

    def test_price_has_discount_property(self) -> None:
        price = Price.objects.create(
            listing=self.listing,
            price=Decimal("2500000"),
            original_price=Decimal("3000000"),
        )
        self.assertTrue(price.has_discount)
        self.assertEqual(price.discount_amount, Decimal("500000"))

    def test_price_invalid_original_price_less_than_price(self) -> None:
        """
        Si el modelo tiene constraint/clean: original_price >= price.
        Usamos full_clean para validar regla de dominio.
        """
        p = Price(
            listing=self.listing,
            price=Decimal("3000000"),
            original_price=Decimal("2500000"),
        )
        with self.assertRaises(ValidationError):
            p.full_clean()


class ProductListingIntegrationTest(TestCase):
    """Tests de integración: flujo completo multi-store + historial."""

    def setUp(self) -> None:
        self.ml = Store.objects.create(
            name="MercadoLibre",
            code="ML",
            base_url="https://www.mercadolibre.com.co",
        )
        self.fa = Store.objects.create(
            name="Falabella",
            code="FA",
            base_url="https://www.falabella.com.co",
        )
        self.category = Category.objects.create(name="Laptops", store=self.ml)
        self.product = Product.objects.create(
            name="Laptop HP Victus 15",
            brand="HP",
            category=self.category,
        )

    def test_product_in_multiple_stores(self) -> None:
        ml_listing = ProductListing.objects.create(
            product=self.product,
            store=self.ml,
            url="https://ml.com/producto",
        )
        Price.objects.create(listing=ml_listing, price=Decimal("2500000"), is_available=True)

        fa_listing = ProductListing.objects.create(
            product=self.product,
            store=self.fa,
            url="https://fa.com/producto",
        )
        Price.objects.create(listing=fa_listing, price=Decimal("2450000"), is_available=True)

        self.assertEqual(self.product.listings.count(), 2)

        best = self.product.get_best_price()
        self.assertIsNotNone(best)
        assert best is not None
        self.assertEqual(best.store, self.fa)

    def test_price_history_tracking(self) -> None:
        listing = ProductListing.objects.create(
            product=self.product,
            store=self.ml,
            url="https://example.com",
        )

        Price.objects.create(
            listing=listing,
            price=Decimal("2600000"),
            recorded_at=timezone.now() - timezone.timedelta(days=4),
        )
        Price.objects.create(
            listing=listing,
            price=Decimal("2550000"),
            recorded_at=timezone.now() - timezone.timedelta(days=2),
        )
        Price.objects.create(
            listing=listing,
            price=Decimal("2500000"),
            recorded_at=timezone.now(),
        )

        history = listing.price_history.all()
        self.assertEqual(history.count(), 3)

        latest = listing.get_latest_price()
        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertEqual(latest.price, Decimal("2500000"))