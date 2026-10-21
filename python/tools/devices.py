"""Dispositivos de referencia para probar y capturar el sitio.

Cada dispositivo indica el motor con que se prueba: WebKit (el motor de
Safari, el único que usa iOS/iPadOS y el de Safari en Mac), Chromium (Chrome,
Edge, Samsung Internet, el navegador de Android) o Firefox (Gecko). Las
medidas son el área visible en píxeles CSS; las de Playwright vienen de su
catálogo de dispositivos y el resto se calcula de la resolución y la
densidad de pantalla publicadas por el fabricante (aproximadas).
"""

from __future__ import annotations

# (id, nombre, motor, descriptor de Playwright o None, ajustes propios)
DEVICES: list[tuple[str, str, str, str | None, dict]] = [
    ("kaios-flip", "Teléfono de tapa básico (KaiOS, 240×320)", "firefox", None,
     {"viewport": {"width": 240, "height": 320}, "device_scale_factor": 1, "is_mobile": False, "has_touch": False}),
    ("galaxy-s9", "Samsung Galaxy S9+", "chromium", "Galaxy S9+", {}),
    ("iphone-se", "iPhone SE (3.ª generación)", "webkit", "iPhone SE (3rd gen)", {}),
    ("iphone-x", "iPhone X (iPhone 10)", "webkit", "iPhone X", {}),
    ("iphone-15-pro-max", "iPhone 15 Pro Max", "webkit", "iPhone 15 Pro Max", {}),
    ("galaxy-s24", "Samsung Galaxy S24", "chromium", "Galaxy S24", {}),
    ("galaxy-a55", "Samsung Galaxy A55", "chromium", "Galaxy A55", {}),
    ("pixel-7", "Google Pixel 7 (Android)", "chromium", "Pixel 7", {}),
    ("galaxy-zflip-cover", "Samsung Galaxy Z Flip6, pantalla externa", "chromium", "Galaxy S24",
     {"viewport": {"width": 360, "height": 374}, "device_scale_factor": 2}),
    ("galaxy-zflip-open", "Samsung Galaxy Z Flip6 abierto", "chromium", "Galaxy S24",
     {"viewport": {"width": 412, "height": 1005}, "device_scale_factor": 2.625}),
    ("galaxy-zfold-open", "Samsung Galaxy Z Fold6 abierto", "chromium", "Galaxy S24",
     {"viewport": {"width": 707, "height": 823}, "device_scale_factor": 2.625}),
    ("ipad", "iPad (11.ª generación)", "webkit", "iPad (gen 11)", {}),
    ("laptop-1366", "Laptop 1366×768 (Windows, Chrome)", "chromium", "Desktop Chrome",
     {"viewport": {"width": 1366, "height": 657}}),
    ("macbook-air", "MacBook Air 13″ (Safari)", "webkit", "Desktop Safari",
     {"viewport": {"width": 1470, "height": 830}, "device_scale_factor": 2}),
    ("pc-fullhd-firefox", "PC Full HD (Windows, Firefox)", "firefox", "Desktop Firefox",
     {"viewport": {"width": 1920, "height": 960}}),
    ("pc-fullhd-edge", "PC Full HD (Windows, Edge)", "chromium", "Desktop Edge",
     {"viewport": {"width": 1920, "height": 960}}),
]


def context_options(playwright, engine: str, descriptor: str | None, extra: dict) -> dict:
    opts = dict(playwright.devices[descriptor]) if descriptor else {}
    opts.pop("default_browser_type", None)
    opts.update(extra)
    if engine == "firefox":
        opts.pop("is_mobile", None)  # Firefox no admite el modo móvil de Playwright
    opts.setdefault("locale", "es-PE")
    opts.setdefault("timezone_id", "America/Lima")
    return opts
