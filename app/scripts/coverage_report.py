"""One-shot coverage report for Buyers/SnowDogg product enrichment."""
from __future__ import annotations
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import select, func, or_
from app.database import async_session, engine
engine.echo = False
engine.sync_engine.echo = False
from app.models import (
    Brand, Product, ProductImage, ProductAttribute,
    ProductDescription, ProductFitment, ProductResource,
)


async def report():
    async with async_session() as db:
        brand_filter = or_(Brand.name.ilike("%buyers%"), Brand.name.ilike("%snowdogg%"))

        # Totals
        total = (await db.execute(
            select(func.count(Product.id)).join(Brand)
            .where(brand_filter, Product.is_for_sale.is_(True))
        )).scalar()
        visible = (await db.execute(
            select(func.count(Product.id)).join(Brand)
            .where(brand_filter, Product.is_for_sale.is_(True), Product.is_hidden.is_(False))
        )).scalar()
        hidden = total - visible

        # Coverage: products with at least 1 row in each table
        has_img = (await db.execute(
            select(func.count(func.distinct(ProductImage.product_id)))
            .join(Product).join(Brand).where(brand_filter)
        )).scalar()
        has_attr = (await db.execute(
            select(func.count(func.distinct(ProductAttribute.product_id)))
            .join(Product).join(Brand).where(brand_filter)
        )).scalar()
        has_fit = (await db.execute(
            select(func.count(func.distinct(ProductFitment.product_id)))
            .join(Product).join(Brand).where(brand_filter)
        )).scalar()
        has_fea = (await db.execute(
            select(func.count(func.distinct(ProductDescription.product_id)))
            .join(Product).join(Brand).where(brand_filter)
            .where(ProductDescription.description_code == "FEA")
        )).scalar()
        has_ext = (await db.execute(
            select(func.count(Product.id)).join(Brand)
            .where(brand_filter, Product.is_for_sale.is_(True),
                   Product.extended_description.isnot(None),
                   func.length(Product.extended_description) > 50)
        )).scalar()
        has_res = (await db.execute(
            select(func.count(func.distinct(ProductResource.product_id)))
            .join(Product).join(Brand).where(brand_filter)
        )).scalar()

        # Row counts
        img_rows = (await db.execute(
            select(func.count(ProductImage.id)).join(Product).join(Brand).where(brand_filter)
        )).scalar()
        attr_rows = (await db.execute(
            select(func.count(ProductAttribute.id)).join(Product).join(Brand).where(brand_filter)
        )).scalar()
        fit_rows = (await db.execute(
            select(func.count(ProductFitment.id)).join(Product).join(Brand).where(brand_filter)
        )).scalar()
        desc_rows = (await db.execute(
            select(func.count(ProductDescription.id)).join(Product).join(Brand).where(brand_filter)
        )).scalar()
        res_rows = (await db.execute(
            select(func.count(ProductResource.id)).join(Product).join(Brand).where(brand_filter)
        )).scalar()

        # "Storefront-ready" = has image AND (has attrs OR has features)
        # Using subqueries
        from sqlalchemy import exists
        img_exists = select(ProductImage.id).where(ProductImage.product_id == Product.id).exists()
        attr_exists = select(ProductAttribute.id).where(ProductAttribute.product_id == Product.id).exists()
        fea_exists = select(ProductDescription.id).where(
            ProductDescription.product_id == Product.id,
            ProductDescription.description_code == "FEA"
        ).exists()
        ready = (await db.execute(
            select(func.count(Product.id)).join(Brand)
            .where(brand_filter, Product.is_for_sale.is_(True),
                   img_exists, or_(attr_exists, fea_exists))
        )).scalar()

        # Row counts
        img_rows = (await db.execute(
            select(func.count(ProductImage.id)).join(Product).join(Brand).where(brand_filter)
        )).scalar()
        attr_rows = (await db.execute(
            select(func.count(ProductAttribute.id)).join(Product).join(Brand).where(brand_filter)
        )).scalar()
        fit_rows = (await db.execute(
            select(func.count(ProductFitment.id)).join(Product).join(Brand).where(brand_filter)
        )).scalar()
        desc_rows_total = (await db.execute(
            select(func.count(ProductDescription.id)).join(Product).join(Brand).where(brand_filter)
        )).scalar()
        res_rows = (await db.execute(
            select(func.count(ProductResource.id)).join(Product).join(Brand).where(brand_filter)
        )).scalar()

        print("=" * 60)
        print("BUYERS / SNOWDOGG CATALOG COVERAGE REPORT")
        print("=" * 60)
        print()
        print(f"Total products:       {total:>6}")
        print(f"  Visible:            {visible:>6}")
        print(f"  Hidden:             {hidden:>6}")
        print()
        print(f"TOTAL ROWS IN DB:")
        print(f"  ProductImage:       {img_rows:>6}")
        print(f"  ProductAttribute:   {attr_rows:>6}")
        print(f"  ProductFitment:     {fit_rows:>6}")
        print(f"  ProductDescription: {desc_rows_total:>6}")
        print(f"  ProductResource:    {res_rows:>6}")
        print()

        # Split report: visible vs hidden
        from sqlalchemy import exists as sa_exists
        for label, hfilter in [("VISIBLE", Product.is_hidden.is_(False)),
                                ("HIDDEN", Product.is_hidden.is_(True))]:
            t = (await db.execute(
                select(func.count(Product.id)).join(Brand)
                .where(brand_filter, Product.is_for_sale.is_(True), hfilter)
            )).scalar()
            if t == 0:
                continue

            img_sub = sa_exists(select(ProductImage.id).where(ProductImage.product_id == Product.id))
            attr_sub = sa_exists(select(ProductAttribute.id).where(ProductAttribute.product_id == Product.id))
            fit_sub = sa_exists(select(ProductFitment.id).where(ProductFitment.product_id == Product.id))
            fea_sub = sa_exists(select(ProductDescription.id).where(
                ProductDescription.product_id == Product.id,
                ProductDescription.description_code == "FEA"))
            base = select(func.count(Product.id)).join(Brand).where(
                brand_filter, Product.is_for_sale.is_(True), hfilter)

            hi = (await db.execute(base.where(img_sub))).scalar()
            ha = (await db.execute(base.where(attr_sub))).scalar()
            hf = (await db.execute(base.where(fit_sub))).scalar()
            hd = (await db.execute(base.where(fea_sub))).scalar()
            he = (await db.execute(
                base.where(Product.extended_description.isnot(None),
                           func.length(Product.extended_description) > 50)
            )).scalar()
            hr = (await db.execute(base.where(
                sa_exists(select(ProductResource.id).where(ProductResource.product_id == Product.id))
            ))).scalar()
            rdy = (await db.execute(base.where(img_sub, or_(attr_sub, fea_sub)))).scalar()

            print(f"--- {label} PRODUCTS ({t}) ---")
            print(f"  Image:              {hi:>5} / {t:<5}  ({hi/t*100:>5.1f}%)")
            print(f"  Specs (attributes): {ha:>5} / {t:<5}  ({ha/t*100:>5.1f}%)")
            print(f"  Fitment (YMM):      {hf:>5} / {t:<5}  ({hf/t*100:>5.1f}%)")
            print(f"  Features (FEA):     {hd:>5} / {t:<5}  ({hd/t*100:>5.1f}%)")
            print(f"  Ext description:    {he:>5} / {t:<5}  ({he/t*100:>5.1f}%)")
            print(f"  PDF / video:        {hr:>5} / {t:<5}  ({hr/t*100:>5.1f}%)")
            print(f"  STOREFRONT-READY*:  {rdy:>5} / {t:<5}  ({rdy/t*100:>5.1f}%)")
            print()

        print("* Storefront-ready = has image AND (has specs OR has features)")

        # Gap analysis for visible products
        from sqlalchemy import exists as sa_exists2
        no_img = ~sa_exists2(select(ProductImage.id).where(ProductImage.product_id == Product.id))
        no_attr = ~sa_exists2(select(ProductAttribute.id).where(ProductAttribute.product_id == Product.id))
        vis_base = select(Product.sku, Product.name).join(Brand).where(
            brand_filter, Product.is_for_sale.is_(True), Product.is_hidden.is_(False))

        # Counts
        ni = (await db.execute(
            select(func.count(Product.id)).join(Brand).where(
                brand_filter, Product.is_for_sale.is_(True), Product.is_hidden.is_(False), no_img)
        )).scalar()
        hi_na = (await db.execute(
            select(func.count(Product.id)).join(Brand).where(
                brand_filter, Product.is_for_sale.is_(True), Product.is_hidden.is_(False), ~no_img, no_attr)
        )).scalar()

        print()
        print("--- GAP ANALYSIS (visible only) ---")
        print(f"  Missing image:              {ni}")
        print(f"  Has image, missing specs:   {hi_na}")
        print()
        print("  Sample visible products WITHOUT image:")
        rows = (await db.execute(vis_base.where(no_img).limit(15))).all()
        for sku, name in rows:
            short = (name or "")[:55]
            print(f"    {sku:<20s} {short}")

        print()
        print("  Sample visible products WITH image but NO specs:")
        rows2 = (await db.execute(vis_base.where(~no_img, no_attr).limit(15))).all()
        for sku, name in rows2:
            short = (name or "")[:55]
            print(f"    {sku:<20s} {short}")

asyncio.run(report())
