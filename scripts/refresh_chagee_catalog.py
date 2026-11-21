"""Refresh the published mainland menu and same-base sweetness variants from the brand calculator."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from time import sleep

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tea_chagee import METRICS, SOURCE, read_recipe  # noqa: E402


def public_data(client, method, **body):
    response = client.post(SOURCE + "api/product/" + method, json=body)
    response.raise_for_status()
    result = response.json()
    if str(result.get("code")) != "1000":
        raise ValueError(f"Brand service did not return {method}")
    return result["data"]


def menu_names(client, category):
    names = []
    page = 1
    while True:
        data = public_data(client, "productTypeList", productType=category, productName="", current=page)
        names.extend(item["productName"] for item in data["records"] if item["productType"] == category)
        if page >= data["pages"]:
            break
        page += 1
    if len(names) != data["total"] or len(set(names)) != len(names):
        raise ValueError(f"Incomplete menu for {category}")
    return names


def product_data(client, name, category):
    product = {"name": name, "category": category, "options": {}, "servings": []}
    default = read_recipe(client, name)
    if default is None:
        return product
    options = product["options"] = default["chagee_options"]
    recipe = default["chagee_recipe"]
    rows = [default]
    for sugar in options.get("sugar", []):
        if sugar != recipe["sugar"]:
            sleep(0.08)
            row = read_recipe(client, name, {**recipe, "sugar": sugar}, options=options)
            if row:
                rows.append(row)
    for row in rows:
        nutrients = {key: row[key] for key in METRICS if row.get(key) is not None}
        if nutrients or row["grade"]:
            product["servings"].append({
                "recipe": {k: v for k, v in row["chagee_recipe"].items() if v},
                "grade": row["grade"], "nutrients": nutrients,
            })
    return product


def main():
    date = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    products = []
    with httpx.Client(timeout=20, transport=httpx.HTTPTransport(retries=2)) as client:
        for item in public_data(client, "listTypeAll"):
            category = item["typeName"]
            names = menu_names(client, category)
            print(category, len(names), flush=True)
            for name in names:
                products.append(product_data(client, name, category))
                sleep(0.08)
    if not products or not any(p["servings"] for p in products):
        raise ValueError("No verified recipes returned")
    dest = ROOT / "tea_data" / "chagee_menu.json"
    dest.parent.mkdir(exist_ok=True)
    temp = dest.with_suffix(".tmp")
    rows = ",\n".join(json.dumps(p, ensure_ascii=False, separators=(",", ":")) for p in products)
    temp.write_text('{"date":"' + date + '","products":[\n' + rows + '\n]}\n', encoding="utf-8")
    temp.replace(dest)
    print(len(products), "products,", sum(len(p["servings"]) for p in products), "published servings")


if __name__ == "__main__":
    main()
