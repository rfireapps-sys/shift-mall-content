#!/usr/bin/env python3
"""商品ページのURLから、products/ に置く商品ファイル(1商品=1ファイル)を作る。

使い方:
    python3 scripts/new_product.py <商品ページのURL> --category 家電 --emoji 🎧 [--dry-run]

- 商品名と価格は、ページに埋め込まれた商品情報(schema.org Product の JSON-LD)から読む。
  無ければ Open Graph(og:title、product:price:amount)から読む。どちらも無い項目は
  --name / --price で手で渡す。
- 価格は実際より少し高めに丸める(1000円以上は1000円単位、1000円未満は100円単位で切り上げ)。
  実在の商品なので、SALE のバッジと元の価格(originalPrice)は付けない。
- 画像はページから取らない(販売サイトの画像を勝手に使わないため)。絵文字で出す。
  ASP と提携して画像の利用が許された商品だけ、あとから imageUrl を足す。
- 説明文もページから写さない(他人の文章をそのまま載せないため)。必要なら --description で書く。
- URLの行き先は allowed_hosts.txt にあるものだけ受け付ける(公開時の検査と同じ判定)。
- 書いたあと、build_products.py と同じ検査にかけて、通らなければファイルを消して止まる。

あとから取り方を足すとき(バリューコマースの商品APIなど)は、`extract_*` と同じ形の
辞書(name / price / currency / imageUrl / externalUrl。分からない項目は None)を返す関数を書き、
main() の取り方の分岐に足す。build_product() 以降はそのまま使える。
標準ライブラリだけで動く(Python 3.9 以上)。
"""
import argparse
import html.parser
import json
import math
import re
import sys
import urllib.request
from pathlib import Path

import build_products as bp

ROOT = bp.ROOT
MAX_BYTES = 5 * 1024 * 1024
USER_AGENT = "Mozilla/5.0 (compatible; shift-mall-content/new_product.py)"


# ===== ページを読む =====

class _HeadParser(html.parser.HTMLParser):
    """JSON-LD の中身と、<meta property/name> と <title> を拾う。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.jsonld = []
        self.meta = {}
        self.title = ""
        self._in_jsonld = False
        self._in_title = False
        self._buf = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script" and (a.get("type") or "").strip().lower() == "application/ld+json":
            self._in_jsonld, self._buf = True, []
        elif tag == "meta":
            key = (a.get("property") or a.get("name") or "").strip().lower()
            if key and a.get("content") is not None and key not in self.meta:
                self.meta[key] = a["content"].strip()
        elif tag == "title" and not self.title:
            self._in_title, self._buf = True, []

    def handle_endtag(self, tag):
        if tag == "script" and self._in_jsonld:
            self.jsonld.append("".join(self._buf))
            self._in_jsonld = False
        elif tag == "title" and self._in_title:
            self.title = re.sub(r"\s+", " ", "".join(self._buf)).strip()
            self._in_title = False

    def handle_data(self, data):
        if self._in_jsonld or self._in_title:
            self._buf.append(data)


def _walk_jsonld(node):
    """JSON-LD の木(リスト・@graph の入れ子)から、辞書を全部たどる。"""
    if isinstance(node, list):
        for x in node:
            yield from _walk_jsonld(x)
    elif isinstance(node, dict):
        yield node
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in node:
                yield from _walk_jsonld(node[key])


def _is_product(d):
    t = d.get("@type")
    types = t if isinstance(t, list) else [t]
    return any(isinstance(x, str) and x.split("/")[-1] in ("Product", "ProductGroup") for x in types)


def _to_number(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else None
    if isinstance(v, str):
        s = v.strip().replace(",", "").replace("￥", "").replace("¥", "").replace("円", "")
        try:
            f = float(s)
        except ValueError:
            return None
        return f if math.isfinite(f) else None
    return None


def _offer_price(offers):
    """offers(Offer / AggregateOffer / そのリスト)から (価格, 通貨) を返す。一番安いものを取る。"""
    found = []
    for o in _walk_jsonld(offers):
        cur = o.get("priceCurrency")
        price = o.get("price")
        if price is None and isinstance(o.get("priceSpecification"), dict):
            price = o["priceSpecification"].get("price")
            cur = cur or o["priceSpecification"].get("priceCurrency")
        if price is None:
            price = o.get("lowPrice")
        n = _to_number(price)
        if n is not None and n > 0:
            found.append((n, cur))
    if not found:
        return None, None
    return min(found, key=lambda x: x[0])


def extract_from_page(page_html):
    """商品ページのHTMLから {name, price, currency, imageUrl, externalUrl} を返す(分からない項目は None)。

    画像と説明文は取らない(モジュールの説明を参照)。
    """
    p = _HeadParser()
    p.feed(page_html)
    name = price = currency = None
    for raw in p.jsonld:
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        for d in _walk_jsonld(data):
            if not _is_product(d):
                continue
            if name is None and isinstance(d.get("name"), str) and d["name"].strip():
                name = d["name"].strip()
            if price is None and "offers" in d:
                price, currency = _offer_price(d["offers"])
            if name is not None and price is not None:
                break
    if name is None:
        name = p.meta.get("og:title") or p.title or None
    if price is None:
        price = _to_number(p.meta.get("product:price:amount") or p.meta.get("og:price:amount"))
        currency = p.meta.get("product:price:currency") or p.meta.get("og:price:currency")
    return {"name": name, "price": price, "currency": currency, "imageUrl": None, "externalUrl": None}


def fetch_html(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "ja"})
    with urllib.request.urlopen(req, timeout=20) as res:
        body = res.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise ValueError("ページが大きすぎます(%dMB超)" % (MAX_BYTES // 1024 // 1024))
        charset = res.headers.get_content_charset() or "utf-8"
    return body.decode(charset, errors="replace")


# ===== 商品ファイルを作る =====

def round_up_price(real_price):
    """実際の価格を少し高めに丸める。1000円以上は1000円単位、1000円未満は100円単位で切り上げ。"""
    step = 1000 if real_price >= 1000 else 100
    return int(math.ceil(real_price / step) * step)


def next_product_id(products_dir):
    nums = [int(m.group(1)) for f in Path(products_dir).glob("p*.json")
            if (m := re.fullmatch(r"p(\d+)", f.stem))]
    return "p%03d" % (max(nums, default=0) + 1)


def build_product(info, pid, category, emoji, description=None):
    """取り出した情報から商品ファイルの中身を作る。足りない項目は ValueError。"""
    if not info.get("name"):
        raise ValueError("商品名が取れませんでした。--name で渡してください")
    if info.get("price") is None:
        raise ValueError("価格が取れませんでした。--price で実際の価格を渡してください")
    cur = (info.get("currency") or "JPY").upper()
    if cur != "JPY":
        raise ValueError("価格が円ではありません(%s)。--price で円の価格を渡してください" % cur)
    product = {
        "id": pid,
        "name": info["name"],
        "category": category,
        "price": round_up_price(info["price"]),
        "emoji": emoji,
    }
    if description:
        product["description"] = description
    if info.get("imageUrl"):
        product["imageUrl"] = info["imageUrl"]
    if info.get("externalUrl"):
        product["externalUrl"] = info["externalUrl"]
    return product


def main(argv=None):
    ap = argparse.ArgumentParser(description="商品ページのURLから products/ の商品ファイルを作る")
    ap.add_argument("url", help="商品ページのURL(https://)")
    ap.add_argument("--category", required=True, help="ショップのカテゴリ(例: 家電)")
    ap.add_argument("--emoji", required=True, help="画像が無いときに出す絵文字")
    ap.add_argument("--name", help="商品名を手で渡す(ページから取れないとき)")
    ap.add_argument("--price", type=float, help="実際の価格(円)を手で渡す(ページから取れないとき)")
    ap.add_argument("--description", help="説明文(ページから写さず、自分で書く)")
    ap.add_argument("--id", help="商品ID(省くと次の空き番号)")
    ap.add_argument("--dry-run", action="store_true", help="ファイルを書かずに中身だけ表示する")
    args = ap.parse_args(argv)

    hosts = bp.load_allowed_hosts(ROOT / "allowed_hosts.txt")
    if not args.url.startswith("https://") or not bp.host_allowed(args.url, hosts):
        print("このURLの行き先は allowed_hosts.txt にありません。先に1行足してください: %s" % args.url,
              file=sys.stderr)
        return 1

    # 取り方の分岐。バリューコマースの商品APIなどを足すときは、ここに分岐を足す。
    try:
        info = extract_from_page(fetch_html(args.url))
    except Exception as e:  # 通信・文字コードの失敗は、手で渡す道を案内する
        print("ページを読めませんでした(%s)。--name と --price で手で渡せます" % e, file=sys.stderr)
        info = {"name": None, "price": None, "currency": None, "imageUrl": None, "externalUrl": None}
    if args.name:
        info["name"] = args.name
    if args.price is not None:
        info["price"], info["currency"] = args.price, "JPY"
    info["externalUrl"] = info.get("externalUrl") or args.url

    products_dir = ROOT / "products"
    pid = args.id or next_product_id(products_dir)
    try:
        product = build_product(info, pid, args.category, args.emoji, args.description)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    errors = bp.validate_product(product, pid, hosts)
    if errors:
        for e in errors:
            print("  - " + e, file=sys.stderr)
        return 1

    text = json.dumps(product, ensure_ascii=False, indent=2) + "\n"
    print("実際の価格: %s円 → ショップの価格: %d円" % (format(info["price"], ",.0f"), product["price"]))
    if args.dry_run:
        print(text, end="")
        return 0
    out = products_dir / ("%s.json" % pid)
    if out.exists():
        print("%s はもうあります。--id で別の番号を渡してください" % out.name, file=sys.stderr)
        return 1
    out.write_text(text, encoding="utf-8")
    print("%s を作りました" % out.relative_to(ROOT))
    print(text, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
