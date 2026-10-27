#!/usr/bin/env python3
"""products/*.json(1商品=1ファイル)を検査して、アプリが読む products.json に束ねる。

- 検査に1つでも失敗したら、products.json は書き換えず、終了コード1で止まる(公開されない)。
- 並び順は「ファイル名の昇順」。アプリのカテゴリの並びは、商品の並びで最初に出てきた順になる。
- imageUrl / externalUrl の https のURLは、allowed_hosts.txt に書いた行き先だけ通す。
- 標準ライブラリだけで動く。
"""
import json
import math
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
ALLOWED_KEYS = {
    "id", "name", "category", "price", "originalPrice", "emoji",
    "imageUrl", "badge", "soldCount", "description", "externalUrl", "hidden",
}
REQUIRED_STR_KEYS = ("id", "name", "category")
OPTIONAL_STR_KEYS = ("emoji", "imageUrl", "badge", "description", "externalUrl")
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def load_allowed_hosts(path):
    """allowed_hosts.txt を読んで、許可する行き先のリストを返す。

    1行に1つ。# から後と空行は無視する。
    - ドメインだけの行(例: shift-mall.com)は、そのドメインとサブドメインを許可する
    - / を含む行(例: raw.githubusercontent.com/rfireapps-sys/shift-mall-content/)は、
      「ドメイン+パス」がその文字列で始まるURLだけを許可する
    """
    entries = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip().lower()
        if line:
            entries.append(line)
    return entries


def host_allowed(url, allowed_hosts):
    """https のURLの行き先が allowed_hosts のどれかに当たるか。"""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if not host:
        return False
    for entry in allowed_hosts:
        if "/" in entry:
            if (host + parts.path).startswith(entry):
                return True
        elif host == entry or host.endswith("." + entry):
            return True
    return False


def validate_product(data, stem, allowed_hosts=None):
    """1商品の検査。エラーメッセージのリストを返す(空なら合格)。

    allowed_hosts が None のときは、URLの行き先を検査しない(単体テスト用)。
    公開用の main() は、必ず allowed_hosts.txt の中身を渡す。
    """
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
    if allowed_hosts is not None:
        for key in ("externalUrl", "imageUrl"):
            url = data.get(key)
            if isinstance(url, str) and url.startswith("https://") and not host_allowed(url, allowed_hosts):
                errors.append("'%s' の行き先が allowed_hosts.txt にありません(足すときは1行追加): %r" % (key, url))
    if "hidden" in data and not isinstance(data["hidden"], bool):
        errors.append("'hidden' は true か false にしてください: %r" % (data["hidden"],))
    return errors


def load_products(products_dir, allowed_hosts=None):
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
        errs = validate_product(data, f.stem, allowed_hosts)
        errors.extend("%s: %s" % (f.name, e) for e in errs)
        if not errs:
            products.append(data)
    if products and all(p.get("hidden") is True for p in products):
        errors.append("全部の商品が hidden です(ショップが空になるので公開しません)")
    return products, errors


def render(products):
    return json.dumps({"products": products}, ensure_ascii=False, indent=2) + "\n"


def main(argv):
    hosts_file = ROOT / "allowed_hosts.txt"
    if not hosts_file.exists():
        print("allowed_hosts.txt がありません。products.json は更新しません。", file=sys.stderr)
        return 1
    products, errors = load_products(ROOT / "products", load_allowed_hosts(hosts_file))
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
