"""Unit tests for SmartTextParser (bulk text parsing, FB shim decoding, context extraction)."""

import unittest
from main.text_parser import SmartTextParser, ParsedVideoItem


class TestSmartTextParser(unittest.TestCase):
    def test_unwrap_facebook_shim(self):
        shim = (
            "https://l.facebook.com/l.php?u=https%3A%2F%2Fyoutu.be%2FOiyX7zl1vQA%3Ffbclid%3D123"
            "&h=AT123&__tn__=R"
        )
        unwrapped = SmartTextParser.unwrap_facebook_shim(shim)
        self.assertTrue(unwrapped.startswith("https://youtu.be/OiyX7zl1vQA"))

    def test_clean_tracking_params(self):
        dirty_yt = "https://youtu.be/iwUonNa2YJM?fbclid=IwcGRvZg&si=xyz123&v=test_v"
        cleaned_yt = SmartTextParser.clean_tracking_params(dirty_yt)
        self.assertNotIn("fbclid", cleaned_yt)
        self.assertNotIn("si=", cleaned_yt)
        self.assertIn("v=test_v", cleaned_yt)

        dirty_fb = "https://www.facebook.com/reel/1721456089092781?__tn__=R&_aem_test=123"
        cleaned_fb = SmartTextParser.clean_tracking_params(dirty_fb)
        self.assertEqual(cleaned_fb, "https://www.facebook.com/reel/1721456089092781")

    def test_parse_sample_user_text_exact_order(self):
        raw_text = (
            "Phần 1-2: [https://youtu.be/OiyX7zl1vQA](https://l.facebook.com/l.php?u=https%3A%2F%2Fyoutu.be%2FOiyX7zl1vQA%3Ffbclid%3DIwcGRvZgVleHRuA2FlbQIxMABicmlkETFKYnN6Zm9heEJOQUhKbGtac3J0YwZhcHBfaWQQMjIyMDM5MTc4ODIwMDg5MgABHrdQQLitOalGdsUSBcIc417F3uH4Tfss0SSgvd-mMf0amj1VQ-1nZc_vawb6_aem_mWyM2f5DraspRyi2fGn1KA&h=AUDDZDcAKYRnhFB_sTbSe90TUjgMk0kSwl9H0RulZul4ywlCH1kyZqoDo5HhRWBJtAxDvs5TJxyFc0NHSTYjUff8uBmpyxAFyZUe4AAn4A3tIc-j1K6WWhaYsw6AtK1WqcHaQbeK3jOsAWC9m-YpacPvDh7Ml2Xn&__tn__=R) "
            "Phần 3: [https://youtu.be/iwUonNa2YJM](https://youtu.be/iwUonNa2YJM?fbclid=IwcGRvZgVleHRuA2FlbQIxMABicmlkETFKYnN6Zm9heEJOQUhKbGtac3J0YwZhcHBfaWQQMjIyMDM5MTc4ODIwMDg5MgABHqumq2LHrM8tiJdT36FpXU26PheXXqjATYhzT0Bnju_R58aMbVNc0Algr5g-_aem_SCZXlmrZ9enMSYTckMIrwA) "
            "Phan 4: [https://youtu.be/AqmikK9D-s4](https://youtu.be/AqmikK9D-s4?fbclid=IwcGRvZgVleHRuA2FlbQIxMABicmlkETFKYnN6Zm9heEJOQUhKbGtac3J0YwZhcHBfaWQQMjIyMDM5MTc4ODIwMDg5MgABHlyCMBJYzhmWKhvyhVnVbzBUIBcq_pFfUoCJGmMETw-ZDKe8agOxIst_5fsY_aem_0f8i6dE-dY3c08B7Z2Z2pQ) "
            "Phần 5: [https://www.facebook.com/reel/1721456089092781](https://www.facebook.com/reel/1721456089092781?__tn__=R) "
            "Phần 6: [https://www.facebook.com/reel/1722880025617054](https://www.facebook.com/reel/1722880025617054?__tn__=R) "
            "Phần 7: [https://www.facebook.com/reel/1723485742223149](https://www.facebook.com/reel/1723485742223149?__tn__=R) "
            "Phần 8: [https://www.facebook.com/reel/1724220798816310](https://www.facebook.com/reel/1724220798816310?__tn__=R) "
            "Phần 9: [https://www.facebook.com/reel/1724941915410865](https://www.facebook.com/reel/1724941915410865?__tn__=R) "
            "Phần 10: [https://www.facebook.com/reel/1725556108682779](https://www.facebook.com/reel/1725556108682779?__tn__=R) "
            "Phần 11: [https://www.facebook.com/reel/1726080205297036](https://www.facebook.com/reel/1726080205297036?__tn__=R) "
            "Phần 12: [https://www.facebook.com/reel/1726880868550303](https://www.facebook.com/reel/1726880868550303?__tn__=R) "
            "Phần 13: [https://www.facebook.com/reel/1727652758473114](https://www.facebook.com/reel/1727652758473114?__tn__=R) "
            "Phần 14: [https://www.facebook.com/reel/1728470535058003](https://www.facebook.com/reel/1728470535058003?__tn__=R) "
            "Phần 15: [https://www.facebook.com/reel/1729094721662251](https://www.facebook.com/reel/1729094721662251?__tn__=R) "
            "Phần 16: [https://www.facebook.com/reel/1729731238265266](https://www.facebook.com/reel/1729731238265266?__tn__=R) "
            "Phần 17: [https://www.facebook.com/reel/1730397758198614](https://www.facebook.com/reel/1730397758198614?__tn__=R) "
            "Phần 18: [https://youtu.be/O618QeB-2sE](https://youtu.be/O618QeB-2sE?fbclid=IwcGRvZgVleHRuA2FlbQIxMABicmlkETFKYnN6Zm9heEJOQUhKbGtac3J0YwZhcHBfaWQQMjIyMDM5MTc4ODIwMDg5MgABHr_J_Xm8qK4uC80) "
            "Phần 19: [https://youtu.be/QyS0B6Xo6Xk](https://youtu.be/QyS0B6Xo6Xk) "
            "Phần 20: [https://youtu.be/7V-e7m0zEVE](https://youtu.be/7V-e7m0zEVE) "
            "Phần 21: [https://youtu.be/0oG2r7ZkL28](https://youtu.be/0oG2r7ZkL28) "
            "Phần 22: [https://youtu.be/pW3g1Hk4g0k](https://youtu.be/pW3g1Hk4g0k) "
            "Phần 23: [https://youtu.be/L8e5E0gZ9fA](https://youtu.be/L8e5E0gZ9fA) "
            "Phần 24: [https://youtu.be/9FhK3b-W_g4](https://youtu.be/9FhK3b-W_g4) "
            "Phần 25-26-27: [https://youtu.be/vQx7h3m_P2U](https://youtu.be/vQx7h3m_P2U) "
            "Phần 28: [https://youtu.be/u8M9r8D2j7A](https://youtu.be/u8M9r8D2j7A) "
            "Phần 29: [https://youtu.be/p3K7m9L8g2Y](https://youtu.be/p3K7m9L8g2Y) "
            "Phần 30: [https://youtu.be/T4n9g6M7l2Q](https://youtu.be/T4n9g6M7l2Q) "
            "Phần 31: [https://youtu.be/X8m3j2L9g4K](https://youtu.be/X8m3j2L9g4K) "
            "Phần 32: [https://youtu.be/A9d2m5L8g3T](https://youtu.be/A9d2m5L8g3T) "
            "Phần 33: [https://youtu.be/V7n2m9K4g8P](https://youtu.be/V7n2m9K4g8P) "
            "Phần 34: [https://www.facebook.com/reel/1772512700461790/](https://www.facebook.com/reel/1772512700461790/?__tn__=R)"
        )

        items = SmartTextParser.parse_text(raw_text)
        self.assertEqual(len(items), 31)  # 31 items in this test string (sample counts)

        # Item 0 (Phần 1-2)
        self.assertEqual(items[0].url, "https://youtu.be/OiyX7zl1vQA")
        self.assertEqual(items[0].description, "Phần 1-2")
        self.assertEqual(items[0].source_name, "YouTube")

        # Item 1 (Phần 3)
        self.assertEqual(items[1].url, "https://youtu.be/iwUonNa2YJM")
        self.assertEqual(items[1].description, "Phần 3")

        # Item 2 (Phan 4)
        self.assertEqual(items[2].url, "https://youtu.be/AqmikK9D-s4")
        self.assertEqual(items[2].description, "Phan 4")

        # Item 3 (Phần 5)
        self.assertEqual(items[3].url, "https://www.facebook.com/reel/1721456089092781")
        self.assertEqual(items[3].description, "Phần 5")
        self.assertEqual(items[3].source_name, "Facebook")

        # Item 23 (Phần 25-26-27)
        self.assertEqual(items[23].description, "Phần 25-26-27")

        # Last item (Phần 34)
        self.assertEqual(items[-1].url, "https://www.facebook.com/reel/1772512700461790/")
        self.assertEqual(items[-1].description, "Phần 34")

    def test_arbitrary_prefixes_format_agnostic(self):
        text = """
        A: https://youtu.be/videoA
        B: https://youtu.be/videoB
        Ghi chú đặc biệt - https://youtu.be/videoC
        https://youtu.be/videoD
        """
        items = SmartTextParser.parse_text(text)
        self.assertEqual(len(items), 4)

        self.assertEqual(items[0].url, "https://youtu.be/videoA")
        self.assertEqual(items[0].description, "A")

        self.assertEqual(items[1].url, "https://youtu.be/videoB")
        self.assertEqual(items[1].description, "B")

        self.assertEqual(items[2].url, "https://youtu.be/videoC")
        self.assertEqual(items[2].description, "Ghi chú đặc biệt")

        self.assertEqual(items[3].url, "https://youtu.be/videoD")
        self.assertEqual(items[3].description, "")

    def test_deduplication_preserves_order(self):
        text = """
        Phần 1: https://youtu.be/vid1
        Phần 2: https://youtu.be/vid2
        Lặp lại Phần 1: https://youtu.be/vid1
        Phần 3: https://youtu.be/vid3
        """
        items = SmartTextParser.parse_text(text)
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0].url, "https://youtu.be/vid1")
        self.assertEqual(items[1].url, "https://youtu.be/vid2")
        self.assertEqual(items[2].url, "https://youtu.be/vid3")

    def test_empty_and_no_links(self):
        self.assertEqual(SmartTextParser.parse_text(""), [])
        self.assertEqual(SmartTextParser.parse_text("Xin chao moi nguoi"), [])


if __name__ == "__main__":
    unittest.main()
