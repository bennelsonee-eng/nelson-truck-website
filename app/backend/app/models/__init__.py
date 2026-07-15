"""SQLAlchemy models for the Titan Truck website.

All models are imported here so Alembic's autogenerate sees them.
"""

from app.models.base import Base
from app.models.catalog import (
    Brand,
    Category,
    CTAMode,
    GroupRequirement,
    Product,
    ProductCategory,
    ProductFitment,
    ProductImage,
)
from app.models.warehouse import ProductInventory, Warehouse
from app.models.pricing import Contract, ProductPrice
from app.models.customer import AddressType, Customer, CustomerAddress, CustomerTier
from app.models.cart import Cart, CartLine, CartLineSource
from app.models.order import (
    FACSPushStatus,
    Order,
    OrderFulfillment,
    OrderLine,
    OrderStatus,
    PaymentType,
    QuoteIntent,
)
from app.models.auth import User, UserRole
from app.models.audit import AuditLog
from app.models.banner import BannerAudience, BannerSlide
from app.models.build_idea import BuildIdea
from app.models.showroom_receipt import ShowroomReceipt
from app.models.deals import DealAudience, DealCollection, DealItem, DealItemKind
from app.models.rebate import RebateAudience, RebateClaimMethod, RebateProgram, RebateType
from app.models.rma import RmaLine, RmaReason, RmaRequest, RmaStatus
from app.models.customer_link_request import (
    CustomerLinkRequest,
    CustomerLinkRequestStatus,
)
from app.models.customer_signals import (
    BackInStockAlert,
    LostSale,
    LostSaleReason,
    PriceMatchRequest,
    PriceMatchStatus,
)
from app.models.weather_alert import WeatherAlertSubscriber
from app.models.product_match import ProductMatch, ProductMatchStatus, ProductMatchSource
from app.models.product_resource import ProductResource, ResourceKind
from app.models.kit import Kit, KitComponent
from app.models.truck_render import TruckRenderRequest, TruckRenderStatus
from app.models.pace_catalog import (
    VcdbMake,
    VcdbModel,
    VcdbBaseVehicle,
    VcdbSubModel,
    VcdbBedLength,
    VcdbBedType,
    VcdbBodyType,
    VcdbDriveType,
    VcdbEngineBase,
    VcdbFuelType,
    VcdbAspiration,
    VcdbRegion,
    PcdbPartType,
    PcdbPosition,
    PacePart,
    PaceFitment,
    ProductAttribute,
    ProductDescription,
    ProductPackage,
    ProductPricing,
    AttributeValueAlias,
    AttributeKeyReview,
    AttributeKeyAlias,
    AttributeValueDecomposition,
)

__all__ = [
    # Base
    "Base",
    # Catalog
    "Brand",
    "Category",
    "CTAMode",
    "GroupRequirement",
    "Product",
    "ProductCategory",
    "ProductFitment",
    "ProductImage",
    # Warehouse
    "ProductInventory",
    "Warehouse",
    # Pricing
    "Contract",
    "ProductPrice",
    # Customer
    "AddressType",
    "Customer",
    "CustomerAddress",
    "CustomerTier",
    # Cart
    "Cart",
    "CartLine",
    "CartLineSource",
    # Order
    "FACSPushStatus",
    "Order",
    "OrderFulfillment",
    "OrderLine",
    "OrderStatus",
    "PaymentType",
    "QuoteIntent",
    # Auth
    "User",
    "UserRole",
    # Audit
    "AuditLog",
    "ShowroomReceipt",
    # Banner CMS (homepage ad banner, audience-scoped)
    "BannerAudience",
    "BannerSlide",
    # Build Ideas (admin future-build backlog)
    "BuildIdea",
    # Deals layer (Deal Warehouse homepage)
    "DealAudience",
    "DealCollection",
    "DealItem",
    "DealItemKind",
    # Rebate engine (audience-scoped programs)
    "RebateAudience",
    "RebateClaimMethod",
    "RebateProgram",
    "RebateType",
    # RMA (A4.31)
    "RmaLine",
    "RmaReason",
    "RmaRequest",
    "RmaStatus",
    # Customer link requests (email-gated User → Customer linkage)
    "CustomerLinkRequest",
    "CustomerLinkRequestStatus",
    # Customer signals
    "BackInStockAlert",
    "LostSale",
    "LostSaleReason",
    "PriceMatchRequest",
    "PriceMatchStatus",
    # Weather alerts
    "WeatherAlertSubscriber",
    # Reseller finder (S1)
    "ProductMatch",
    "ProductMatchStatus",
    "ProductMatchSource",
    # Scraped supplementary files (PDFs, videos, manuals, etc.)
    "ProductResource",
    "ResourceKind",
    # Kit / package bill-of-materials (WeatherGuard van packages)
    "Kit",
    "KitComponent",
    # Truck render requests (FLUX Kontext "see it on my truck")
    "TruckRenderRequest",
    "TruckRenderStatus",
    # PACE catalog (ACES vehicle fitment + PIES product info)
    "VcdbMake",
    "VcdbModel",
    "VcdbBaseVehicle",
    "VcdbSubModel",
    "VcdbBedLength",
    "VcdbBedType",
    "VcdbBodyType",
    "VcdbDriveType",
    "VcdbEngineBase",
    "VcdbFuelType",
    "VcdbAspiration",
    "VcdbRegion",
    "PcdbPartType",
    "PcdbPosition",
    "PacePart",
    "PaceFitment",
    "ProductAttribute",
    "ProductDescription",
    "ProductPackage",
    "ProductPricing",
    # PIES attribute value normalization (curated by admin)
    "AttributeValueAlias",
    "AttributeKeyReview",
    "AttributeKeyAlias",
    "AttributeValueDecomposition",
]
