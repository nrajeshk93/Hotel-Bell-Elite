"""Total Sales KPI on main dashboard uses Sales Update outlet totals."""

import json
import unittest
from datetime import date
from unittest.mock import MagicMock

from app import (
    DASHBOARD_FILTER_LOCATION_RESTAURANT_BAR,
    OUTLET_BAR,
    OUTLET_HOTEL,
    OUTLET_RESTAURANT,
    _build_main_dashboard_payload,
    _dashboard_outlet_names,
    _normalize_dashboard_location_filter,
    _resolve_main_dashboard_filters,
)


def _sales_row(total_sales):
    return {"sales_entry_values": json.dumps({"total_sales": total_sales, "cash": 0})}


class MainDashboardTotalSalesTests(unittest.TestCase):
    def test_total_sales_sums_hotel_restaurant_bar(self):
        day = date(2026, 8, 1)
        day_iso = day.isoformat()

        def execute(sql, params=None):
            sql_l = " ".join(str(sql).split()).lower()
            result = MagicMock()
            if "from sales_updates" in sql_l and "sales_entry_values" in sql_l:
                # Unfiltered range query used by KPI aggregate / sparks
                if "and location" not in sql_l:
                    result.fetchall.return_value = [
                        _sales_row(1000),
                        _sales_row(2000),
                        _sales_row(3000),
                    ]
                elif params and OUTLET_HOTEL in params:
                    result.fetchall.return_value = [_sales_row(1000)]
                elif params and OUTLET_RESTAURANT in params and OUTLET_BAR in params:
                    result.fetchall.return_value = [_sales_row(2000), _sales_row(3000)]
                elif params and OUTLET_RESTAURANT in params:
                    result.fetchall.return_value = [_sales_row(2000)]
                elif params and OUTLET_BAR in params:
                    result.fetchall.return_value = [_sales_row(3000)]
                else:
                    result.fetchall.return_value = []
                # spark series also selects sales_date
                if "sales_date," in sql_l:
                    rows = []
                    for amount, loc in (
                        (1000, OUTLET_HOTEL),
                        (2000, OUTLET_RESTAURANT),
                        (3000, OUTLET_BAR),
                    ):
                        if "and location" in sql_l and params and loc not in params:
                            continue
                        rows.append(
                            {
                                "sales_date": day_iso,
                                "sales_entry_values": json.dumps(
                                    {"total_sales": amount, "cash": 0}
                                ),
                            }
                        )
                    if "and location" not in sql_l:
                        rows = [
                            {
                                "sales_date": day_iso,
                                "sales_entry_values": json.dumps(
                                    {"total_sales": a, "cash": 0}
                                ),
                            }
                            for a in (1000, 2000, 3000)
                        ]
                    result.fetchall.return_value = rows
            elif "from sales_update_expenses" in sql_l:
                result.fetchone.return_value = {"total": 0}
                result.fetchall.return_value = []
            elif "from pos_" in sql_l or "menu" in sql_l:
                result.fetchall.return_value = []
                result.fetchone.return_value = None
            else:
                result.fetchall.return_value = []
                result.fetchone.return_value = {"total": 0}
            return result

        conn = MagicMock()
        conn.execute.side_effect = execute

        payload = _build_main_dashboard_payload(conn, day, day, location=None)
        kpi = next(k for k in payload["dashboard"]["kpis"] if k["key"] == "actual_sales")
        self.assertEqual(kpi["value"], 6000.0)
        self.assertEqual(payload["dashboard"]["sales_contribution"]["total_sales"], 6000.0)

    def test_restaurant_and_bar_filter_excludes_hotel(self):
        day = date(2026, 8, 1)
        day_iso = day.isoformat()

        def execute(sql, params=None):
            sql_l = " ".join(str(sql).split()).lower()
            result = MagicMock()
            if "from sales_updates" in sql_l and "sales_entry_values" in sql_l:
                if params and OUTLET_RESTAURANT in params and OUTLET_BAR in params:
                    rows = [_sales_row(2000), _sales_row(3000)]
                    if "sales_date," in sql_l:
                        rows = [
                            {
                                "sales_date": day_iso,
                                "sales_entry_values": json.dumps(
                                    {"total_sales": a, "cash": 0}
                                ),
                            }
                            for a in (2000, 3000)
                        ]
                    result.fetchall.return_value = rows
                else:
                    result.fetchall.return_value = []
            elif "from sales_update_expenses" in sql_l:
                result.fetchone.return_value = {"total": 0}
                result.fetchall.return_value = []
            else:
                result.fetchall.return_value = []
                result.fetchone.return_value = {"total": 0}
            return result

        conn = MagicMock()
        conn.execute.side_effect = execute
        payload = _build_main_dashboard_payload(
            conn, day, day, location=DASHBOARD_FILTER_LOCATION_RESTAURANT_BAR
        )
        kpi = next(k for k in payload["dashboard"]["kpis"] if k["key"] == "actual_sales")
        self.assertEqual(kpi["value"], 5000.0)
        self.assertEqual(
            _dashboard_outlet_names(DASHBOARD_FILTER_LOCATION_RESTAURANT_BAR),
            [OUTLET_RESTAURANT, OUTLET_BAR],
        )

    def test_resolve_restaurant_and_bar_location(self):
        filters = _resolve_main_dashboard_filters(
            {"location": DASHBOARD_FILTER_LOCATION_RESTAURANT_BAR, "period": "30d"}
        )
        self.assertEqual(
            filters["selected_location"], DASHBOARD_FILTER_LOCATION_RESTAURANT_BAR
        )
        self.assertEqual(filters["selected_location_label"], "Restaurant & Bar")
        self.assertEqual(
            _normalize_dashboard_location_filter(DASHBOARD_FILTER_LOCATION_RESTAURANT_BAR),
            [OUTLET_RESTAURANT, OUTLET_BAR],
        )


if __name__ == "__main__":
    unittest.main()
