# -*- coding: utf-8 -*-
import os
import tempfile
import unittest

import app as app_module
from src.listing_store import ListingStore


class ListingApiTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        app_module.LISTING_STORE = ListingStore(
            os.path.join(self.temp_dir.name, "rentals.db")
        )
        app_module.app.config.update(TESTING=True)
        self.client = app_module.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_import_and_price_reference(self):
        response = self.client.post("/api/listings/import", json={
            "city": "北京",
            "area": "呼家楼",
            "raw_text": "房东直租呼家楼整租一居，月租5600元，长租，无中介费",
            "source_url": "https://example.com/hu-jia-lou-1",
            "is_personal": True,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["listing"]["price_monthly"], 5600)

        response = self.client.get(
            "/api/prices?city=北京&area=呼家楼&lease_term=长租&personal_only=1"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["stats"]["sample_count"], 1)
        self.assertEqual(response.json["stats"]["median"], 5600)
        self.assertEqual(len(response.json["listings"]), 1)

    def test_import_requires_text(self):
        response = self.client.post("/api/listings/import", json={"city": "北京"})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json["ok"])


if __name__ == "__main__":
    unittest.main()
