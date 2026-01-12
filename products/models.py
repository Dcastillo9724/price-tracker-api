"""
Modelos para gestión de productos y seguimiento de precios.

Este módulo contiene los modelos principales del sistema de tracking de precios:
- Store: Tiendas donde se venden productos
- Category: Categorías jerárquicas de productos
- Product: Productos únicos (agnóstico de tienda)
- ProductListing: Producto específico en una tienda
- Price: Historial de precios por listing

Arquitectura:
    Un Product puede tener múltiples ProductListing (uno por tienda).
    Cada ProductListing tiene su propio historial de Price.
    Los precios SOLO se almacenan en Price, nunca en ProductListing.
"""

from decimal import Decimal
from typing import Dict, List, Optional

from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Store(models.Model):
    """
    Tienda donde se venden productos.
    
    Representa una plataforma de e-commerce (MercadoLibre, Falabella, etc.)
    donde se pueden listar productos para seguimiento de precios.
    
    Attributes:
        name: Nombre completo de la tienda
        code: Código único de 2 caracteres (ej: 'ML' para MercadoLibre)
        base_url: URL base del sitio web de la tienda
        is_active: Indica si la tienda está activa en el sistema
        scraping_enabled: Indica si se debe hacer scraping de esta tienda
        created_at: Fecha de creación del registro
        updated_at: Fecha de última actualización
    
    Examples:
        >>> store = Store.objects.create(
        ...     name='MercadoLibre',
        ...     code='ML',
        ...     base_url='https://www.mercadolibre.com.co'
        ... )
        >>> print(store)
        MercadoLibre (ML)
    """
    
    class StoreCode(models.TextChoices):
        """Códigos únicos de tiendas soportadas."""
        MERCADOLIBRE = 'ML', 'MercadoLibre'
        EXITO = 'EX', 'Éxito'
        FALABELLA = 'FA', 'Falabella'
        ALKOSTO = 'AL', 'Alkosto'
        JUMBO = 'JU', 'Jumbo'
    
    name = models.CharField(
        'nombre',
        max_length=100,
        unique=True,
        help_text='Nombre completo de la tienda'
    )
    code = models.CharField(
        'código',
        max_length=2,
        choices=StoreCode.choices,
        unique=True,
        help_text='Código único de 2 caracteres'
    )
    base_url = models.URLField(
        'URL base',
        help_text='URL base del sitio web'
    )
    is_active = models.BooleanField(
        'activa',
        default=True,
        help_text='Indica si la tienda está activa'
    )
    scraping_enabled = models.BooleanField(
        'scraping habilitado',
        default=True,
        help_text='Habilitar scraping automático'
    )
    created_at = models.DateTimeField('creado', auto_now_add=True)
    updated_at = models.DateTimeField('actualizado', auto_now=True)
    
    class Meta:
        db_table = 'store'
        verbose_name = 'tienda'
        verbose_name_plural = 'tiendas'
        ordering = ['name']
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['is_active', 'scraping_enabled']),
        ]
    
    def __str__(self) -> str:
        """Retorna representación en string: 'Nombre (CODE)'."""
        return f"{self.name} ({self.code})"
    
    def get_active_listings_count(self) -> int:
        """
        Retorna el número de listings activos en esta tienda.
        
        Returns:
            Número de ProductListing activos asociados a esta tienda
        """
        return self.listings.filter(is_active=True).count()


class Category(models.Model):
    """
    Categoría de productos con soporte para jerarquía y asociación a tienda.
    
    Las categorías SON específicas por tienda, ya que cada e-commerce
    maneja su propia taxonomía, URLs y estructura de navegación.
    
    Permite organizar productos en una estructura de árbol jerárquico
    por tienda.
    
    Ejemplo:
        Falabella:
            Electrónica > Computadores > Portátiles
        Éxito:
            Tecnología > Computadores > Portátiles
    
    Attributes:
        store: Tienda a la que pertenece la categoría
        name: Nombre de la categoría
        parent: Categoría padre (None si es raíz)
        url: URL de la categoría en la tienda
        description: Descripción opcional de la categoría
        is_active: Indica si la categoría está activa
        created_at: Fecha de creación
        updated_at: Fecha de actualización
    """
    
    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name='categories',
        verbose_name='tienda',
        help_text='Tienda a la que pertenece esta categoría'
    )
    name = models.CharField(
        'nombre',
        max_length=200,
        help_text='Nombre de la categoría'
    )
    url = models.URLField(
        'URL',
        max_length=1000,
        blank=True,
        help_text='URL de la categoría en la tienda'
    )
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='children',
        verbose_name='padre',
        help_text='Categoría padre dentro de la misma tienda'
    )
    description = models.TextField(
        'descripción',
        blank=True,
        help_text='Descripción de la categoría'
    )
    is_active = models.BooleanField(
        'activa',
        default=True,
        help_text='Indica si la categoría está activa'
    )
    created_at = models.DateTimeField('creado', auto_now_add=True)
    updated_at = models.DateTimeField('actualizado', auto_now=True)
    
    class Meta:
        db_table = 'category'
        verbose_name = 'categoría'
        verbose_name_plural = 'categorías'
        ordering = ['name']
        unique_together = [['store', 'name', 'parent']]
        indexes = [
            models.Index(fields=['store', 'parent']),
        ]
    
    def __str__(self) -> str:
        """Retorna representación en string con jerarquía y tienda."""
        if self.parent:
            return f"{self.store.code} | {self.parent.name} > {self.name}"
        return f"{self.store.code} | {self.name}"


class Product(models.Model):
    """
    Producto único, independiente de la tienda donde se vende.
    
    Representa un producto específico (ej: "Laptop HP Victus 15") que puede
    estar disponible en múltiples tiendas. Este modelo NO contiene precios
    ni información específica de tienda - eso va en ProductListing.
    
    Attributes:
        name: Nombre del producto
        brand: Marca del producto
        model: Modelo específico del producto
        description: Descripción detallada
        category: Categoría a la que pertenece
        is_active: Indica si el producto está activo
        created_at: Fecha de creación
        updated_at: Fecha de actualización
    
    Examples:
        >>> laptop = Product.objects.create(
        ...     name='Laptop HP Victus 15',
        ...     brand='HP',
        ...     model='Victus 15'
        ... )
        >>> best = laptop.get_best_price()
        >>> print(f"Mejor precio: ${best.get_latest_price().price}")
    """
    
    name = models.CharField(
        'nombre',
        max_length=500,
        help_text='Nombre completo del producto'
    )
    brand = models.CharField(
        'marca',
        max_length=100,
        blank=True,
        help_text='Marca del producto'
    )
    model = models.CharField(
        'modelo',
        max_length=200,
        blank=True,
        help_text='Modelo específico del producto'
    )
    description = models.TextField(
        'descripción',
        blank=True,
        help_text='Descripción detallada del producto'
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='products',
        verbose_name='categoría',
        help_text='Categoría del producto'
    )
    is_active = models.BooleanField(
        'activo',
        default=True,
        help_text='Indica si el producto está activo'
    )
    created_at = models.DateTimeField('creado', auto_now_add=True)
    updated_at = models.DateTimeField('actualizado', auto_now=True)
    
    class Meta:
        db_table = 'product'
        verbose_name = 'producto'
        verbose_name_plural = 'productos'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['name']),
            models.Index(fields=['brand']),
            models.Index(fields=['category', 'is_active']),
        ]
    
    def __str__(self) -> str:
        """Retorna el nombre del producto."""
        return self.name
    
    def get_best_price(self) -> Optional['ProductListing']:
        """
        Retorna el listing con el mejor precio actual.
        
        Compara los precios más recientes de todos los listings activos
        y retorna el que tiene el precio más bajo disponible.
        
        Returns:
            ProductListing con el mejor precio, o None si no hay precios
        
        Examples:
            >>> product = Product.objects.get(id=1)
            >>> best = product.get_best_price()
            >>> if best:
            ...     latest = best.get_latest_price()
            ...     print(f"${latest.price} en {best.store.name}")
        """
        best_listing = None
        best_price = None
        
        for listing in self.listings.filter(is_active=True).select_related('store'):
            latest_price = listing.get_latest_price()
            if latest_price and latest_price.is_available:
                if best_price is None or latest_price.price < best_price.price:
                    best_price = latest_price
                    best_listing = listing
        
        return best_listing
    
    def get_price_range(self) -> Optional[Dict[str, Decimal]]:
        """
        Retorna el rango de precios del producto entre todas las tiendas.
        
        Returns:
            Diccionario con 'min', 'max' y 'count' de precios disponibles,
            o None si no hay precios
        
        Examples:
            >>> product = Product.objects.get(id=1)
            >>> range_data = product.get_price_range()
            >>> if range_data:
            ...     print(f"Desde ${range_data['min']} hasta ${range_data['max']}")
        """
        prices = []
        
        for listing in self.listings.filter(is_active=True):
            latest = listing.get_latest_price()
            if latest and latest.is_available:
                prices.append(latest.price)
        
        if not prices:
            return None
        
        return {
            'min': min(prices),
            'max': max(prices),
            'count': len(prices)
        }
    
    def get_average_price(self) -> Optional[Decimal]:
        """
        Retorna el precio promedio del producto entre todas las tiendas.
        
        Returns:
            Precio promedio como Decimal, o None si no hay precios
        """
        price_range = self.get_price_range()
        if not price_range:
            return None
        
        total = sum(
            listing.get_latest_price().price
            for listing in self.listings.filter(is_active=True)
            if listing.get_latest_price() and listing.get_latest_price().is_available
        )
        return total / price_range['count']


class ProductListing(models.Model):
    """
    Producto en una tienda específica.
    
    Representa la oferta de un producto en una tienda particular.
    Contiene información específica de la tienda (URL)
    pero NO contiene precios - los precios van en el modelo Price.
    
    Attributes:
        product: Producto al que pertenece este listing
        store: Tienda donde se vende
        url: URL del producto en la tienda
        is_available: Disponibilidad actual del producto
        stock_status: Estado del stock (opcional)
        is_active: Indica si el listing está activo
        last_scraped_at: Última vez que se hizo scraping
        created_at: Fecha de creación
        updated_at: Fecha de actualización
    
    Examples:
        >>> listing = ProductListing.objects.create(
        ...     product=laptop,
        ...     store=mercadolibre,
        ...     url='https://...'
        ... )
        >>> latest_price = listing.get_latest_price()
        >>> discount = listing.get_discount_percentage()
    """
    
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='listings',
        verbose_name='producto',
        help_text='Producto al que pertenece'
    )
    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name='listings',
        verbose_name='tienda',
        help_text='Tienda donde se vende'
    )
    url = models.URLField(
        'URL',
        max_length=1000,
        help_text='URL del producto en la tienda'
    )
    is_available = models.BooleanField(
        'disponible',
        default=True,
        help_text='Disponibilidad actual'
    )
    stock_status = models.CharField(
        'stock',
        max_length=100,
        blank=True,
        help_text='Estado del stock (ej: "En stock", "Últimas unidades")'
    )
    is_active = models.BooleanField(
        'activo',
        default=True,
        help_text='Indica si el listing está activo'
    )
    last_scraped_at = models.DateTimeField(
        'último scraping',
        null=True,
        blank=True,
        help_text='Última vez que se hizo scraping'
    )
    created_at = models.DateTimeField('creado', auto_now_add=True)
    updated_at = models.DateTimeField('actualizado', auto_now=True)
    
    class Meta:
        db_table = 'product_listing'
        verbose_name = 'listado'
        verbose_name_plural = 'listados'
        ordering = ['-created_at']
        unique_together = [['product', 'store']]
        indexes = [
            models.Index(fields=['product', 'store']),
            models.Index(fields=['is_active', 'is_available']),
            models.Index(fields=['last_scraped_at']),
        ]
    
    def __str__(self) -> str:
        """Retorna representación con nombre, tienda y precio actual."""
        latest = self.get_latest_price()
        price_str = f"${latest.price}" if latest else "Sin precio"
        return f"{self.product.name} - {self.store.name} ({price_str})"
    
    def get_latest_price(self) -> Optional['Price']:
        """
        Retorna el precio más reciente de este listing.
        
        Returns:
            Objeto Price más reciente, o None si no hay precios registrados
        """
        return self.price_history.first()
    
    def get_discount_percentage(self) -> Decimal:
        """
        Calcula el porcentaje de descuento basado en precio original.
        
        Returns:
            Porcentaje de descuento (0 si no hay descuento)
            Ejemplo: 16.67 para un descuento del 16.67%
        """
        latest = self.get_latest_price()
        if not latest or not latest.original_price:
            return Decimal('0')
        
        if latest.original_price > latest.price:
            discount = ((latest.original_price - latest.price) / latest.original_price) * 100
            return round(discount, 2)
        return Decimal('0')
    
    def update_scrape_timestamp(self) -> None:
        """Actualiza el timestamp del último scraping a ahora."""
        self.last_scraped_at = timezone.now()
        self.save(update_fields=['last_scraped_at'])


class Price(models.Model):
    """
    Registro de precio en el historial de un listing.
    
    ÚNICA FUENTE DE PRECIOS EN EL SISTEMA. Cada vez que se hace scraping
    de un producto, se crea un nuevo registro Price con el precio actual.
    Esto permite tracking histórico y análisis de tendencias.
    
    Attributes:
        listing: ProductListing al que pertenece
        price: Precio actual del producto
        original_price: Precio original (antes de descuento)
        is_available: Si el producto estaba disponible
        recorded_at: Fecha y hora del registro
    
    Examples:
        >>> price = Price.objects.create(
        ...     listing=listing,
        ...     price=Decimal('2500000'),
        ...     original_price=Decimal('3000000')
        ... )
        >>> discount = ((price.original_price - price.price) / price.original_price) * 100
    """
    
    listing = models.ForeignKey(
        ProductListing,
        on_delete=models.CASCADE,
        related_name='price_history',
        verbose_name='listado',
        help_text='ProductListing al que pertenece'
    )
    price = models.DecimalField(
        'precio',
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text='Precio actual del producto'
    )
    original_price = models.DecimalField(
        'precio original',
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text='Precio original antes de descuento'
    )
    is_available = models.BooleanField(
        'disponible',
        default=True,
        help_text='Si el producto estaba disponible al momento del registro'
    )
    recorded_at = models.DateTimeField(
        'fecha',
        default=timezone.now,
        db_index=True,
        help_text='Fecha y hora del registro de precio'
    )
    
    class Meta:
        db_table = 'price'
        verbose_name = 'precio'
        verbose_name_plural = 'precios'
        ordering = ['-recorded_at']
        indexes = [
            models.Index(fields=['listing', '-recorded_at']),
            models.Index(fields=['is_available']),
        ]
    
    def __str__(self) -> str:
        """Retorna representación con producto, precio y fecha."""
        return (
            f"{self.listing.product.name} - "
            f"${self.price} ({self.recorded_at.strftime('%Y-%m-%d %H:%M')})"
        )
    
    @property
    def has_discount(self) -> bool:
        """Indica si este precio tiene descuento."""
        return (
            self.original_price is not None
            and self.original_price > self.price
        )
    
    @property
    def discount_amount(self) -> Optional[Decimal]:
        """Retorna el monto del descuento."""
        if self.has_discount:
            return self.original_price - self.price
        return None