"""
Serializers para la app scrapers.

Maneja la serialización de ejecuciones de scraping y errores.
Incluye serializers para listados, detalles, creación y estadísticas.
"""

from typing import Any, Dict, Optional

from rest_framework import serializers

from products.models import Store
from .models import ScraperError, ScraperRun


class ScraperRunSerializer(serializers.ModelSerializer):
    """
    Serializer ligero para listado de ejecuciones de scraping.
    
    Incluye métricas básicas y tasa de éxito calculada.
    Optimizado para mostrar múltiples registros.
    
    Fields:
        - id: ID de la ejecución
        - store_name: Nombre de la tienda
        - status: Estado de la ejecución
        - trigger_type: Cómo se inició
        - started_at: Fecha de inicio
        - finished_at: Fecha de finalización
        - duration_seconds: Duración en segundos
        - products_scraped: Total procesados
        - products_updated: Productos actualizados
        - products_created: Productos creados
        - errors_count: Número de errores
        - success_rate: Porcentaje de éxito
    
    Examples:
        >>> runs = ScraperRun.objects.all()
        >>> serializer = ScraperRunSerializer(runs, many=True)
        >>> serializer.data[0]['success_rate']
        95.5
    """
    
    store_name = serializers.CharField(source='store.name', read_only=True)
    success_rate = serializers.SerializerMethodField()
    duration_seconds = serializers.SerializerMethodField()
    
    class Meta:
        model = ScraperRun
        fields = [
            'id',
            'store_name',
            'status',
            'trigger_type',
            'started_at',
            'finished_at',
            'duration_seconds',
            'products_scraped',
            'products_updated',
            'products_created',
            'errors_count',
            'success_rate'
        ]
    
    def get_success_rate(self, obj: ScraperRun) -> float:
        """
        Retorna el porcentaje de éxito.
        
        Args:
            obj: Instancia de ScraperRun
        
        Returns:
            Porcentaje de éxito (0-100)
        """
        return obj.get_success_rate()
    
    def get_duration_seconds(self, obj: ScraperRun) -> Optional[float]:
        """
        Retorna la duración en segundos.
        
        Args:
            obj: Instancia de ScraperRun
        
        Returns:
            Duración en segundos o None
        """
        return obj.get_duration_seconds()


class ScraperRunDetailSerializer(serializers.ModelSerializer):
    """
    Serializer completo para detalle de ejecución de scraping.
    
    Incluye información completa de la tienda, errores asociados
    y métricas calculadas. Usado en vistas de detalle.
    
    Fields:
        Todos los campos de ScraperRunSerializer más:
        - store: Información completa de la tienda
        - task_id: ID de la tarea de Celery
        - execution_time: Duración completa
        - notes: Notas adicionales
        - errors: Lista de errores recientes
    """
    
    store = serializers.SerializerMethodField()
    success_rate = serializers.SerializerMethodField()
    duration_seconds = serializers.SerializerMethodField()
    errors = serializers.SerializerMethodField()
    
    class Meta:
        model = ScraperRun
        fields = [
            'id',
            'store',
            'status',
            'trigger_type',
            'started_at',
            'finished_at',
            'duration_seconds',
            'products_scraped',
            'products_updated',
            'products_created',
            'errors_count',
            'success_rate',
            'task_id',
            'execution_time',
            'notes',
            'errors'
        ]
        read_only_fields = [
            'id',
            'started_at',
            'finished_at',
            'execution_time',
            'success_rate',
            'duration_seconds'
        ]
    
    def get_store(self, obj: ScraperRun) -> Dict[str, Any]:
        """
        Retorna información básica de la tienda.
        
        Args:
            obj: Instancia de ScraperRun
        
        Returns:
            Dict con id, name y code de la tienda
        """
        return {
            'id': obj.store.id,
            'name': obj.store.name,
            'code': obj.store.code
        }
    
    def get_success_rate(self, obj: ScraperRun) -> float:
        """Retorna el porcentaje de éxito."""
        return obj.get_success_rate()
    
    def get_duration_seconds(self, obj: ScraperRun) -> Optional[float]:
        """Retorna la duración en segundos."""
        return obj.get_duration_seconds()
    
    def get_errors(self, obj: ScraperRun) -> list:
        """
        Retorna los errores asociados (máximo 10 más recientes).
        
        Args:
            obj: Instancia de ScraperRun
        
        Returns:
            Lista de errores serializados
        """
        recent_errors = obj.errors.all()[:10]
        return ScraperErrorSerializer(recent_errors, many=True).data


class ScraperRunCreateSerializer(serializers.ModelSerializer):
    """
    Serializer para crear nuevas ejecuciones de scraping.
    
    Usado principalmente para disparar scraping manual desde la API.
    Valida que la tienda esté activa y tenga scraping habilitado.
    
    Fields:
        - store: ID de la tienda
        - trigger_type: Tipo de trigger
        - notes: Notas adicionales
    
    Validation:
        - La tienda debe estar activa
        - El scraping debe estar habilitado para la tienda
    """
    
    class Meta:
        model = ScraperRun
        fields = [
            'store',
            'trigger_type',
            'notes'
        ]
    
    def validate_store(self, value: Store) -> Store:
        """
        Valida que la tienda esté activa y tenga scraping habilitado.
        
        Args:
            value: Instancia de Store
        
        Returns:
            Store validado
        
        Raises:
            ValidationError: Si la tienda no cumple los requisitos
        """
        if not value.is_active:
            raise serializers.ValidationError("La tienda no está activa")
        if not value.scraping_enabled:
            raise serializers.ValidationError(
                "El scraping está deshabilitado para esta tienda"
            )
        return value
    
    def create(self, validated_data: Dict[str, Any]) -> ScraperRun:
        """
        Crea una nueva ejecución de scraping en estado PENDING.
        
        Args:
            validated_data: Datos validados
        
        Returns:
            Instancia de ScraperRun creada
        """
        validated_data['status'] = ScraperRun.Status.PENDING
        return super().create(validated_data)


class ScraperErrorSerializer(serializers.ModelSerializer):
    """
    Serializer para errores de scraping.
    
    Incluye información del producto/listing y la ejecución asociada.
    
    Fields:
        - id: ID del error
        - scraper_run_info: Información de la ejecución
        - listing_info: Información del listing (si aplica)
        - error_type: Tipo de error
        - error_message: Mensaje descriptivo
        - stack_trace: Stack trace completo
        - url: URL donde ocurrió
        - occurred_at: Fecha del error
        - is_resolved: Si está resuelto
        - resolution_notes: Notas de resolución
    """
    
    scraper_run_info = serializers.SerializerMethodField()
    listing_info = serializers.SerializerMethodField()
    
    class Meta:
        model = ScraperError
        fields = [
            'id',
            'scraper_run_info',
            'listing_info',
            'error_type',
            'error_message',
            'stack_trace',
            'url',
            'occurred_at',
            'is_resolved',
            'resolution_notes'
        ]
        read_only_fields = ['id', 'occurred_at']
    
    def get_scraper_run_info(self, obj: ScraperError) -> Dict[str, Any]:
        """
        Retorna información básica de la ejecución.
        
        Args:
            obj: Instancia de ScraperError
        
        Returns:
            Dict con información de la ejecución
        """
        return {
            'id': obj.scraper_run.id,
            'store_name': obj.scraper_run.store.name,
            'status': obj.scraper_run.status,
            'started_at': obj.scraper_run.started_at
        }
    
    def get_listing_info(self, obj: ScraperError) -> Optional[Dict[str, Any]]:
        """
        Retorna información del listing si existe.
        
        Args:
            obj: Instancia de ScraperError
        
        Returns:
            Dict con información del listing o None
        """
        if obj.listing:
            return {
                'id': obj.listing.id,
                'product_name': obj.listing.product.name,
                'store_sku': obj.listing.store_sku
            }
        return None


class ScraperErrorCreateSerializer(serializers.ModelSerializer):
    """
    Serializer para crear registros de errores.
    
    Usado internamente por los scrapers durante la ejecución.
    
    Fields:
        - scraper_run: ID de la ejecución
        - listing: ID del listing (opcional)
        - error_type: Tipo de error
        - error_message: Mensaje descriptivo
        - stack_trace: Stack trace
        - url: URL donde ocurrió
    
    Validation:
        - El listing debe pertenecer a la tienda del scraper_run
    """
    
    class Meta:
        model = ScraperError
        fields = [
            'scraper_run',
            'listing',
            'error_type',
            'error_message',
            'stack_trace',
            'url'
        ]
    
    def validate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validación de integridad de datos.
        
        Args:
            data: Datos a validar
        
        Returns:
            Datos validados
        
        Raises:
            ValidationError: Si el listing no coincide con la tienda
        """
        if data.get('listing') and data.get('scraper_run'):
            if data['listing'].store != data['scraper_run'].store:
                raise serializers.ValidationError(
                    "El listing no pertenece a la tienda del scraper run"
                )
        return data


class ScraperStatsSerializer(serializers.Serializer):
    """
    Serializer para estadísticas agregadas de scraping.
    
    No está vinculado a un modelo, se usa para respuestas calculadas
    con métricas globales del sistema de scraping.
    
    Fields:
        - total_runs: Total de ejecuciones
        - successful_runs: Ejecuciones exitosas
        - failed_runs: Ejecuciones fallidas
        - total_products_scraped: Total de productos procesados
        - total_errors: Total de errores
        - average_duration: Duración promedio en segundos
        - last_run: Fecha de última ejecución
        - store_stats: Estadísticas por tienda
    
    Examples:
        >>> stats = {
        ...     'total_runs': 100,
        ...     'successful_runs': 95,
        ...     'average_duration': 120.5
        ... }
        >>> serializer = ScraperStatsSerializer(stats)
    """
    
    total_runs = serializers.IntegerField()
    successful_runs = serializers.IntegerField()
    failed_runs = serializers.IntegerField()
    total_products_scraped = serializers.IntegerField()
    total_errors = serializers.IntegerField()
    average_duration = serializers.FloatField()
    last_run = serializers.DateTimeField(allow_null=True)
    store_stats = serializers.DictField(child=serializers.DictField())