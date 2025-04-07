"""Background jobs for Shopify integration."""

import frappe
from frappe import _
from frappe.utils import cint

from ecommerce_integrations.shopify.constants import SETTING_DOCTYPE
from ecommerce_integrations.shopify.product_class import ShopifyProduct


def enqueue_bulk_product_import():
    """Enqueue bulk product import job with 10-day timeout"""
    setting = frappe.get_doc(SETTING_DOCTYPE)

    if not setting.is_enabled():
        frappe.throw(_("Shopify integration is not enabled"))

    if not setting.enable_bulk_import:
        frappe.throw(_("Bulk import is not enabled"))

    try:
        frappe.enqueue(
            method=ShopifyProduct.import_products_bulk,
            queue="long",
            timeout=864000,  # 10 days in seconds
            job_name="shopify_bulk_product_import",
            enqueue_after_commit=True,
        )

        frappe.msgprint(
            _(
                "Bulk product import has been queued. It may take up to 10 days to complete."
            )
        )

    except Exception as e:
        frappe.log_error(
            title="Shopify Bulk Import Error",
            message=f"Failed to enqueue bulk import: {str(e)}",
        )
        frappe.throw(_("Failed to enqueue bulk import: {0}").format(str(e)))
