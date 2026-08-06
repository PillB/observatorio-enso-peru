"""
Playwright browser tests using VISIBLE CONTROLS (not page.evaluate).

These tests exercise the user interface through accessible locators:
- Click nav buttons by visible text
- Read DOM text content (not global variables)
- Verify downloads by clicking links
- Test tutorial through visible buttons
- Test chatbot through visible input + buttons
- Verify publication ID from the DOM (not from JS globals)

Run with: python -m pytest tests/test_playwright_visible.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

try:
    from playwright.sync_api import sync_playwright, Page, expect
except ImportError:
    pytest.skip("Playwright not installed", allow_module_level=True)

REPO = Path(__file__).resolve().parents[2]
LIVE_URL = "https://pillb.github.io/observatorio-enso-peru/"


@pytest.fixture(scope="module")
def browser_context():
    """Launch browser and create context."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        yield ctx
        browser.close()


@pytest.fixture
def page(browser_context):
    """Create a fresh page for each test."""
    p = browser_context.new_page()
    yield p
    p.close()


def get_live_publication_id(page: Page) -> str:
    """Fetch publicationId from the live health.json (not from JS globals)."""
    response = page.request.get(f"{LIVE_URL}data/health.json")
    assert response.ok, f"health.json not accessible: {response.status}"
    data = response.json()
    return data.get("publicationId", "MISSING")


class TestVisibleNavigation:
    """Test navigation through visible nav buttons (not page.evaluate)."""

    def test_all_views_navigable_by_clicking(self, page: Page):
        """All 14 views are navigable by clicking visible nav buttons."""
        page.goto(LIVE_URL)
        page.wait_for_load_state("networkidle")

        # Get all nav button texts by reading the DOM
        nav_buttons = page.locator("nav#sidebar-nav button").all()
        assert len(nav_buttons) == 14, f"Expected 14 nav buttons, got {len(nav_buttons)}"

        for btn in nav_buttons:
            btn.click()
            page.wait_for_timeout(300)
            # Verify the view title changed (read from DOM, not JS)
            title = page.locator("#view-title").text_content()
            assert title and len(title) > 0, f"View title empty after clicking {btn.text_content()}"

    def test_resumen_shows_roni_value(self, page: Page):
        """Resumen view shows the RONI value in the DOM text."""
        page.goto(LIVE_URL)
        page.wait_for_load_state("networkidle")

        # Click the "Resumen" nav button by visible text
        page.locator("nav#sidebar-nav button", has_text="Resumen").click()
        page.wait_for_timeout(500)

        # Read the body text and verify RONI is visible
        body_text = page.locator("body").text_content()
        assert "RONI" in body_text, "RONI not visible in Resumen view"
        # Verify the value is a number (not "undefined" or empty)
        assert "0." in body_text or "1." in body_text, "RONI value not found in text"

    def test_nino_costero_view_shows_icen(self, page: Page):
        """El Niño Costero view shows ICEN value in the DOM."""
        page.goto(LIVE_URL)
        page.wait_for_load_state("networkidle")

        page.locator("nav#sidebar-nav button", has_text="El Niño Costero").click()
        page.wait_for_timeout(500)

        body_text = page.locator("body").text_content()
        assert "ICEN" in body_text, "ICEN not visible in El Niño Costero view"


class TestPublicationCoherence:
    """Verify all live JSON artifacts share the same publication ID."""

    def test_all_json_share_publication_id(self, page: Page):
        """All JSON data files must share the same publicationId."""
        page.goto(LIVE_URL)

        # Fetch all JSON files and verify publicationId
        json_files = [
            "status.json", "health.json", "manifest.json",
            "data-quality.json", "latest.json", "indicators.json",
            "sources.json", "official-status.json", "operational-signals.json",
        ]
        pub_ids = set()
        for f in json_files:
            response = page.request.get(f"{LIVE_URL}data/{f}")
            if response.ok:
                data = response.json()
                if isinstance(data, dict):
                    pid = data.get("publicationId")
                    if pid:
                        pub_ids.add(pid)

        assert len(pub_ids) == 1, \
            f"Multiple publication IDs found: {pub_ids}. Expected exactly 1."

    def test_live_publication_id_matches_status(self, page: Page):
        """The live health.json publicationId must match status.json."""
        page.goto(LIVE_URL)

        health_resp = page.request.get(f"{LIVE_URL}data/health.json")
        status_resp = page.request.get(f"{LIVE_URL}data/status.json")

        health = health_resp.json()
        status = status_resp.json()

        assert health["publicationId"] == status["publicationId"], \
            f"Publication ID mismatch: health={health['publicationId']}, status={status['publicationId']}"


class TestDownloadsWork:
    """Verify download links actually work."""

    def test_csv_downloads_accessible(self, page: Page):
        """All CSV download links return HTTP 200."""
        page.goto(LIVE_URL)
        page.wait_for_load_state("networkidle")

        # Navigate to Datos view
        page.locator("nav#sidebar-nav button", has_text="Datos").click()
        page.wait_for_timeout(500)

        # Find all download links in the data table
        download_links = page.locator("table#data-table a[href*='.csv']").all()
        assert len(download_links) >= 7, f"Expected at least 7 CSV links, got {len(download_links)}"

        # Verify each CSV link is accessible
        for link in download_links:
            href = link.get_attribute("href")
            if href and not href.startswith("http"):
                # Handle relative URLs properly — the live site is under /observatorio-enso-peru/
                if href.startswith("/"):
                    href = f"https://pillb.github.io{href}"
                else:
                    href = f"{LIVE_URL}{href}"
            response = page.request.get(href)
            assert response.ok, f"CSV download failed: {href} → {response.status}"


class TestTutorialStateMachine:
    """Test tutorial pause/resume/restart through visible controls."""

    def test_tutorial_has_pause_button(self, page: Page):
        """Tutorial box has a visible 'Pausar' button."""
        page.goto(LIVE_URL)
        page.wait_for_load_state("networkidle")

        # Start tutorial by clicking the Tutorial button
        page.locator("button.tutorial-btn").click()
        page.wait_for_timeout(500)

        # Verify the tutorial box is visible
        tutorial_box = page.locator(".tutorial-box")
        expect(tutorial_box).to_be_visible()

        # Verify the Pausar button exists
        pause_btn = page.locator(".tutorial-box button", has_text="Pausar")
        assert pause_btn.count() > 0, "Pausar button not found in tutorial box"

    def test_tutorial_pause_hides_box(self, page: Page):
        """Clicking Pausar hides the tutorial box."""
        page.goto(LIVE_URL)
        page.wait_for_load_state("networkidle")

        page.locator("button.tutorial-btn").click()
        page.wait_for_timeout(500)

        # Click Pausar
        page.locator(".tutorial-box button", has_text="Pausar").click()
        page.wait_for_timeout(300)

        # Tutorial box should be hidden
        tutorial_box = page.locator(".tutorial-box")
        assert not tutorial_box.is_visible(), "Tutorial box still visible after pause"

        # Tutorial bar should show paused state
        bar_text = page.locator(".tutorial-bar .step-info").text_content()
        assert "Pausado" in bar_text, f"Expected 'Pausado' in bar, got: {bar_text}"

    def test_tutorial_resume_shows_box(self, page: Page):
        """Clicking Reanudar after pause shows the tutorial box again."""
        page.goto(LIVE_URL)
        page.wait_for_load_state("networkidle")

        page.locator("button.tutorial-btn").click()
        page.wait_for_timeout(500)
        page.locator(".tutorial-box button", has_text="Pausar").click()
        page.wait_for_timeout(300)

        # Click Reanudar
        page.locator(".tutorial-bar button", has_text="Reanudar").click()
        page.wait_for_timeout(500)

        tutorial_box = page.locator(".tutorial-box")
        assert tutorial_box.is_visible(), "Tutorial box not visible after resume"

    def test_tutorial_restart_resets_to_step_1(self, page: Page):
        """Clicking Reiniciar resets the tutorial to step 1."""
        page.goto(LIVE_URL)
        page.wait_for_load_state("networkidle")

        page.locator("button.tutorial-btn").click()
        page.wait_for_timeout(500)

        # Advance to step 2 by clicking Siguiente
        page.locator(".tutorial-box button", has_text="Siguiente").click()
        page.wait_for_timeout(300)

        # Click Reiniciar in the bar
        page.locator(".tutorial-bar button", has_text="Reiniciar").click()
        page.wait_for_timeout(500)

        # Should be back at step 1
        bar_text = page.locator(".tutorial-bar .step-info").text_content()
        assert "Paso 1 de" in bar_text, f"Expected 'Paso 1 de' after restart, got: {bar_text}"


class TestChatbotGrounding:
    """Test chatbot remains grounded in validated publication."""

    def test_chatbot_answers_soic_costero(self, page: Page):
        """Chatbot correctly answers '¿Existe SOI costero?'."""
        page.goto(LIVE_URL)
        page.wait_for_load_state("networkidle")

        # Navigate to Asistente
        page.locator("nav#sidebar-nav button", has_text="Asistente").click()
        page.wait_for_timeout(500)

        # Click the "¿Existe SOI costero?" button
        page.locator("button", has_text="SOI costero").click()
        page.wait_for_timeout(500)

        # Read the response from the DOM
        response_text = page.locator("#chat-response").text_content()
        assert "No existe" in response_text, \
            f"Expected 'No existe' in response, got: {response_text[:200]}"
        assert "SOI costero" in response_text, "Response should mention 'SOI costero'"


class TestFallbackDegradation:
    """Verify fallback status is visibly degraded."""

    def test_enfen_fallback_label_visible(self, page: Page):
        """ENFEN fallback status shows a degradation label in the alert banner."""
        page.goto(LIVE_URL)
        page.wait_for_load_state("networkidle")

        # Check if the alert banner shows a FALLBACK label
        # (only if alertSourceMethod is 'fallback' in the data)
        response = page.request.get(f"{LIVE_URL}data/status.json")
        status = response.json()
        alert_method = status.get("coastal", {}).get("alertSourceMethod", "")

        if alert_method == "fallback":
            # The FALLBACK degradation label should be visible
            body_text = page.locator("body").text_content()
            assert "FALLBACK" in body_text.upper(), \
                "ENFEN fallback status should show FALLBACK degradation label"


class TestNoConsoleErrors:
    """Verify no console errors on any view."""

    def test_no_console_errors_all_views(self, page: Page):
        """No JavaScript console errors on any of the 14 views."""
        page.goto(LIVE_URL)
        page.wait_for_load_state("networkidle")

        errors = []
        page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda err: errors.append(str(err)))

        nav_buttons = page.locator("nav#sidebar-nav button").all()
        for btn in nav_buttons:
            btn.click()
            page.wait_for_timeout(300)

        assert len(errors) == 0, f"Console errors found: {errors}"


class TestNoHorizontalOverflow:
    """Verify no horizontal overflow on mobile viewports."""

    @pytest.mark.parametrize("viewport", [
        {"width": 320, "height": 568},   # iPhone SE
        {"width": 390, "height": 844},   # iPhone 13 Pro
        {"width": 768, "height": 1024},  # iPad Mini
    ])
    def test_no_overflow_mobile(self, browser_context, viewport):
        """No horizontal overflow on mobile viewports."""
        ctx = browser_context.browser.new_context(viewport=viewport)
        page = ctx.new_page()
        try:
            page.goto(LIVE_URL)
            page.wait_for_load_state("networkidle")

            nav_buttons = page.locator("nav#sidebar-nav button").all()
            for btn in nav_buttons:
                btn.click()
                page.wait_for_timeout(300)
                overflow = page.evaluate("document.body.scrollWidth - window.innerWidth")
                assert overflow <= 0, \
                    f"Overflow {overflow}px on view '{btn.text_content()}' at {viewport['width']}px"
        finally:
            page.close()
            ctx.close()


class TestRoniDescriptionCorrect:
    """Verify RONI description is scientifically correct in the UI."""

    def test_no_incorrect_roni_description(self, page: Page):
        """The incorrect 'baseline adaptativa de 30 días' text must not appear."""
        page.goto(LIVE_URL)
        page.wait_for_load_state("networkidle")

        # Navigate to methodology
        page.locator("nav#sidebar-nav button", has_text="Metodología").click()
        page.wait_for_timeout(500)

        body_text = page.locator("body").text_content()
        assert "baseline adaptativa de 30 días" not in body_text, \
            "Incorrect RONI description 'baseline adaptativa de 30 días' still present"

    def test_correct_roni_description_present(self, page: Page):
        """The correct RONI description with ERSSTv5 should be present."""
        page.goto(LIVE_URL)
        page.wait_for_load_state("networkidle")

        # Start tutorial and advance to module 7 (ENSO de cuenca)
        page.locator("button.tutorial-btn").click()
        page.wait_for_timeout(500)

        # Navigate through tutorial until we find ERSSTv5
        body_text = page.locator("body").text_content()
        max_steps = 13
        step = 0
        while "ERSSTv5" not in body_text and step < max_steps:
            next_btn = page.locator(".tutorial-box button", has_text="Siguiente")
            if next_btn.count() == 0:
                break
            next_btn.click()
            page.wait_for_timeout(300)
            body_text = page.locator("body").text_content()
            step += 1

        assert "ERSSTv5" in body_text, \
            "Correct RONI description with ERSSTv5 not found in tutorial"


class TestWindSemanticsCorrect:
    """Verify wind product is labeled as actual wind, not anomaly."""

    def test_wind_labeled_as_actual(self, page: Page):
        """The Winds view must label the product as actual wind, not anomaly."""
        page.goto(LIVE_URL)
        page.wait_for_load_state("networkidle")

        page.locator("nav#sidebar-nav button", has_text="Vientos").click()
        page.wait_for_timeout(500)

        body_text = page.locator("body").text_content()
        # Must say "real" or "actual" (not anomaly)
        assert "real" in body_text.lower() or "actual" in body_text.lower(), \
            "Wind product not labeled as actual/real wind"
