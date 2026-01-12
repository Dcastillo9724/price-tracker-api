"""
Serializers para la API de productos y tracking de precios.

Este módulo define los serializers de DRF para transformar modelos
en representaciones JSON. Incluye serializers para listados, detalles
y creación/actualización de datos.

Estructura:
    - StoreSerializer: Serializer completo para tiendas
    - CategorySerializer: Serializer con ruta jerárquica completa
    - PriceSerializer: Serializer de historial de precios
    - ProductListing: Tres versiones (List, Detail, Create)
    - Product: Tres versiones (List, Detail, Create)
"""

from decimal import Decimal
from typing import Any, Dict, Optional

from rest_framework import serializers

from .models import Category, Price, Product, ProductListing, Store


class StoreSerializer(serializers.ModelSerializer):
    """
    Serializer completo para el modelo Store.
    
    Incluye conteo de listings activos para mostrar
    la cantidad de productos rastreados por tienda.
    
    Fields:
        - id: ID único de la tienda
        - name: Nombre de la tienda
        - code: Código de 2 caracteres
        - base_url: URL base del sitio
        - is_active: Si la tienda está activa
        - scraping_enabled: Si el scraping está habilitado
        - listings_count: Número de listings activos (computed)
        - created_at: Fecha de creación
    
    Examples:
        >>> serializer = StoreSerializer(store)
        >>> serializer.data
        {
            'id': 1,
            'name': 'MercadoLibre',
            'code': 'ML',
            'listings_count': 150,
            ...
        }
    """
    
    listings_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Store
        fields = [
            'id', 'name', 'code', 'base_url', 'is_active',
            'scraping_enabled', 'listings_count', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']
    
    def get_listings_count(self, obj: Store) -> int:
        """
        Retorna el número de listings activos de la tienda.
        
        Args:
            obj: Instancia de Store
        
        Returns:
            Número de listings activos
        """
        return obj.listings.filter(is_active=True).count()


class CategorySerializer(serializers.ModelSerializer):
    """
    Serializer completo para el modelo Category.

    Incluye la ruta completa de la jerarquía y el conteo de productos.
    La ruta muestra toda la cadena de categorías padre dentro de la tienda.

    Fields:
        - id: ID único de la categoría
        - store_name: Nombre de la tienda
        - store_code: Código de la tienda
        - name: Nombre de la categoría
        - parent: Categoría padre
        - url: URL de la categoría en la tienda
        - full_path: Ruta completa (ej: Electrónica > Computadores > Portátiles)
        - products_count: Cantidad de productos asociados
        - is_active: Indica si la categoría está activa
    """

    store_name = serializers.CharField(source='store.name', read_only=True)
    store_code = serializers.CharField(source='store.code', read_only=True)

    full_path = serializers.SerializerMethodField()
    products_count = serializers.IntegerField(
        source='products.count',
        read_only=True
    )

    class Meta:
        model = Category
        fields = [
            'id',
            'store',
            'store_name',
            'store_code',
            'name',
            'parent',
            'url',
            'full_path',
            'products_count',
            'is_active'
        ]
        read_only_fields = ['id', 'store_name', 'store_code', 'full_path', 'products_count']

    def get_full_path(self, obj: Category) -> str:
        """
        Retorna la ruta jerárquica completa de la categoría dentro de la tienda.

        Returns:
            Ruta completa separada por ' > '
            Ejemplo: 'Electrónica > Computadores > Portátiles'
        """
        path = [obj.name]
        parent = obj.parent

        while parent:
            path.append(parent.name)
            parent = parent.parent

        return ' > '.join(reversed(path))
    
    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validación a nivel de objeto.
        
        Args:
            attrs: Atributos de la categoría
        
        Returns:
            Atributos validados
        
        Raises:
            ValidationError: Si parent no pertenece a la misma tienda
        """
        parent = attrs.get('parent')
        store = attrs.get('store')
        
        # Si estamos actualizando, obtener store de la instancia si no viene en attrs
        if not store and self.instance:
            store = self.instance.store
        
        # Validar que parent pertenece a la misma tienda
        if parent and store and parent.store != store:
            raise serializers.ValidationError({
                'parent': 'La categoría padre debe pertenecer a la misma tienda'
            })
        
        return attrs


class CategoryTreeSerializer(serializers.ModelSerializer):
    """
    Serializer para mostrar categorías en estructura de árbol.
    
    Incluye las categorías hijas anidadas recursivamente.
    Útil para mostrar el catálogo completo de categorías.
    
    Examples:
        >>> serializer = CategoryTreeSerializer(root_category)
        >>> serializer.data
        {
            'id': 1,
            'name': 'Electrónica',
            'children': [
                {'id': 2, 'name': 'Laptops', 'children': []},
                ...
            ]
        }
    """
    
    children = serializers.SerializerMethodField()
    
    class Meta:
        model = Category
        fields = ['id', 'name', 'children', 'products_count']
    
    def get_children(self, obj: Category) -> list:
        """
        Retorna las categorías hijas serializadas.
        
        Args:
            obj: Instancia de Category
        
        Returns:
            Lista de categorías hijas serializadas
        """
        children = obj.children.filter(is_active=True)
        return CategoryTreeSerializer(children, many=True).data


class PriceSerializer(serializers.ModelSerializer):
    """
    Serializer para el modelo Price.
    
    Representa un punto en el historial de precios de un producto.
    Usado principalmente para mostrar evolución de precios.
    
    Fields:
        - id: ID único del registro
        - price: Precio registrado
        - original_price: Precio original antes de descuento
        - is_available: Si el producto estaba disponible
        - recorded_at: Fecha y hora del registro
    
    Examples:
        >>> serializer = PriceSerializer(price)
        >>> serializer.data
        {
            'id': 123,
            'price': '2500000.00',
            'original_price': '3000000.00',
            'is_available': True,
            'recorded_at': '2025-01-11T10:30:00Z'
        }
    """
    
    class Meta:
        model = Price
        fields = ['id', 'price', 'original_price', 'is_available', 'recorded_at']
        read_only_fields = ['id', 'recorded_at']


class PriceStatsSerializer(serializers.Serializer):
    """
    Serializer para estadísticas de precios.
    
    No está vinculado a un modelo, se usa para retornar
    estadísticas calculadas sobre rangos de precios.
    
    Fields:
        - min_price: Precio mínimo
        - max_price: Precio máximo
        - avg_price: Precio promedio
        - current_price: Precio actual
        - lowest_date: Fecha del precio más bajo
        - highest_date: Fecha del precio más alto
    """
    
    min_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    max_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    avg_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    current_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    lowest_date = serializers.DateTimeField()
    highest_date = serializers.DateTimeField()


class ListingListSerializer(serializers.ModelSerializer):
    """
    Serializer de ProductListing para listados.
    
    Versión ligera optimizada para mostrar múltiples listings.
    Incluye información esencial del producto, tienda y precio actual.
    
    Fields:
        - id: ID del listing
        - product_name: Nombre del producto
        - store_name: Nombre de la tienda
        - store_code: Código de la tienda
        - url: URL del producto en la tienda
        - current_price: Precio actual
        - original_price: Precio original (si aplica)
        - discount: Porcentaje de descuento
        - is_available: Disponibilidad actual
        - last_scraped_at: Última actualización
    
    Examples:
        >>> listings = ProductListing.objects.filter(is_active=True)
        >>> serializer = ListingListSerializer(listings, many=True)
        >>> serializer.data[0]['discount']
        16.67
    """
    
    product_name = serializers.CharField(source='product.name', read_only=True)
    store_name = serializers.CharField(source='store.name', read_only=True)
    store_code = serializers.CharField(source='store.code', read_only=True)
    current_price = serializers.SerializerMethodField()
    original_price = serializers.SerializerMethodField()
    discount = serializers.SerializerMethodField()
    
    class Meta:
        model = ProductListing
        fields = [
            'id', 'product_name', 'store_name', 'store_code',
            'url', 'current_price', 'original_price', 'discount',
            'is_available', 'last_scraped_at'
        ]
    
    def get_current_price(self, obj: ProductListing) -> Optional[str]:
        """
        Retorna el precio actual del listing.
        
        Args:
            obj: Instancia de ProductListing
        
        Returns:
            Precio como string o None si no hay precio
        """
        latest = obj.get_latest_price()
        return str(latest.price) if latest else None
    
    def get_original_price(self, obj: ProductListing) -> Optional[str]:
        """
        Retorna el precio original si existe descuento.
        
        Args:
            obj: Instancia de ProductListing
        
        Returns:
            Precio original como string o None
        """
        latest = obj.get_latest_price()
        return str(latest.original_price) if latest and latest.original_price else None
    
    def get_discount(self, obj: ProductListing) -> Decimal:
        """
        Retorna el porcentaje de descuento.
        
        Args:
            obj: Instancia de ProductListing
        
        Returns:
            Porcentaje de descuento (0 si no hay descuento)
        """
        return obj.get_discount_percentage()


class ListingDetailSerializer(serializers.ModelSerializer):
    """
    Serializer de ProductListing para vista detallada.
    
    Versión completa con toda la información del listing,
    producto, tienda y historial reciente de precios.
    
    Fields:
        - id: ID del listing
        - product: Información básica del producto
        - store: Información completa de la tienda
        - url: URL del producto
        - current_price: Precio actual
        - original_price: Precio original
        - discount: Porcentaje de descuento
        - is_available: Disponibilidad
        - stock_status: Estado del stock
        - recent_prices: Últimos 20 precios registrados
        - last_scraped_at: Última actualización
        - created_at: Fecha de creación
    """
    
    product = serializers.SerializerMethodField()
    store = StoreSerializer(read_only=True)
    current_price = serializers.SerializerMethodField()
    original_price = serializers.SerializerMethodField()
    discount = serializers.SerializerMethodField()
    recent_prices = serializers.SerializerMethodField()
    
    class Meta:
        model = ProductListing
        fields = [
            'id', 'product', 'store', 'url',
            'current_price', 'original_price', 'discount',
            'is_available', 'stock_status', 'recent_prices',
            'last_scraped_at', 'created_at'
        ]
    
    def get_product(self, obj: ProductListing) -> Dict[str, Any]:
        """
        Retorna información básica del producto.
        
        Args:
            obj: Instancia de ProductListing
        
        Returns:
            Diccionario con datos del producto
        """
        return {
            'id': obj.product.id,
            'name': obj.product.name,
            'brand': obj.product.brand,
            'category': obj.product.category.name if obj.product.category else None
        }
    
    def get_current_price(self, obj: ProductListing) -> Optional[str]:
        """Retorna el precio actual como string."""
        latest = obj.get_latest_price()
        return str(latest.price) if latest else None
    
    def get_original_price(self, obj: ProductListing) -> Optional[str]:
        """Retorna el precio original como string."""
        latest = obj.get_latest_price()
        return str(latest.original_price) if latest and latest.original_price else None
    
    def get_discount(self, obj: ProductListing) -> Decimal:
        """Retorna el porcentaje de descuento."""
        return obj.get_discount_percentage()
    
    def get_recent_prices(self, obj: ProductListing) -> list:
        """
        Retorna los últimos 20 precios registrados.
        
        Args:
            obj: Instancia de ProductListing
        
        Returns:
            Lista de precios serializados ordenados por fecha
        """
        prices = obj.price_history.all()[:20]
        return PriceSerializer(prices, many=True).data


class ListingCreateSerializer(serializers.ModelSerializer):
    """
    Serializer de ProductListing para crear/actualizar.
    
    Versión simplificada que solo acepta los campos editables.
    Usado en endpoints POST/PUT/PATCH.
    
    Fields:
        - product: ID del producto
        - store: ID de la tienda
        - url: URL del producto
        - is_available: Disponibilidad
        - stock_status: Estado del stock
        - is_active: Si está activo
    
    Validation:
        - Valida que la URL sea válida
    """
    
    class Meta:
        model = ProductListing
        fields = [
            'product', 'store', 'url',
            'is_available', 'stock_status', 'is_active'
        ]
    
    def validate_url(self, value: str) -> str:
        """
        Valida que la URL sea válida y no esté vacía.
        
        Args:
            value: URL a validar
        
        Returns:
            URL validada
        
        Raises:
            ValidationError: Si la URL es inválida
        """
        if not value or not value.strip():
            raise serializers.ValidationError("La URL no puede estar vacía")
        return value.strip()


class ProductListSerializer(serializers.ModelSerializer):
    """
    Serializer de Product para listados.
    
    Versión ligera optimizada para mostrar múltiples productos.
    Incluye mejor precio actual y conteo de tiendas.
    
    Fields:
        - id: ID del producto
        - name: Nombre del producto
        - brand: Marca
        - model: Modelo
        - category_name: Nombre de la categoría
        - best_price: Mejor precio disponible con tienda
        - listings_count: Número de tiendas donde está disponible
    
    Examples:
        >>> products = Product.objects.filter(is_active=True)
        >>> serializer = ProductListSerializer(products, many=True)
        >>> serializer.data[0]['best_price']
        {'price': '2450000.00', 'store': 'Falabella', 'url': 'https://...'}
    """
    
    category_name = serializers.CharField(
        source='category.name',
        read_only=True,
        default=None
    )
    best_price = serializers.SerializerMethodField()
    listings_count = serializers.IntegerField(
        source='listings.count',
        read_only=True
    )
    
    class Meta:
        model = Product
        fields = [
            'id', 'name', 'brand', 'model', 'category_name',
            'best_price', 'listings_count'
        ]
    
    def get_best_price(self, obj: Product) -> Optional[Dict[str, str]]:
        """
        Retorna el mejor precio disponible del producto.
        
        Args:
            obj: Instancia de Product
        
        Returns:
            Diccionario con price, store y url, o None si no hay precio
        """
        best = obj.get_best_price()
        if best:
            latest = best.get_latest_price()
            if latest:
                return {
                    'price': str(latest.price),
                    'store': best.store.name,
                    'url': best.url
                }
        return None


class ProductDetailSerializer(serializers.ModelSerializer):
    """
    Serializer de Product para vista detallada.
    
    Versión completa con toda la información del producto,
    todos sus listings activos, mejor precio y rango de precios.
    
    Fields:
        - id: ID del producto
        - name: Nombre del producto
        - brand: Marca
        - model: Modelo
        - description: Descripción detallada
        - category: Información completa de la categoría
        - listings: Lista de todos los listings activos
        - best_price: Mejor precio con información de tienda
        - price_range: Rango de precios (min, max, count)
        - is_active: Si el producto está activo
    """
    
    category = CategorySerializer(read_only=True)
    listings = serializers.SerializerMethodField()
    best_price = serializers.SerializerMethodField()
    price_range = serializers.SerializerMethodField()
    
    class Meta:
        model = Product
        fields = [
            'id', 'name', 'brand', 'model', 'description',
            'category', 'listings', 'best_price', 'price_range', 'is_active'
        ]
    
    def get_listings(self, obj: Product) -> list:
        """
        Retorna todos los listings activos del producto.
        
        Args:
            obj: Instancia de Product
        
        Returns:
            Lista de listings serializados
        """
        active = obj.listings.filter(is_active=True).select_related('store')
        return ListingListSerializer(active, many=True).data
    
    def get_best_price(self, obj: Product) -> Optional[Dict[str, str]]:
        """
        Retorna el mejor precio disponible con información completa.
        
        Args:
            obj: Instancia de Product
        
        Returns:
            Diccionario con price, store, store_code y url
        """
        best = obj.get_best_price()
        if best:
            latest = best.get_latest_price()
            if latest:
                return {
                    'price': str(latest.price),
                    'store': best.store.name,
                    'store_code': best.store.code,
                    'url': best.url
                }
        return None
    
    def get_price_range(self, obj: Product) -> Optional[Dict[str, Any]]:
        """
        Retorna el rango de precios del producto.
        
        Args:
            obj: Instancia de Product
        
        Returns:
            Diccionario con min, max y count, o None si no hay precios
        """
        price_range = obj.get_price_range()
        if price_range:
            return {
                'min': str(price_range['min']),
                'max': str(price_range['max']),
                'count': price_range['count']
            }
        return None


class ProductCreateSerializer(serializers.ModelSerializer):
    """
    Serializer de Product para crear/actualizar.
    
    Versión simplificada que solo acepta los campos editables.
    Incluye validación personalizada de campos.
    
    Fields:
        - name: Nombre del producto (mínimo 3 caracteres)
        - brand: Marca (opcional)
        - model: Modelo (opcional)
        - description: Descripción (opcional)
        - category: ID de la categoría
        - is_active: Si está activo
    
    Validation:
        - Nombre: mínimo 3 caracteres, se hace trim
        - Brand: se hace trim si existe
        - Model: se hace trim si existe
    """
    
    class Meta:
        model = Product
        fields = ['name', 'brand', 'model', 'description', 'category', 'is_active']
    
    def validate_name(self, value: str) -> str:
        """
        Valida que el nombre tenga al menos 3 caracteres.
        
        Args:
            value: Nombre a validar
        
        Returns:
            Nombre validado y limpio
        
        Raises:
            ValidationError: Si el nombre es muy corto
        """
        value = value.strip()
        if len(value) < 3:
            raise serializers.ValidationError(
                "El nombre debe tener al menos 3 caracteres"
            )
        return value
    
    def validate_brand(self, value: str) -> str:
        """Limpia espacios en blanco de la marca."""
        return value.strip() if value else value
    
    def validate_model(self, value: str) -> str:
        """Limpia espacios en blanco del modelo."""
        return value.strip() if value else value
    
    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validación a nivel de objeto.
        
        Args:
            attrs: Atributos del producto
        
        Returns:
            Atributos validados
        
        Raises:
            ValidationError: Si la categoría está inactiva
        """
        category = attrs.get('category')
        if category and not category.is_active:
            raise serializers.ValidationError({
                'category': 'No se puede asignar una categoría inactiva'
            })
        return attrs