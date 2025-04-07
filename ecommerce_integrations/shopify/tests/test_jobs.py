"""Test background jobs for Shopify integration."""

import unittest
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from ecommerce_integrations.shopify.product_class import ShopifyProduct
from ecommerce_integrations.shopify.constants import SETTING_DOCTYPE
from ecommerce_integrations.shopify.bulk_product_import import BulkProductImport

from ecommerce_integrations.shopify.jobs import enqueue_bulk_product_import


class TestShopifyJobs(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        self.setting = frappe.get_doc("Shopify Setting", "Shopify Setting")

    @patch("frappe.enqueue")
    def test_enqueue_bulk_product_import(self, mock_enqueue):
        """Test enqueuing bulk product import"""
        self.setting.enable_sync = 1
        self.setting.enable_bulk_import = 1
        self.setting.save()

        enqueue_bulk_product_import()

        mock_enqueue.assert_called_once_with(
            method=ShopifyProduct.import_products_bulk,
            queue="long",
            timeout=864000,
            job_name="shopify_bulk_product_import",
            enqueue_after_commit=True,
        )

    def test_enqueue_bulk_product_import_disabled(self):
        """Test enqueuing bulk product import when disabled"""
        self.setting.enable_sync = 1
        self.setting.enable_bulk_import = 0
        self.setting.save()

        with unittest.TestCase.assertRaises(self, frappe.ValidationError):
            enqueue_bulk_product_import()

    def test_enqueue_bulk_product_import_integration_disabled(self):
        """Test enqueuing bulk product import when integration is disabled"""
        self.setting.enable_sync = 0
        self.setting.enable_bulk_import = 1
        self.setting.save()

        with unittest.TestCase.assertRaises(self, frappe.ValidationError):
            enqueue_bulk_product_import()

    @patch("ecommerce_integrations.shopify.bulk_product_import.BulkProductImport")
    def test_bulk_product_import_job(self, mock_bulk_import):
        """Test bulk product import job execution"""
        self.setting.enable_sync = 1
        self.setting.enable_bulk_import = 1
        self.setting.save()

        mock_instance = mock_bulk_import.return_value
        mock_instance.run_bulk_import.return_value = True

        result = ShopifyProduct.import_products_bulk()

        mock_bulk_import.assert_called_once()
        mock_instance.run_bulk_import.assert_called_once()
        self.assertTrue(result)

    @patch("ecommerce_integrations.shopify.bulk_product_import.BulkProductImport")
    def test_bulk_product_import_job_failure(self, mock_bulk_import):
        """Test bulk product import job failure"""
        self.setting.enable_sync = 1
        self.setting.enable_bulk_import = 1
        self.setting.save()

        mock_instance = mock_bulk_import.return_value
        mock_instance.run_bulk_import.side_effect = Exception("Import failed")

        with unittest.TestCase.assertRaises(self, frappe.ValidationError):
            ShopifyProduct.import_products_bulk()

        mock_bulk_import.assert_called_once()
        mock_instance.run_bulk_import.assert_called_once()
