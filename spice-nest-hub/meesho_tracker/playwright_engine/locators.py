"""
Playwright Automation - Accessibility & Semantic Locators
=========================================================
Encapsulates accessibility-first and resilient semantic locators for Meesho:
- Prioritizes get_by_role, get_by_text, get_by_label, get_by_placeholder
- Avoids fragile, minified or hashed CSS classes
- Supports common interactive components (modals, dropdowns, search, cards, cart)
"""

import re
from typing import Optional
from playwright.async_api import Locator, Page


class MeeshoLocators:
    """Central repository of accessibility and resilient semantic locators for Meesho."""

    def __init__(self, page: Page):
        self.page = page

    # --- Store & Search Navigation ---
    @property
    def search_box(self) -> Locator:
        """Search input field located via accessible placeholder or role."""
        return self.page.get_by_placeholder(
            re.compile(r"search|product code|try saree", re.I)
        ).or_(self.page.get_by_role("searchbox")).or_(self.page.locator("input[type='text'][placeholder*='Search' i]")).first

    @property
    def product_cards(self) -> Locator:
        """Product cards linked via canonical /p/ PDP URLs."""
        return self.page.locator("a[href*='/p/']")

    @property
    def store_name_heading(self) -> Locator:
        """Store header title."""
        return self.page.get_by_role("heading", level=2).or_(self.page.get_by_role("heading", level=1)).first

    @property
    def follow_button(self) -> Locator:
        """Follow store button."""
        return self.page.get_by_role("button", name=re.compile(r"^follow$", re.I)).first

    # --- Product Card Details ---
    def card_title(self, card: Locator) -> Locator:
        return card.locator("p, [class*='ProductTitle']").first

    def card_price(self, card: Locator) -> Locator:
        return card.locator("h5, [class*='Price']").filter(has_text="₹").first

    def card_rating(self, card: Locator) -> Locator:
        return card.locator("[class*='Rating__StyledPill'], [class*='RatingSection'] span").first

    def card_reviews(self, card: Locator) -> Locator:
        return card.locator("[class*='RatingCount'], span").filter(has_text=re.compile(r"reviews?|ratings?", re.I)).first

    # --- Loading & Status Indicators ---
    @property
    def loading_spinners(self) -> Locator:
        """Active loading animations and progress indicators."""
        return self.page.locator(
            "[role='progressbar'], [aria-busy='true'], div[class*='loader' i], div[class*='spinner' i]"
        )

    # --- Modals, Popups & Dialogs ---
    @property
    def modal_dialog(self) -> Locator:
        """Any open modal dialog or overlay container."""
        return self.page.get_by_role("dialog").or_(self.page.locator("div[class*='Modal' i], div[class*='Dialog' i]"))

    @property
    def modal_close_button(self) -> Locator:
        """Close / dismiss button inside a modal or dialog."""
        return self.page.locator(
            "button[aria-label*='close' i], button[aria-label*='dismiss' i], button:has-text('✕'), button:has-text('×'), [class*='CloseButton' i]"
        ).or_(self.page.get_by_role("button", name=re.compile(r"close|dismiss|skip|not now", re.I)))

    # --- Dropdowns & Menus ---
    @property
    def sort_dropdown_button(self) -> Locator:
        """Sort by dropdown trigger button."""
        return self.page.get_by_role("button", name=re.compile(r"sort", re.I)).or_(
            self.page.locator("div[class*='Sort' i], span:has-text('Sort by')"
        )).first

    def dropdown_option(self, option_text: str) -> Locator:
        """Accessible option inside a dropdown or listbox."""
        return self.page.get_by_role("option", name=re.compile(re.escape(option_text), re.I)).or_(
            self.page.get_by_role("menuitem", name=re.compile(re.escape(option_text), re.I))
        ).or_(self.page.locator(f"li:has-text('{option_text}'), span:has-text('{option_text}')")).first

    # --- Product Page (PDP) Actions ---
    @property
    def add_to_cart_button(self) -> Locator:
        return self.page.get_by_role("button", name=re.compile(r"add to cart", re.I)).first

    @property
    def buy_now_button(self) -> Locator:
        return self.page.get_by_role("button", name=re.compile(r"buy now", re.I)).first

    @property
    def size_options(self) -> Locator:
        return self.page.locator("span[class*='Size'], button:has-text('Free Size'), button:has-text('Pack of')")

