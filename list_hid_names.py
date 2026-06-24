import hid

for d in hid.enumerate():
    name = d.get("product_string") or ""
    manufacturer = d.get("manufacturer_string") or ""

    if name or manufacturer:
        print(f"{manufacturer} | {name}")
        print(f"  vendor_id={d.get('vendor_id')}")
        print(f"  product_id={d.get('product_id')}")
        print(f"  path={d.get('path')}")
        print()
