import logging
import time
import traceback
from typing import Any, Dict, List, Optional

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import (
    StaleElementReferenceException,
    ElementClickInterceptedException,
    TimeoutException,
)

from .base import BaseScraper
from .selenium_config import SeleniumHelpers

logger = logging.getLogger(__name__)


class FalabellaScraper(BaseScraper):
    BASE_URL = "https://www.falabella.com.co"

    # CSS modules cambian hash, usamos "contains"
    SEL_PARENT = "[class*='FirstLevelCategories-module_categories']"
    SEL_ACTIVE = "[class*='FirstLevelCategories-module_active']"
    SEL_BLOCK = "[class*='SecondLevelCategories-module_secondLevelCategory']"

    def scrape_categories(self) -> List[Dict[str, Any]]:
        logger.info("Iniciando scraping de categorías de Falabella")

        try:
            logger.info(f"Abriendo {self.BASE_URL}")
            self.driver.get(self.BASE_URL)

            logger.info("Removiendo overlays")
            SeleniumHelpers.remove_overlays(self.driver)

            logger.info("Abriendo menú de categorías")
            self._open_menu()

            # ✅ CLAVE: recolectar nombres haciendo scroll en el panel
            parent_names = self._collect_parent_names()

            logger.info(f"Categorías padre encontradas (nombres únicos): {len(parent_names)}")

            results = self._extract_categories_by_names(parent_names)

            logger.info(f"Total categorías padre extraídas (con hijos): {len(results)}")
            return results

        except Exception as e:
            logger.error(f"Error scrapeando categorías: {e}", exc_info=True)
            self.log_error(
                error_type="PARSE",
                error_message=f"Error scrapeando categorías: {str(e)}",
                url=self.BASE_URL,
                stack_trace=traceback.format_exc(),
            )
            raise

    def _open_menu(self) -> None:
        btn = self.wait.until(
            EC.presence_of_element_located((By.ID, "testId-HamburgerBtn-toggle"))
        )
        SeleniumHelpers.click_element(self.driver, btn)

        self.wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, self.SEL_PARENT)) > 0)
        logger.debug("Menú hamburguesa abierto y categorías cargadas")

    # ----------------------------
    # 1) Recolectar nombres con scroll dentro del panel
    # ----------------------------
    def _collect_parent_names(self) -> List[str]:
        """
        Falabella suele virtualizar el menú: solo hay texto en el viewport.
        Aquí hacemos scroll dentro del contenedor para forzar que se rendericen todas.
        """
        seen = set()
        names: List[str] = []

        # Asegurar que hay al menos un elemento
        parents = self.driver.find_elements(By.CSS_SELECTOR, self.SEL_PARENT)
        if not parents:
            self._dump_debug("no_parents_collect")
            return names

        # Encontrar contenedor scrollable (ancestro con overflow auto/scroll)
        container = self._find_scroll_container(parents[0])

        def collect_visible():
            for el in self.driver.find_elements(By.CSS_SELECTOR, self.SEL_PARENT):
                name = SeleniumHelpers.clean_text(el.text)
                if name and name not in seen:
                    seen.add(name)
                    names.append(name)

        # recolectar primera pantalla
        collect_visible()

        # Si no hay contenedor scrollable, devolvemos lo que hay
        if not container:
            return names

        # Scroll incremental hasta que ya no aparezcan nombres nuevos
        stable_rounds = 0
        last_count = len(names)

        for _ in range(60):  # límite duro para no quedar infinito
            self.driver.execute_script(
                "arguments[0].scrollTop = arguments[0].scrollTop + arguments[0].clientHeight;",
                container,
            )
            time.sleep(0.25)
            collect_visible()

            if len(names) == last_count:
                stable_rounds += 1
            else:
                stable_rounds = 0
                last_count = len(names)

            # si 3 rondas seguidas sin nuevos nombres, asumimos final
            if stable_rounds >= 3:
                break

        # volver arriba (para que el procesamiento no empiece en el fondo)
        self.driver.execute_script("arguments[0].scrollTop = 0;", container)
        time.sleep(0.3)

        return names

    def _find_scroll_container(self, element) -> Optional[Any]:
        """
        Busca el ancestro más cercano que sea scrollable.
        """
        try:
            return self.driver.execute_script(
                """
                function isScrollable(el){
                  if (!el) return false;
                  const style = window.getComputedStyle(el);
                  const overflowY = style.overflowY;
                  return (overflowY === 'auto' || overflowY === 'scroll') && el.scrollHeight > el.clientHeight;
                }
                let el = arguments[0];
                while (el && el !== document.body) {
                  if (isScrollable(el)) return el;
                  el = el.parentElement;
                }
                return null;
                """,
                element,
            )
        except Exception:
            return None

    # ----------------------------
    # 2) Procesar por nombre (robusto)
    # ----------------------------
    def _extract_categories_by_names(self, parent_names: List[str]) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []

        if not parent_names:
            self._dump_debug("no_parent_names")
            return results

        def find_parent_by_name(target: str):
            for el in self.driver.find_elements(By.CSS_SELECTOR, self.SEL_PARENT):
                if SeleniumHelpers.clean_text(el.text) == target:
                    return el
            return None

        processed = 0

        for name in parent_names:
            ok = False

            for attempt in range(3):
                try:
                    el = find_parent_by_name(name)
                    if not el:
                        # si no está en el DOM visible, hacemos scrollIntoView con el primer match parcial
                        # (en virtualización, a veces solo aparece al scroll; por eso reintento)
                        time.sleep(0.2)
                        continue

                    self.driver.execute_script(
                        "arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});",
                        el,
                    )
                    time.sleep(0.2)

                    ActionChains(self.driver).move_to_element(el).pause(0.05).perform()

                    try:
                        self.wait.until(
                            lambda d: d.find_elements(By.CSS_SELECTOR, self.SEL_BLOCK)
                            or d.find_elements(By.CSS_SELECTOR, self.SEL_ACTIVE)
                        )
                    except TimeoutException:
                        time.sleep(0.4)
                        continue

                    time.sleep(0.4)

                    parent_obj = {"name": name, "children": []}

                    blocks = self.driver.find_elements(By.CSS_SELECTOR, self.SEL_BLOCK)
                    for block in blocks:
                        block_data = self._extract_block(block)
                        if block_data:
                            parent_obj["children"].append(block_data)

                    if parent_obj["children"]:
                        results.append(parent_obj)
                        logger.info(f"📁 {name} (OK)")
                    else:
                        logger.info(f"📁 {name} (sin hijos detectables)")

                    processed += 1
                    ok = True
                    break

                except (StaleElementReferenceException, ElementClickInterceptedException):
                    time.sleep(0.5)
                    continue
                except Exception as e:
                    logger.error(f"Error padre '{name}' intento {attempt+1}: {e}", exc_info=True)
                    time.sleep(0.5)

            if not ok:
                logger.warning(f"No se pudo procesar padre '{name}' tras reintentos")

        logger.info(f"Total padres procesados: {processed} / {len(parent_names)}")
        return results

    def _extract_block(self, block) -> Optional[Dict[str, Any]]:
        try:
            lis = block.find_elements(By.TAG_NAME, "li")
            if len(lis) < 2:
                return None

            block_name = SeleniumHelpers.clean_text(lis[0].text)
            if not block_name:
                return None

            children: List[Dict[str, str]] = []

            for li in lis[1:]:
                try:
                    a = li.find_element(By.TAG_NAME, "a")
                    name = SeleniumHelpers.clean_text(a.text)
                    url = (a.get_attribute("href") or "").strip()

                    if not name or name.lower() == "ver todo":
                        continue

                    children.append({"name": name, "url": url})
                except Exception:
                    continue

            if not children:
                return None

            return {"name": block_name, "children": children}
        except Exception:
            return None

    def _dump_debug(self, tag: str) -> None:
        try:
            png = f"/tmp/falabella_{tag}.png"
            html = f"/tmp/falabella_{tag}.html"
            self.driver.save_screenshot(png)
            with open(html, "w", encoding="utf-8") as f:
                f.write(self.driver.page_source)
            logger.warning(f"Debug dump: {png} y {html}")
        except Exception:
            pass

    def scrape_products(self, category_url: str) -> List[Dict[str, Any]]:
        logger.warning("scrape_products aún no implementado para Falabella")
        return []
