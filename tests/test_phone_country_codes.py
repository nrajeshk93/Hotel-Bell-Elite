"""Country calling-code list for check-in phone pickers."""

import unittest

from phone_country_codes import (
    COUNTRY_CALLING_CODES,
    nationality_for_country_name,
    phone_country_code_options,
    phone_country_name_options,
    phone_nationality_options,
)


class PhoneCountryCodeTests(unittest.TestCase):
    def test_includes_core_codes(self):
        codes = {code for _name, code in COUNTRY_CALLING_CODES}
        for expected in ("+91", "+1", "+44", "+971", "+81", "+86", "+61"):
            self.assertIn(expected, codes)

    def test_options_keep_compact_chip_label(self):
        options = phone_country_code_options()
        self.assertGreater(len(options), 180)
        india = [row for row in options if row[0] == "+91" and "India" in row[1]]
        self.assertEqual(len(india), 1)
        self.assertEqual(india[0][1], "India")
        self.assertEqual(india[0][2], "+91")

    def test_nationality_follows_country_name(self):
        self.assertEqual(nationality_for_country_name("India"), "Indian")
        self.assertEqual(nationality_for_country_name("indonesia"), "indonesia")
        self.assertEqual(nationality_for_country_name("Indonesia"), "Indonesia")
        self.assertEqual(nationality_for_country_name(""), "")

    def test_nationality_options_keep_indian_and_indonesia(self):
        options = phone_nationality_options()
        values = [row[0] for row in options]
        self.assertEqual(values[0], "Indian")
        self.assertIn("Indonesia", values)
        self.assertNotIn("India", values)
        self.assertIn("Other", values)

    def test_country_name_options_include_indonesia(self):
        values = [row[0] for row in phone_country_name_options()]
        self.assertIn("India", values)
        self.assertIn("Indonesia", values)
        self.assertIn("Other", values)
