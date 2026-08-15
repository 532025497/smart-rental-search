# -*- coding: utf-8 -*-
import os
import tempfile
import unittest

from src.listing_store import ListingStore


class ListingStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = ListingStore(os.path.join(self.temp_dir.name, "rentals.db"))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_parses_text_and_deduplicates_source_url(self):
        payload = {
            "city": "北京",
            "area": "大望路",
            "source_url": "https://example.com/listing/1",
            "raw_text": "个人转租大望路主卧，月租3500元，可短租三个月，无中介费",
        }
        first = self.store.save(payload)
        second = self.store.save({**payload, "raw_text": payload["raw_text"] + "，随时入住"})

        self.assertEqual(first["price_monthly"], 3500)
        self.assertEqual(first["lease_term"], "短租")
        self.assertEqual(first["room_type"], "主卧")
        self.assertTrue(first["is_personal"])
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(len(self.store.list(city="北京", area="大望路")), 1)

    def test_price_stats_are_filtered_by_lease_and_personal(self):
        for index, price in enumerate((3000, 3200, 3500, 3800, 5000)):
            self.store.save({
                "city": "北京",
                "area": "大望路",
                "title": f"个人长租{index}",
                "raw_text": f"大望路整租，长租，月租{price}元，个人房东",
                "price_monthly": price,
                "lease_term": "长租",
                "room_type": "整租",
                "is_personal": True,
            })
        self.store.save({
            "city": "北京",
            "area": "大望路",
            "title": "中介短租",
            "raw_text": "中介短租房源，月租9000元，收服务费",
            "price_monthly": 9000,
            "lease_term": "短租",
            "room_type": "整租",
            "is_personal": False,
        })

        stats = self.store.price_stats(
            city="北京", area="大望路", lease_term="长租",
            room_type="整租", personal_only=True,
        )
        self.assertEqual(stats["sample_count"], 5)
        self.assertEqual(stats["median"], 3500)
        self.assertEqual(stats["q25"], 3200)
        self.assertEqual(stats["q75"], 3800)
        self.assertEqual(stats["confidence"], "中等")

    def test_rejects_invalid_url_and_missing_price(self):
        with self.assertRaisesRegex(ValueError, "来源链接"):
            self.store.save({
                "city": "北京", "area": "国贸",
                "source_url": "javascript:alert(1)",
                "raw_text": "个人房源，月租4000元",
            })
        with self.assertRaisesRegex(ValueError, "有效月租"):
            self.store.save({
                "city": "北京", "area": "国贸", "raw_text": "个人房源，价格面议",
            })


if __name__ == "__main__":
    unittest.main()
