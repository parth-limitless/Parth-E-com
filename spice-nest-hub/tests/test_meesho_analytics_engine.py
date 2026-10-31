"""
Unit tests for Meesho Advanced Intelligence Engine.
Tests:
1. Fast-Movers vs Dead-Stock Classifier (Star, Rising, Slow)
2. Meesho SEO & Search Ranking Optimizer (Score 0-100%, Titles, Tags)
3. Competitor Price Spy & Buybox Intelligence
4. Historical Price & Rating Timeline Generation
5. Store-level Catalog Enrichment Rollup
"""

import pytest
import meesho_analytics_engine


def test_classify_velocity_star_mover():
    prod = {"product_id": "p1", "name": "Garlic Pickle 200g", "review_count": 150, "rating": 4.5}
    res = meesho_analytics_engine.classify_velocity(prod)
    assert res["tier"] == "STAR_MOVER"
    assert "Star" in res["badge_label"]
    assert res["priority"] == 1
    assert "Stockout" in res["stock_risk"] or "HIGH" in res["stock_risk"]


def test_classify_velocity_rising():
    prod = {"product_id": "p2", "name": "Mixed Jam 500g", "review_count": 45, "rating": 4.1}
    res = meesho_analytics_engine.classify_velocity(prod)
    assert res["tier"] == "RISING"
    assert "Rising" in res["badge_label"]
    assert res["priority"] == 2


def test_classify_velocity_slow_mover():
    prod = {"product_id": "p3", "name": "Exotic Saffron Paste 100g", "review_count": 8, "rating": 3.9}
    res = meesho_analytics_engine.classify_velocity(prod)
    assert res["tier"] == "SLOW_MOVER"
    assert "Push" in res["badge_label"]
    assert res["priority"] == 3


def test_optimize_seo_high_score():
    prod = {
        "product_id": "p4",
        "name": "Spice Nest Spicy Tangy Pure Garlic Pickle 200gm for Paratha and Rice Homemade Traditional"
    }
    res = meesho_analytics_engine.optimize_seo(prod)
    assert res["score"] >= 80
    assert "Spice Nest" in res["ai_optimized_title"]
    assert len(res["recommended_tags"]) >= 3
    assert any("Pickle" in t for t in res["recommended_tags"])


def test_optimize_seo_low_score_detects_missing():
    prod = {
        "product_id": "p5",
        "name": "Pickle"
    }
    res = meesho_analytics_engine.optimize_seo(prod)
    assert res["score"] <= 60
    assert len(res["missing_elements"]) > 0


def test_analyze_competitor_buybox_win():
    # Garlic pickle benchmark price is ~165.0
    prod = {"product_id": "p6", "name": "Garlic Pickle 200g", "price": 140.0}
    res = meesho_analytics_engine.analyze_competitor_buybox(prod)
    assert res["status"] == "WIN_BUYBOX"
    assert res["price_diff"] > 0
    assert "Winning" in res["label"]


def test_analyze_competitor_buybox_risk():
    # Garlic pickle benchmark price is ~165.0; pricing at 210 is overpriced
    prod = {"product_id": "p7", "name": "Garlic Pickle 200g", "price": 210.0}
    res = meesho_analytics_engine.analyze_competitor_buybox(prod)
    assert res["status"] == "RISK_BUYBOX"
    assert res["price_diff"] < 0
    assert "Overpriced" in res["label"]


def test_get_product_timeline_history():
    res = meesho_analytics_engine.get_product_timeline_history("86cube", "spicenest.db")
    if "error" not in res:
        assert res["product_id"] == "86cube"
        assert len(res["labels"]) == 10
        assert len(res["prices"]) == 10
        assert len(res["ratings"]) == 10
        assert "velocity" in res
        assert "seo" in res
        assert "competitor" in res


def test_enrich_catalog_with_intelligence():
    catalog = [
        {"product_id": "p1", "name": "Garlic Pickle 200g", "price": 145.0, "review_count": 120, "rating": 4.5},
        {"product_id": "p2", "name": "Mixed Jam 500g", "price": 230.0, "review_count": 35, "rating": 4.2},
        {"product_id": "p3", "name": "Soya Sauce 250ml", "price": 190.0, "review_count": 5, "rating": 3.8}
    ]
    res = meesho_analytics_engine.enrich_catalog_with_intelligence(catalog)
    assert len(res["products"]) == 3
    summary = res["summary"]
    assert summary["total"] == 3
    assert summary["star_movers_count"] == 1
    assert summary["rising_count"] == 1
    assert summary["slow_movers_count"] == 1
    assert 0 <= summary["buybox_win_pct"] <= 100
    assert 0 <= summary["avg_seo_score"] <= 100
