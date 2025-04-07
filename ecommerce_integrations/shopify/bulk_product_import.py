import json
import time
from enum import Enum
from typing import List, Optional, Tuple

import frappe
import requests
from frappe import _
from shopify import GraphQL

from ecommerce_integrations.shopify.connection import temp_shopify_session
from ecommerce_integrations.shopify.constants import SETTING_DOCTYPE
from ecommerce_integrations.shopify.product import ShopifyProduct
from ecommerce_integrations.shopify.utils import create_shopify_log


class BulkOperationStatus(Enum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"
    EXPIRED = "EXPIRED"


class BulkProductImport:
    def __init__(self, poll_interval: int = 30, max_retries: int = 10):
        self.setting = frappe.get_doc(SETTING_DOCTYPE)
        self.poll_interval = poll_interval
        self.max_retries = max_retries

        if not self.setting.is_enabled():
            frappe.throw(_("Shopify integration is not enabled"))

    def _create_bulk_query(self) -> str:
        """Create GraphQL query for bulk product export"""
        return """
        mutation {
            bulkOperationRunQuery(
                query: """
        +json.dumps(
            """
            {
                products {
                    edges {
                        node {
                            id
                            title
                            description
                            productType
                            vendor
                            status
                            tags
                            variants {
                                edges {
                                    node {
                                        id
                                        sku
                                        title
                                        price
                                        compareAtPrice
                                        inventoryQuantity
                                        weight
                                        weightUnit
                                        option1
                                        option2
                                        option3
                                    }
                                }
                            }
                            options {
                                name
                                values
                            }
                            images {
                                edges {
                                    node {
                                        id
                                        src
                                        altText
                                    }
                                }
                            }
                        }
                    }
                }
            }
            """
        ).replace('"', '\\"')
        +"""
            }
        ) {
            bulkOperation {
                id
                status
                url
            }
            userErrors {
                field
                message
            }
        }
    }
    """

    @temp_shopify_session
    def start_bulk_operation(self) -> str:
        """Start a bulk operation to export all products"""
        client = GraphQL()
        response = client.execute(self._create_bulk_query())

        if "errors" in response:
            error_message = "\n".join(error["message"] for error in response["errors"])
            create_shopify_log(
                status="Error",
                message=f"Failed to start bulk operation: {error_message}",
                response_data=response,
            )
            frappe.throw(_("Failed to start bulk operation: {0}").format(error_message))

        operation = response["data"]["bulkOperationRunQuery"]["bulkOperation"]
        return operation["id"]

    @temp_shopify_session
    def poll_bulk_operation(
        self, operation_id: str
    ) -> Tuple[BulkOperationStatus, Optional[str]]:
        """Poll the status of a bulk operation until completion"""
        query = (
            """
        query {
            node(id: "%s") {
                ... on BulkOperation {
                    status
                    url
                }
            }
        }
        """
            % operation_id
        )

        client = GraphQL()
        retries = 0

        while retries < self.max_retries:
            response = client.execute(query)
            operation = response["data"]["node"]
            status = BulkOperationStatus(operation["status"])

            if status in [BulkOperationStatus.COMPLETED, BulkOperationStatus.FAILED]:
                return status, operation.get("url")

            if status == BulkOperationStatus.FAILED:
                create_shopify_log(
                    status="Error",
                    message=f"Bulk operation failed: {operation_id}",
                    response_data=response,
                )
                frappe.throw(_("Bulk operation failed"))

            time.sleep(self.poll_interval)
            retries += 1

        create_shopify_log(
            status="Error",
            message=f"Bulk operation timed out: {operation_id}",
            response_data={"retries": retries},
        )
        frappe.throw(
            _("Bulk operation timed out after {0} retries").format(self.max_retries)
        )

    @staticmethod
    def _parse_jsonl_data(jsonl_data: str) -> List[dict]:
        """Parse JSONL data into a list of product dictionaries"""
        products = []
        for line in jsonl_data.strip().split("\n"):
            if line:
                products.append(json.loads(line))
        return products

    def _download_bulk_data(self, url: str) -> str:
        """Download bulk data from the provided URL"""
        response = requests.get(url)
        response.raise_for_status()
        return response.text

    def import_products(self, data_url: str) -> None:
        """Import products from bulk data"""
        try:
            jsonl_data = self._download_bulk_data(data_url)
            products = self._parse_jsonl_data(jsonl_data)

            for product_data in products:
                try:
                    product = ShopifyProduct(product_id=product_data["id"])
                    product.sync_product()
                except Exception as e:
                    create_shopify_log(
                        status="Error",
                        message=f"Failed to import product {product_data.get('id')}: {str(e)}",
                        response_data=product_data,
                    )
                    frappe.log_error(
                        title="Shopify Bulk Import Error",
                        message=f"Failed to import product {product_data.get('id')}: {str(e)}",
                    )

        except Exception as e:
            create_shopify_log(
                status="Error",
                message=f"Failed to process bulk data: {str(e)}",
                response_data={"url": data_url},
            )
            frappe.throw(_("Failed to process bulk data: {0}").format(str(e)))

    def run_bulk_import(self) -> None:
        """Run the complete bulk import process"""
        try:
            operation_id = self.start_bulk_operation()
            status, data_url = self.poll_bulk_operation(operation_id)

            if status == BulkOperationStatus.COMPLETED and data_url:
                self.import_products(data_url)
            else:
                frappe.throw(_("Bulk operation did not complete successfully"))

        except Exception as e:
            create_shopify_log(
                status="Error",
                message=f"Bulk import failed: {str(e)}",
                response_data={"error": str(e)},
            )
            frappe.throw(_("Bulk import failed: {0}").format(str(e)))
