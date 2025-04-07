"""Test bulk product import functionality for Shopify integration."""

import json
import unittest
from unittest.mock import patch, MagicMock

import frappe
from frappe.tests.utils import FrappeTestCase
from shopify import GraphQL

from ecommerce_integrations.shopify.bulk_product_import import (
    BulkProductImport,
    BulkOperationStatus,
)
from ecommerce_integrations.shopify.tests.utils import TestCase


class TestBulkProductImport(TestCase):
    def setUp(self):
        super().setUp()
        self.bulk_import = BulkProductImport(poll_interval=0, max_retries=1)
        self.mock_graphql = MagicMock()
        self.mock_requests = MagicMock()

    def test_create_bulk_query(self):
        """Test creation of bulk query"""
        query = self.bulk_import._create_bulk_query()
        self.assertIn("mutation", query)
        self.assertIn("bulkOperationRunQuery", query)
        self.assertIn("products", query)
        self.assertIn("variants", query)
        self.assertIn("images", query)

    @patch("ecommerce_integrations.shopify.bulk_product_import.GraphQL")
    def test_start_bulk_operation_success(self, mock_graphql_class):
        """Test successful start of bulk operation"""
        mock_graphql = MagicMock()
        mock_graphql_class.return_value = mock_graphql
        mock_graphql.execute.return_value = {
            "data": {
                "bulkOperationRunQuery": {
                    "bulkOperation": {"id": "gid://shopify/BulkOperation/123"},
                    "userErrors": [],
                }
            }
        }

        operation_id = self.bulk_import.start_bulk_operation()
        self.assertEqual(operation_id, "gid://shopify/BulkOperation/123")
        mock_graphql.execute.assert_called_once()

    @patch("ecommerce_integrations.shopify.bulk_product_import.GraphQL")
    def test_start_bulk_operation_failure(self, mock_graphql_class):
        """Test failure to start bulk operation"""
        mock_graphql = MagicMock()
        mock_graphql_class.return_value = mock_graphql
        mock_graphql.execute.return_value = {"errors": [{"message": "Invalid query"}]}

        with self.assertRaises(frappe.ValidationError):
            self.bulk_import.start_bulk_operation()

    @patch("ecommerce_integrations.shopify.bulk_product_import.GraphQL")
    def test_poll_bulk_operation_completed(self, mock_graphql_class):
        """Test polling bulk operation until completion"""
        mock_graphql = MagicMock()
        mock_graphql_class.return_value = mock_graphql
        mock_graphql.execute.return_value = {
            "data": {
                "node": {
                    "status": "COMPLETED",
                    "url": "https://example.com/data.jsonl",
                }
            }
        }

        status, url = self.bulk_import.poll_bulk_operation(
            "gid://shopify/BulkOperation/123"
        )
        self.assertEqual(status, BulkOperationStatus.COMPLETED)
        self.assertEqual(url, "https://example.com/data.jsonl")

    @patch("ecommerce_integrations.shopify.bulk_product_import.GraphQL")
    def test_poll_bulk_operation_failed(self, mock_graphql_class):
        """Test polling bulk operation that failed"""
        mock_graphql = MagicMock()
        mock_graphql_class.return_value = mock_graphql
        mock_graphql.execute.return_value = {
            "data": {
                "node": {
                    "status": "FAILED",
                    "url": None,
                }
            }
        }

        with self.assertRaises(frappe.ValidationError):
            self.bulk_import.poll_bulk_operation("gid://shopify/BulkOperation/123")

    @patch("ecommerce_integrations.shopify.bulk_product_import.requests")
    def test_download_bulk_data(self, mock_requests):
        """Test downloading bulk data"""
        mock_response = MagicMock()
        mock_response.text = '{"id":"1"}\n{"id":"2"}'
        mock_requests.get.return_value = mock_response

        data = self.bulk_import._download_bulk_data("https://example.com/data.jsonl")
        self.assertEqual(data, '{"id":"1"}\n{"id":"2"}')
        mock_requests.get.assert_called_once_with("https://example.com/data.jsonl")

    def test_parse_jsonl_data(self):
        """Test parsing JSONL data"""
        jsonl_data = '{"id":"1"}\n{"id":"2"}'
        products = self.bulk_import._parse_jsonl_data(jsonl_data)
        self.assertEqual(len(products), 2)
        self.assertEqual(products[0]["id"], "1")
        self.assertEqual(products[1]["id"], "2")

    @patch("ecommerce_integrations.shopify.bulk_product_import.ShopifyProduct")
    @patch("ecommerce_integrations.shopify.bulk_product_import.requests")
    def test_import_products(self, mock_requests, mock_shopify_product):
        """Test importing products from bulk data"""
        mock_response = MagicMock()
        mock_response.text = '{"id":"1"}\n{"id":"2"}'
        mock_requests.get.return_value = mock_response

        mock_product = MagicMock()
        mock_shopify_product.return_value = mock_product

        self.bulk_import.import_products("https://example.com/data.jsonl")

        self.assertEqual(mock_shopify_product.call_count, 2)
        mock_product.sync_product.assert_called()

    @patch(
        "ecommerce_integrations.shopify.bulk_product_import.BulkProductImport.start_bulk_operation"
    )
    @patch(
        "ecommerce_integrations.shopify.bulk_product_import.BulkProductImport.poll_bulk_operation"
    )
    @patch(
        "ecommerce_integrations.shopify.bulk_product_import.BulkProductImport.import_products"
    )
    def test_run_bulk_import_success(self, mock_import_products, mock_poll, mock_start):
        """Test successful bulk import process"""
        mock_start.return_value = "gid://shopify/BulkOperation/123"
        mock_poll.return_value = (
            BulkOperationStatus.COMPLETED,
            "https://example.com/data.jsonl",
        )

        self.bulk_import.run_bulk_import()

        mock_start.assert_called_once()
        mock_poll.assert_called_once_with("gid://shopify/BulkOperation/123")
        mock_import_products.assert_called_once_with("https://example.com/data.jsonl")

    @patch(
        "ecommerce_integrations.shopify.bulk_product_import.BulkProductImport.start_bulk_operation"
    )
    def test_run_bulk_import_failure(self, mock_start):
        """Test bulk import process failure"""
        mock_start.side_effect = Exception("Failed to start operation")

        with self.assertRaises(frappe.ValidationError):
            self.bulk_import.run_bulk_import()
