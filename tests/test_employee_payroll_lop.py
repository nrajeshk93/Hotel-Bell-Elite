import unittest

from employee_payroll import _calc_salary, _calc_total_off_lop, _apply_total_off_to_attendance_view


class TotalOffLopTests(unittest.TestCase):
    def test_no_lop_when_leave_within_entitlement(self):
        info = _calc_total_off_lop(3, 4, 15000, 30)
        self.assertEqual(info['lop_days'], 0)
        self.assertEqual(info['lop_deduction'], 0.0)
        self.assertEqual(info['paid_calendar_days'], 30)
        self.assertEqual(info['pay_ratio'], 1.0)

    def test_one_lop_day_example(self):
        info = _calc_total_off_lop(5, 4, 15000, 30)
        self.assertEqual(info['lop_days'], 1)
        self.assertEqual(info['daily_rate'], 500.0)
        self.assertEqual(info['lop_deduction'], 500.0)
        self.assertEqual(info['paid_calendar_days'], 29)
        self.assertAlmostEqual(info['pay_ratio'], 29 / 30)

    def test_half_day_leave_counts(self):
        info = _calc_total_off_lop(4.5, 4, 15000, 30)
        self.assertEqual(info['lop_days'], 0.5)
        self.assertEqual(info['lop_deduction'], 250.0)

    def test_zero_entitlement_makes_all_leave_lop(self):
        info = _calc_total_off_lop(2, 0, 12000, 30)
        self.assertEqual(info['lop_days'], 2)
        self.assertEqual(info['lop_deduction'], 800.0)

    def test_calc_salary_applies_lop_to_gross_and_net(self):
        salary = _calc_salary(
            15000,
            calendar_days=30,
            weekday_leave_days=5,
            total_off=4,
            tracked=True,
            epf_exempt=True,
            esic_exempt=True,
        )
        self.assertEqual(salary['lop_days'], 1)
        self.assertEqual(salary['lop_deduction'], 500.0)
        self.assertEqual(salary['gross_actual'], 14500.0)
        self.assertEqual(salary['net'], 14500.0)

    def test_untracked_attendance_pays_zero(self):
        salary = _calc_salary(
            15000,
            calendar_days=30,
            tracked=False,
            epf_exempt=True,
            esic_exempt=True,
        )
        self.assertEqual(salary['gross_actual'], 0.0)
        self.assertEqual(salary['net'], 0.0)

    def test_epf_is_12_percent_of_actual_gross_capped_at_1800(self):
        salary = _calc_salary(
            30000,
            calendar_days=30,
            tracked=True,
            epf_exempt=False,
            esic_exempt=True,
        )
        self.assertEqual(salary['gross_actual'], 30000.0)
        self.assertEqual(salary['epf'], 1800.0)  # min(1800, 12% of 30000)
        self.assertEqual(salary['epf_full'], 1800.0)
        self.assertAlmostEqual(
            salary['basic'] + salary['epf'] + salary['esic'],
            30000.0,
            places=2,
        )

    def test_epf_uses_actual_gross_after_lop(self):
        salary = _calc_salary(
            15000,
            calendar_days=30,
            weekday_leave_days=5,
            total_off=4,
            tracked=True,
            epf_exempt=False,
            esic_exempt=True,
        )
        self.assertEqual(salary['gross_actual'], 14500.0)
        self.assertEqual(salary['epf'], 1740.0)  # 12% of 14500

    def test_custom_epf_also_caps_at_1800(self):
        salary = _calc_salary(
            30000,
            calendar_days=30,
            tracked=True,
            custom_epf=3214,
            epf_exempt=False,
            esic_exempt=True,
        )
        self.assertEqual(salary['epf_full'], 1800.0)
        self.assertEqual(salary['epf'], 1800.0)

    def test_esic_fixed_158_above_21000(self):
        salary = _calc_salary(
            30000,
            calendar_days=30,
            tracked=True,
            epf_exempt=False,
            esic_exempt=False,
        )
        self.assertEqual(salary['esic_full'], 158.0)
        self.assertEqual(salary['esic'], 158.0)
        self.assertTrue(salary['esic_applicable'])
        self.assertEqual(salary['epf'], 1800.0)
        self.assertEqual(salary['net'], 28042.0)  # 30000 - 1800 - 158

    def test_esic_applies_at_or_below_21000(self):
        salary = _calc_salary(
            21000,
            calendar_days=30,
            tracked=True,
            epf_exempt=True,
            esic_exempt=False,
        )
        self.assertEqual(salary['esic_full'], 158)  # 0.75% of 21000, rounded to rupee
        self.assertTrue(salary['esic_applicable'])


class TotalOffAbsentDisplayTests(unittest.TestCase):
    def test_leave_within_total_off_not_counted_as_absent(self):
        att = {
            'absent': 2,
            'half_day': 0,
            'weekday_leave_days': 2,
            'tracked': True,
        }
        view = _apply_total_off_to_attendance_view(att, total_off=4)
        self.assertEqual(view['absent_marked'], 2)
        self.assertEqual(view['leave_covered_by_off'], 2)
        self.assertEqual(view['absent'], 0)

    def test_leave_beyond_total_off_counts_as_absent(self):
        att = {
            'absent': 6,
            'half_day': 0,
            'weekday_leave_days': 6,
            'tracked': True,
        }
        view = _apply_total_off_to_attendance_view(att, total_off=4)
        self.assertEqual(view['absent'], 2)
        self.assertEqual(view['leave_covered_by_off'], 4)

    def test_half_day_leave_uses_total_off(self):
        att = {
            'absent': 3,
            'half_day': 2,
            'weekday_leave_days': 4.0,
            'tracked': True,
        }
        view = _apply_total_off_to_attendance_view(att, total_off=4)
        self.assertEqual(view['absent'], 0)
        self.assertEqual(view['leave_covered_by_off'], 4)


if __name__ == '__main__':
    unittest.main()
