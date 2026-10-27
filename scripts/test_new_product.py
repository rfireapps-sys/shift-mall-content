import json
import tempfile
import unittest
from pathlib import Path

import new_product as np_


def page(*jsonld, meta="", title=""):
    scripts = "".join('<script type="application/ld+json">%s</script>' % json.dumps(j, ensure_ascii=False)
                      for j in jsonld)
    return "<html><head><title>%s</title>%s%s</head><body></body></html>" % (title, meta, scripts)


class ExtractTest(unittest.TestCase):
    def test_jsonld_product_with_offer(self):
        info = np_.extract_from_page(page({
            "@context": "https://schema.org", "@type": "Product", "name": "ワイヤレスイヤホン",
            "image": "https://shop.example/a.jpg", "description": "説明",
            "offers": {"@type": "Offer", "price": "2480", "priceCurrency": "JPY"}}))
        self.assertEqual(info["name"], "ワイヤレスイヤホン")
        self.assertEqual(info["price"], 2480)
        self.assertEqual(info["currency"], "JPY")
        # 画像はページから取らない
        self.assertIsNone(info["imageUrl"])

    def test_graph_and_aggregate_offer_takes_lowest(self):
        info = np_.extract_from_page(page({"@context": "https://schema.org", "@graph": [
            {"@type": "WebPage", "name": "ページ"},
            {"@type": ["Product"], "name": "マグカップ",
             "offers": [{"@type": "AggregateOffer", "lowPrice": 1200, "highPrice": 1800, "priceCurrency": "JPY"},
                        {"@type": "Offer", "price": "1,500", "priceCurrency": "JPY"}]}]}))
        self.assertEqual(info["name"], "マグカップ")
        self.assertEqual(info["price"], 1200)

    def test_broken_jsonld_is_skipped(self):
        html = ('<script type="application/ld+json">{ broken</script>'
                + page({"@type": "Product", "name": "ペン", "offers": {"price": 300, "priceCurrency": "JPY"}}))
        self.assertEqual(np_.extract_from_page(html)["name"], "ペン")

    def test_falls_back_to_open_graph(self):
        meta = ('<meta property="og:title" content="トートバッグ">'
                '<meta property="product:price:amount" content="3,980">'
                '<meta property="product:price:currency" content="JPY">')
        info = np_.extract_from_page(page(meta=meta, title="ショップ名"))
        self.assertEqual(info["name"], "トートバッグ")
        self.assertEqual(info["price"], 3980)

    def test_nothing_found(self):
        info = np_.extract_from_page("<html><head><title> 何かのページ </title></head></html>")
        self.assertEqual(info["name"], "何かのページ")
        self.assertIsNone(info["price"])

    def test_zero_and_nan_prices_are_ignored(self):
        info = np_.extract_from_page(page({"@type": "Product", "name": "x",
                                           "offers": [{"price": 0}, {"price": "NaN"}]}))
        self.assertIsNone(info["price"])


class PriceTest(unittest.TestCase):
    def test_round_up(self):
        cases = {2500: 3000, 2400: 3000, 3000: 3000, 12800: 13000, 1000: 1000, 1001: 2000,
                 350: 400, 300: 300, 999: 1000, 1: 100, 98000: 98000}
        for real, shop in cases.items():
            self.assertEqual(np_.round_up_price(real), shop, real)


class BuildTest(unittest.TestCase):
    def info(self, **over):
        d = {"name": "ペン", "price": 2480, "currency": "JPY", "imageUrl": None,
             "externalUrl": "https://shift-mall.com/p"}
        d.update(over)
        return d

    def test_build(self):
        p = np_.build_product(self.info(), "p022", "文房具", "🖊️")
        self.assertEqual(p, {"id": "p022", "name": "ペン", "category": "文房具", "price": 3000,
                             "emoji": "🖊️", "externalUrl": "https://shift-mall.com/p"})
        self.assertNotIn("originalPrice", p)
        self.assertNotIn("badge", p)

    def test_missing_name_or_price(self):
        with self.assertRaises(ValueError):
            np_.build_product(self.info(name=None), "p022", "c", "e")
        with self.assertRaises(ValueError):
            np_.build_product(self.info(price=None), "p022", "c", "e")

    def test_non_jpy_is_rejected(self):
        with self.assertRaises(ValueError):
            np_.build_product(self.info(currency="usd"), "p022", "c", "e")

    def test_missing_currency_is_treated_as_jpy(self):
        self.assertEqual(np_.build_product(self.info(currency=None), "p022", "c", "e")["price"], 3000)

    def test_next_id(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(np_.next_product_id(d), "p001")
            for name in ("p001.json", "p021.json", "x.json", "p9a.json"):
                (Path(d) / name).write_text("{}", encoding="utf-8")
            self.assertEqual(np_.next_product_id(d), "p022")


class MainTest(unittest.TestCase):
    def test_disallowed_host_stops_before_fetch(self):
        self.assertEqual(np_.main(["https://example.com/item", "--category", "c", "--emoji", "e",
                                   "--dry-run"]), 1)


if __name__ == "__main__":
    unittest.main()
