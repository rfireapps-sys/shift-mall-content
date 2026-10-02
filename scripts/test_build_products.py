import json
import tempfile
import unittest
from pathlib import Path

import build_products as bp


def ok(**over):
    p = {"id": "p001", "name": "テスト", "category": "家電", "price": 1000, "emoji": "🎧"}
    p.update(over)
    return p


class ValidateTest(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(bp.validate_product(ok(), "p001"), [])

    def test_valid_with_optionals(self):
        p = ok(originalPrice=1500, badge="SALE", soldCount=3, description="説明",
               imageUrl="assets/products/p001.png", externalUrl="https://example.com/x")
        self.assertEqual(bp.validate_product(p, "p001"), [])

    def test_valid_nulls(self):
        self.assertEqual(bp.validate_product(ok(originalPrice=None, soldCount=None, badge=None), "p001"), [])

    def test_missing_required(self):
        for key in ("id", "name", "category", "price"):
            p = ok(); del p[key]
            self.assertTrue(bp.validate_product(p, "p001"), key)

    def test_price_must_be_positive_finite_number(self):
        for bad in (0, -1, "100", None, True, float("nan"), float("inf")):
            self.assertTrue(bp.validate_product(ok(price=bad), "p001"), repr(bad))

    def test_id_must_match_filename(self):
        self.assertTrue(bp.validate_product(ok(id="p002"), "p001"))

    def test_id_charset(self):
        self.assertTrue(bp.validate_product(ok(id="商品"), "商品"))

    def test_unknown_key_is_error(self):
        self.assertTrue(bp.validate_product(ok(prise=1), "p001"))

    def test_original_price_must_exceed_price(self):
        self.assertTrue(bp.validate_product(ok(originalPrice=1000), "p001"))
        self.assertTrue(bp.validate_product(ok(originalPrice=500), "p001"))

    def test_sold_count(self):
        for bad in (-1, 1.5, "3", True):
            self.assertTrue(bp.validate_product(ok(soldCount=bad), "p001"), repr(bad))

    def test_urls(self):
        self.assertTrue(bp.validate_product(ok(externalUrl="javascript:alert(1)"), "p001"))
        self.assertTrue(bp.validate_product(ok(externalUrl="http://example.com"), "p001"))
        self.assertTrue(bp.validate_product(ok(imageUrl="http://example.com/a.png"), "p001"))
        self.assertTrue(bp.validate_product(ok(imageUrl="file:///etc/passwd"), "p001"))

    def test_not_an_object(self):
        self.assertTrue(bp.validate_product([1, 2], "p001"))


class LoadTest(unittest.TestCase):
    def write(self, d, name, text):
        (Path(d) / name).write_text(text, encoding="utf-8")

    def test_order_is_by_filename(self):
        with tempfile.TemporaryDirectory() as d:
            self.write(d, "p002.json", json.dumps(ok(id="p002")))
            self.write(d, "p001.json", json.dumps(ok(id="p001")))
            products, errors = bp.load_products(d)
            self.assertEqual(errors, [])
            self.assertEqual([p["id"] for p in products], ["p001", "p002"])

    def test_empty_dir_is_error(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(bp.load_products(d)[1])

    def test_broken_json_is_error(self):
        with tempfile.TemporaryDirectory() as d:
            self.write(d, "p001.json", "{ not json")
            self.assertTrue(bp.load_products(d)[1])

    def test_nan_literal_is_error(self):
        with tempfile.TemporaryDirectory() as d:
            self.write(d, "p001.json", '{"id":"p001","name":"a","category":"b","price":NaN}')
            self.assertTrue(bp.load_products(d)[1])

    def test_one_bad_file_blocks_everything_via_errors(self):
        with tempfile.TemporaryDirectory() as d:
            self.write(d, "p001.json", json.dumps(ok()))
            self.write(d, "p002.json", json.dumps(ok(id="p002", price=0)))
            products, errors = bp.load_products(d)
            self.assertEqual(len(errors), 1)
            self.assertIn("p002.json", errors[0])

    def test_render_is_deterministic_and_keeps_japanese(self):
        text = bp.render([ok()])
        self.assertEqual(text, bp.render([ok()]))
        self.assertIn("テスト", text)
        self.assertTrue(text.endswith("\n"))
        self.assertEqual(json.loads(text), {"products": [ok()]})


if __name__ == "__main__":
    unittest.main()
