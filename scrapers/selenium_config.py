"""
Configuración de Selenium para scrapers.

Proporciona configuración estándar y helpers para trabajar con Selenium.
"""

import logging
import time
from typing import List

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager


logger = logging.getLogger(__name__)


class SeleniumConfig:
    """
    Configuración centralizada de Selenium.
    
    Proporciona métodos para crear y configurar WebDriver con
    opciones estándar reutilizables.
    
    Examples:
        >>> driver = SeleniumConfig.create_driver(headless=True)
        >>> driver.get('https://example.com')
    """
    
    @staticmethod
    def get_chrome_options(headless: bool = False):
        options = webdriver.ChromeOptions()
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        if headless:
            options.add_argument("--headless=new")
        return options

    
    @staticmethod
    def create_driver(
        headless: bool = False,
        wait_time: int = 20
    ) -> tuple[webdriver.Chrome, WebDriverWait]:
        """
        Crea y configura un WebDriver de Chrome.
        
        Args:
            headless: Si ejecutar en modo headless
            wait_time: Tiempo máximo de espera para WebDriverWait
        
        Returns:
            Tupla de (driver, wait)
        
        Examples:
            >>> driver, wait = SeleniumConfig.create_driver()
            >>> driver.get('https://example.com')
        """
        options = SeleniumConfig.get_chrome_options(headless=headless)
        
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        
        # Configurar script anti-detección
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                })
            """
        })
        
        wait = WebDriverWait(driver, wait_time)
        
        logger.info("WebDriver de Chrome creado exitosamente")
        return driver, wait


class SeleniumHelpers:
    """
    Helpers comunes para trabajar con Selenium.
    
    Métodos utilitarios para operaciones frecuentes como:
    - Remover overlays
    - Hover sobre elementos
    - Limpiar texto
    - Scroll
    """
    
    @staticmethod
    def remove_overlays(driver: webdriver.Chrome, selectors: List[str] = None) -> None:
        """
        Remueve overlays molestos de la página.
        
        Args:
            driver: WebDriver de Selenium
            selectors: Lista de selectores CSS a remover
        """
        time.sleep(2)
        
        default_selectors = [
            '.airship-html-prompt-shadow',
            '#onetrust-consent-sdk',
            '.modal-backdrop',
            '[class*="cookie"]',
            '[class*="popup"]',
            '[class*="overlay"]'
        ]
        
        if selectors:
            default_selectors.extend(selectors)
        
        for selector in default_selectors:
            try:
                driver.execute_script(f"""
                    document.querySelectorAll('{selector}')
                    .forEach(el => el.remove());
                """)
            except:
                pass
        
        logger.debug("Overlays removidos")
    
    @staticmethod
    def hover_element(driver: webdriver.Chrome, element: WebElement) -> None:
        """
        Simula hover sobre un elemento.
        
        Args:
            driver: WebDriver de Selenium
            element: Elemento sobre el cual hacer hover
        """
        driver.execute_script("""
            arguments[0].dispatchEvent(
                new MouseEvent('mouseover', { bubbles: true })
            );
        """, element)
    
    @staticmethod
    def click_element(driver: webdriver.Chrome, element: WebElement) -> None:
        """
        Hace click en un elemento usando JavaScript.
        
        Útil cuando el click normal no funciona por overlays.
        
        Args:
            driver: WebDriver de Selenium
            element: Elemento a clickear
        """
        driver.execute_script("arguments[0].click();", element)
    
    @staticmethod
    def clean_text(text: str) -> str:
        """
        Limpia texto extraído de HTML.
        
        Args:
            text: Texto a limpiar
        
        Returns:
            Texto limpio
        """
        return (
            text.replace("NUEVO", "")
            .replace("\n", " ")
            .replace("\t", " ")
            .strip()
        )
    
    @staticmethod
    def scroll_to_bottom(driver: webdriver.Chrome, pause_time: float = 1.0) -> None:
        """
        Hace scroll hasta el fondo de la página.
        
        Args:
            driver: WebDriver de Selenium
            pause_time: Tiempo de pausa entre scrolls
        """
        last_height = driver.execute_script("return document.body.scrollHeight")
        
        while True:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(pause_time)
            
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height
    
    @staticmethod
    def wait_for_page_load(driver: webdriver.Chrome, timeout: int = 30) -> bool:
        """
        Espera a que la página cargue completamente.
        
        Args:
            driver: WebDriver de Selenium
            timeout: Tiempo máximo de espera
        
        Returns:
            True si cargó, False si timeout
        """
        try:
            WebDriverWait(driver, timeout).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            return True
        except:
            return False
