import logging
import re
import time
import traceback
from decimal import Decimal
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode, urlparse, parse_qsl, urlunparse

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

    SEL_PARENT = "[class*='FirstLevelCategories-module_categories']"
    SEL_ACTIVE = "[class*='FirstLevelCategories-module_active']"
    SEL_BLOCK = "[class*='SecondLevelCategories-module_secondLevelCategory']"

    def scrape_categories(self) -> List[Dict[str, Any]]:
        logger.info("Iniciando scraping de categorías de Falabella")

        try:
            logger.info("Abriendo %s", self.BASE_URL)
            self.driver.get(self.BASE_URL)

            logger.info("Removiendo overlays")
            SeleniumHelpers.remove_overlays(self.driver)

            logger.info("Abriendo menú de categorías")
            self._open_menu()

            parent_names = self._collect_parent_names()
            logger.info("Categorías padre encontradas (nombres únicos): %s", len(parent_names))

            results = self._extract_categories_by_names(parent_names)
            logger.info("Total categorías padre extraídas (con hijos): %s", len(results))
            return results

        except Exception as e:
            logger.error("Error scrapeando categorías: %s", e, exc_info=True)
            self.log_error(
                error_type="PARSE",
                error_message=f"Error scrapeando categorías: {str(e)}",
                url=self.BASE_URL,
                stack_trace=traceback.format_exc(),
            )
            raise

    def _open_menu(self) -> None:
        btn = self.wait.until(EC.presence_of_element_located((By.ID, "testId-HamburgerBtn-toggle")))
        SeleniumHelpers.click_element(self.driver, btn)
        self.wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, self.SEL_PARENT)) > 0)

    def _collect_parent_names(self) -> List[str]:
        seen = set()
        names: List[str] = []

        parents = self.driver.find_elements(By.CSS_SELECTOR, self.SEL_PARENT)
        if not parents:
            self._dump_debug("no_parents_collect")
            return names

        container = self._find_scroll_container(parents[0])

        def collect_visible():
            for el in self.driver.find_elements(By.CSS_SELECTOR, self.SEL_PARENT):
                name = SeleniumHelpers.clean_text(el.text)
                if name and name not in seen:
                    seen.add(name)
                    names.append(name)

        collect_visible()

        if not container:
            return names

        stable_rounds = 0
        last_count = len(names)

        for _ in range(60):
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

            if stable_rounds >= 3:
                break

        self.driver.execute_script("arguments[0].scrollTop = 0;", container)
        time.sleep(0.3)

        return names

    def _find_scroll_container(self, element) -> Optional[Any]:
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

                    processed += 1
                    ok = True
                    break

                except (StaleElementReferenceException, ElementClickInterceptedException):
                    time.sleep(0.5)
                    continue
                except Exception as e:
                    logger.error("Error padre '%s' intento %s: %s", name, attempt + 1, e, exc_info=True)
                    time.sleep(0.5)

            if not ok:
                logger.warning("No se pudo procesar padre '%s' tras reintentos", name)

        logger.info("Total padres procesados: %s / %s", processed, len(parent_names))
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

    # ----------------------------
    # Productos (lógica del lab)
    # ----------------------------
    def scrape_products(self, category_url: str) -> List[Dict[str, Any]]:
        logger.info("Scrapeando productos: %s", category_url)
        results: List[Dict[str, Any]] = []

        try:
            base_url = (category_url or "").strip()
            if not base_url:
                return results

            self.driver.get(base_url)
            SeleniumHelpers.remove_overlays(self.driver)

            if self._is_no_result():
                self._dump_debug("products_no_result_base")
                return results

            if not self._wait_products_container(timeout=25):
                alt = self._ensure_is_plp(base_url)
                if alt and alt != base_url:
                    self.driver.get(alt)
                    SeleniumHelpers.remove_overlays(self.driver)

                if self._is_no_result() or not self._wait_products_container(timeout=25):
                    self._dump_debug("products_base_not_loaded")
                    return results

            SeleniumHelpers.remove_overlays(self.driver)

            max_pages = self._detect_max_pages()
            if max_pages is None:
                max_pages = 30

            seen = set()

            page_items = self._extract_products_from_current_page()
            for item in page_items:
                u = item.get("url")
                if u and u not in seen:
                    seen.add(u)
                    results.append(item)

            for page in range(2, max_pages + 1):
                page_url = self._with_page_param(base_url, page)
                self.driver.get(page_url)
                SeleniumHelpers.remove_overlays(self.driver)

                if self._is_no_result():
                    break

                if not self._wait_products_container(timeout=25):
                    break

                SeleniumHelpers.remove_overlays(self.driver)

                page_items = self._extract_products_from_current_page()
                if not page_items:
                    break

                for item in page_items:
                    u = item.get("url")
                    if u and u not in seen:
                        seen.add(u)
                        results.append(item)

            return results

        except Exception as e:
            logger.error("Error scrapeando productos: %s", e, exc_info=True)
            self.log_error(
                error_type="PARSE",
                error_message=f"Error scrapeando productos: {str(e)}",
                url=category_url,
                stack_trace=traceback.format_exc(),
            )
            return results

    def _wait_products_container(self, timeout: int = 25) -> bool:
        try:
            self.wait.__class__(self.driver, timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "#testId-searchResults-products"))
            )
            return True
        except Exception:
            return False

    def _is_no_result(self) -> bool:
        try:
            url = (self.driver.current_url or "").lower()
            if "/noresult" in url:
                return True
            body_txt = (self.driver.find_element(By.TAG_NAME, "body").text or "").lower()
            return ("no encontramos resultados" in body_txt) or ("lo sentimos, no encontramos resultados" in body_txt)
        except Exception:
            return False

    def _ensure_is_plp(self, url: str) -> Optional[str]:
        try:
            parsed = urlparse(url)
            qs = dict(parse_qsl(parsed.query, keep_blank_values=True))
            if qs.get("isPLP") == "1":
                return url
            qs["isPLP"] = "1"
            new_q = urlencode(qs, doseq=True)
            return urlunparse(parsed._replace(query=new_q))
        except Exception:
            return None

    @staticmethod
    def _clean(text: str) -> str:
        return re.sub(r"\s+", " ", (text or "").replace("\n", " ")).strip()

    @staticmethod
    def _parse_price_attr(value: str) -> Optional[Decimal]:
        if not value:
            return None
        v = value.strip().replace(".", "").replace(",", ".")
        try:
            return Decimal(v).quantize(Decimal("0.01"))
        except Exception:
            return None

    @staticmethod
    def _parse_price_text(text: str) -> Optional[Decimal]:
        if not text:
            return None
        t = text.replace("\xa0", " ")
        m = re.search(r"\$\s*([\d\.\,]+)", t)
        if not m:
            return None
        num = m.group(1).replace(".", "").replace(",", ".")
        try:
            return Decimal(num).quantize(Decimal("0.01"))
        except Exception:
            return None

    def _extract_products_from_current_page(self) -> List[Dict[str, Any]]:
        products: List[Dict[str, Any]] = []

        container = self.driver.find_element(By.CSS_SELECTOR, "#testId-searchResults-products")
        anchors = container.find_elements(By.CSS_SELECTOR, "a[href*='/product/']")

        seen_local = set()

        for a in anchors:
            try:
                url = (a.get_attribute("href") or "").strip()
                if not url or url in seen_local:
                    continue
                seen_local.add(url)

                card = a.find_element(By.XPATH, "./ancestor::*[self::article or self::div][1]")

                name = self._clean(a.text)
                if not name or len(name) < 3:
                    imgs = a.find_elements(By.CSS_SELECTOR, "img[alt]")
                    if imgs:
                        name = self._clean(imgs[0].get_attribute("alt"))

                name = re.sub(r"\bPatrocinado\b", "", name, flags=re.IGNORECASE).strip()

                prices: List[Decimal] = []

                price_blocks = card.find_elements(By.CSS_SELECTOR, "div[id^='testId-pod-prices-']")
                for pb in price_blocks:
                    lis = pb.find_elements(By.CSS_SELECTOR, "li")
                    for li in lis:
                        attrs = self.driver.execute_script(
                            """
                            const el = arguments[0];
                            const out = [];
                            for (const a of el.attributes) {
                              if (a.name.startsWith('data-') && a.name.endsWith('-price')) out.push(a.value);
                            }
                            return out;
                            """,
                            li,
                        )
                        for v in (attrs or []):
                            p = self._parse_price_attr(v)
                            if p is not None:
                                prices.append(p)

                    if not prices:
                        spans = pb.find_elements(By.XPATH, ".//*[contains(text(), '$')]")
                        for sp in spans:
                            p = self._parse_price_text(sp.text)
                            if p is not None:
                                prices.append(p)

                if not prices:
                    any_price_nodes = card.find_elements(By.XPATH, ".//*[contains(text(), '$')]")
                    for n in any_price_nodes:
                        p = self._parse_price_text(n.text)
                        if p is not None:
                            prices.append(p)

                price = min(prices) if prices else None
                original_price = max(prices) if prices and len(prices) >= 2 else None

                products.append(
                    {
                        "name": name or None,
                        "url": url,
                        "price": price,
                        "original_price": original_price,
                        "is_available": True,
                    }
                )

            except (StaleElementReferenceException, Exception):
                continue

        return products

    def _detect_max_pages(self) -> Optional[int]:
        try:
            containers = self.driver.find_elements(By.CSS_SELECTOR, "div[data-pagination-container='true']")
            if not containers:
                return None

            btns = self.driver.find_elements(By.CSS_SELECTOR, "button[id^='testId-pagination-top-button']")
            nums: List[int] = []
            for b in btns:
                t = self._clean(b.text)
                if t.isdigit():
                    nums.append(int(t))

            return max(nums) if nums else None
        except Exception:
            return None

    @staticmethod
    def _with_page_param(url: str, page: int) -> str:
        parsed = urlparse(url)
        qs = dict(parse_qsl(parsed.query, keep_blank_values=True))
        qs["page"] = str(page)
        new_q = urlencode(qs, doseq=True)
        return urlunparse(parsed._replace(query=new_q))

    def _dump_debug(self, tag: str) -> None:
        try:
            png = f"/tmp/falabella_{tag}.png"
            html = f"/tmp/falabella_{tag}.html"
            self.driver.save_screenshot(png)
            with open(html, "w", encoding="utf-8") as f:
                f.write(self.driver.page_source)
            logger.warning("Debug dump: %s y %s", png, html)
        except Exception:
            pass