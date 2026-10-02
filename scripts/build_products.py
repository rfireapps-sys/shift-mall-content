#!/usr/bin/env python3
"""products/*.json(1商品=1ファイル)を検査して、アプリが読む products.json に束ねる。

- 検査に1つでも失敗したら、products.json は書き換えず、終了コード1で止まる(公開されない)。
- 並び順は「ファイル名の昇順」。アプリのカテゴリの並びは、商品の並びで最初に出てきた順になる。
- 標準ライブラリだけで動く。
"""
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWED_KEYS = {
    "id", "name", "category", "price", "originalPrice", "emoji",
    "imageUrl", "badge", "soldCount", "description", "externalUrl",
}
REQUIRED_STR_KEYS = ("id", "name", "category")
OPTIONAL_STR_KEYS = ("emoji", "imageUrl", "badge", "description", "externalUrl")
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def validate_product(data, stem):
    """1商品の検査。エラーメッセージのリストを返す(空なら合格)。"""
    if not isinstance(data, dict):
        return ["商品は { ... } の形(オブジェクト)で書いてください"]
    errors = []
    for key in sorted(set(data) - ALLOWED_KEYS):
        errors.append("知らない項目 '%s' があります(綴りの間違いかもしれません)" % key)
    for key in REQUIRED_STR_KEYS:
        v = data.get(key)
        if not isinstance(v, str) or not v.strip():
            errors.append("'%s' は必須です(空でない文字列)" % key)
    pid = data.get("id")
    if isinstance(pid, str) and pid.strip():
        if not ID_PATTERN.match(pid):
            errors.append("'id' は英数字と - _ だけにしてください: %r" % pid)
        elif pid != stem:
            errors.append("'id' (%s) とファイル名 (%s.json) を同じにしてください" % (pid, stem))
    price = data.get("price")
    if not _is_number(price) or price <= 0:
        errors.append("'price' は0より大きい数値にしてください: %r" % (price,))
    if "originalPrice" in data and data["originalPrice"] is not None:
        op = data["originalPrice"]
        if not _is_number(op) or op <= 0:
            errors.append("'originalPrice' は0より大きい数値か null にしてください: %r" % (op,))
        elif _is_number(price) and op <= price:
            errors.append("'originalPrice' (%s) は 'price' (%s) より大きくしてください" % (op, price))
    if "soldCount" in data and data["soldCount"] is not None:
        sc = data["soldCount"]
        if isinstance(sc, bool) or not isinstance(sc, int) or sc < 0:
            errors.append("'soldCount' は0以上の整数か null にしてください: %r" % (sc,))
    for key in OPTIONAL_STR_KEYS:
        if key in data and data[key] is not None and not isinstance(data[key], str):
            errors.append("'%s' は文字列にしてください: %r" % (key, data[key]))
    ext = data.get("externalUrl")
    if isinstance(ext, str) and ext and not ext.startswith("https://"):
        errors.append("'externalUrl' は https:// で始めてください: %r" % ext)
    img = data.get("imageUrl")
    if isinstance(img, str) and img and not (img.startswith("https://") or img.startswith("assets/")):
        errors.append("'imageUrl' は https:// か assets/ (アプリ同梱の画像) で始めてください: %r" % img)
    return errors


def load_products(products_dir):
    """products_dir のJSONを読んで (商品のリスト, エラーのリスト) を返す。"""
    products, errors = [], []
    files = sorted(Path(products_dir).glob("*.json"))
    if not files:
        errors.append("%s に商品のファイルが1つもありません(全商品が消えてしまうので公開しません)" % products_dir)
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            errors.append("%s: JSONとして読めません: %s" % (f.name, e))
            continue
        errs = validate_product(data, f.stem)
        errors.extend("%s: %s" % (f.name, e) for e in errs)
        if not errs:
            products.append(data)
    return products, errors


def render(products):
    return json.dumps({"products": products}, ensure_ascii=False, indent=2) + "\n"


def main(argv):
    products, errors = load_products(ROOT / "products")
    if errors:
        print("検査に失敗しました。products.json は更新しません。", file=sys.stderr)
        for e in errors:
            print("  - " + e, file=sys.stderr)
        return 1
    out = ROOT / "products.json"
    text = render(products)
    if out.exists() and out.read_text(encoding="utf-8") == text:
        print("products.json は最新です(%d件)" % len(products))
    else:
        out.write_text(text, encoding="utf-8")
        print("products.json を更新しました(%d件)" % len(products))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
