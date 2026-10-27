import unittest
import json
from unittest.mock import MagicMock, patch

import macro_data


class MacroDataTests(unittest.TestCase):
    def test_month_range_forms(self):
        self.assertEqual(macro_data.parse_month_range("14/6", "26/10"), ("2014-06", "2026-10"))
        self.assertEqual(macro_data.parse_month_range("2014-06", "2026-10"), ("2014-06", "2026-10"))

    def test_rejects_invalid_or_reversed_ranges(self):
        for start, end in (("2026-13", "2026-10"), ("2026-10", "2026-09"), ("bad", "2026-10")):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                macro_data.parse_month_range(start, end)

    def test_quarter_parser_and_credit_calculation(self):
        self.assertEqual(macro_data.quarter_of("2026年第3季度"), 2026 * 4 + 2)
        self.assertEqual(macro_data.month_of("2026 Jan"), "2026-01")
        self.assertEqual(macro_data.month_of("Jan-26"), "2026-01")
        financing = {"2026-%02d" % month: 1 for month in range(5, 11)}
        financing.update({"2025-%02d" % month: 0.5 for month in range(5, 11)})
        gdp = {2026 * 4 + 2: 100, 2026 * 4 + 1: 100}
        self.assertEqual(macro_data.calculate_credit(financing, gdp, "2026-10"), 1.5)

    def test_january_february_combined_release_maps_both_months(self):
        frame = [{"月份": "2025年1-2月份", "同比增长": 4.2}]
        values = macro_data.indexed_values(frame, ("同比增长",), ("月份",))
        self.assertEqual(values, {"2025-01": 4.2, "2025-02": 4.2})

    def test_retail_uses_cumulative_yoy_for_january_and_february(self):
        frame = [
            {"月份": "2025年2月份", "同比增长": 4.0, "累计-同比增长": 4.2},
            {"月份": "2025年3月份", "同比增长": 3.1, "累计-同比增长": 3.8},
        ]
        self.assertEqual(macro_data.retail_values(frame), {"2025-01": 4.2, "2025-02": 4.2, "2025-03": 3.1})

    def test_cumulative_gdp_is_converted_to_single_quarter_values(self):
        cumulative = {2025 * 4: 100, 2025 * 4 + 1: 210, 2025 * 4 + 2: 330, 2025 * 4 + 3: 460}
        self.assertEqual(macro_data.cumulative_gdp_to_quarters(cumulative), {2025 * 4: 100, 2025 * 4 + 1: 110, 2025 * 4 + 2: 120, 2025 * 4 + 3: 130})

    def test_nbs_report_parser_reads_single_quarter_current_price_gdp(self):
        report = """<html><title>2026年三季度国内生产总值初步核算结果</title>
        <table><tr><th>指标</th><th>三季度</th></tr>
        <tr><td>GDP</td><td>375367</td><td>1071071</td></tr></table></html>""".encode("utf-8")
        self.assertEqual(macro_data.parse_nbs_gdp_report(report), (2026 * 4 + 2, 375367.0))

    def test_nbs_fetch_discovers_and_parses_quarterly_reports(self):
        index = '''<a href="/q3.html" title="2026年三季度国内生产总值初步核算结果">GDP</a>
        <a href="/q2.html" title="2026年二季度和上半年国内生产总值初步核算结果">GDP</a>'''.encode("utf-8")
        def quarter_report(title, amount):
            return ("<title>" + title + "</title><table><tr><td>GDP</td><td>" + str(amount) + "</td></tr></table>").encode("utf-8")
        pages = {
            "https://www.stats.gov.cn/sj/zxfb/": (index, "https://www.stats.gov.cn/sj/zxfb/"),
            "https://www.stats.gov.cn/q3.html": (quarter_report("2026年三季度国内生产总值初步核算结果", 375367), "https://www.stats.gov.cn/q3.html"),
            "https://www.stats.gov.cn/q2.html": (quarter_report("2026年二季度和上半年国内生产总值初步核算结果", 361511), "https://www.stats.gov.cn/q2.html"),
        }
        with patch.object(macro_data, "_urlopen", side_effect=lambda url: (pages[url][0], pages[url][1], "text/html")):
            self.assertEqual(macro_data.fetch_nbs_gdp(), {2026 * 4 + 2: 375367.0, 2026 * 4 + 1: 361511.0})

    def test_credit_uses_only_gdp_published_by_month_end(self):
        financing = {"2026-%02d" % month: 1 for month in range(3, 9)}
        financing.update({"2025-%02d" % month: 0 for month in range(3, 9)})
        gdp = {2026 * 4 + 2: 300, 2026 * 4 + 1: 200, 2026 * 4: 100}
        self.assertAlmostEqual(macro_data.calculate_credit(financing, gdp, "2026-08"), 2.0)

    def test_akshare_adapter_uses_reference_api_names(self):
        class FakeAkshare:
            def macro_china_ppi(self):
                return [{"月份": "2026年10月份", "当月同比增长": 2.0}]
            def macro_china_consumer_goods_retail(self):
                return [{"月份": "2026年2月份", "同比增长": 4.0, "累计-同比增长": 4.2}]
            def macro_china_shrzgm(self):
                return [{"月份": "202610", "社会融资规模增量": 1000}]
            def macro_china_gdp(self):
                return [{"季度": "2026年第1季度", "国内生产总值-绝对值": 300000}]
            def stock_hk_index_daily_sina(self, symbol):
                self.symbol = symbol
                return [{"date": "2026-10-30", "close": 25000}]

        fake = FakeAkshare()
        with patch.object(macro_data, "_akshare", return_value=fake), patch.object(
            macro_data, "fetch_social_financing_direct", return_value=[]
        ), patch.object(
            macro_data, "fetch_nbs_gdp", return_value={}
        ), patch.object(macro_data, "fetch_pbc_social_financing", return_value=[]):
            result = macro_data.fetch_akshare("2025-10", "2026-10")
        self.assertEqual(fake.symbol, "HSI")
        self.assertEqual(result["retail"]["2026-01"], 4.2)
        self.assertEqual(result["financing"]["2026-10"], 1000)
        self.assertEqual(result["ppi"]["2026-10"], 2.0)
        self.assertEqual(result["hsi"]["2026-10"], 25000)

    def test_pbc_financing_overlays_akshare_and_mofcom_without_losing_history(self):
        class FakeAkshare:
            def macro_china_ppi(self):
                return [{"月份": "2026年6月份", "当月同比增长": 2.0}]
            def macro_china_consumer_goods_retail(self):
                return [{"月份": "2026年6月份", "同比增长": 3.0}]
            def macro_china_shrzgm(self):
                return [
                    {"月份": "202605", "社会融资规模增量": 12000},
                    {"月份": "202606", "社会融资规模增量": 13000},
                ]
            def macro_china_gdp(self):
                return [
                    {"季度": "2026年第1季度", "国内生产总值-绝对值": 300000},
                    {"季度": "2026年第2季度", "国内生产总值-绝对值": 700000},
                ]
            def stock_hk_index_daily_sina(self, symbol):
                return [{"date": "2026-06-30", "close": 25000}]

        pbc = [{"月份": "202605", "社会融资规模增量": 20293}, {"月份": "202606", "社会融资规模增量": 33671}]
        with patch.object(macro_data, "_akshare", return_value=FakeAkshare()), patch.object(
            macro_data, "fetch_social_financing_direct", return_value=[]
        ), patch.object(macro_data, "fetch_pbc_social_financing", return_value=pbc), patch.object(
            macro_data, "fetch_nbs_gdp", return_value={}
        ):
            result = macro_data.fetch_akshare("2025-06", "2026-06")
        self.assertEqual(result["financing"], {"2026-05": 20293.0, "2026-06": 33671.0})
        self.assertEqual(result["sources"]["social_financing"]["pbc"], "ok")

    def test_nbs_gdp_is_used_when_akshare_gdp_endpoint_fails(self):
        class FakeAkshare:
            def macro_china_ppi(self):
                return [{"月份": "2026年6月份", "当月同比增长": 2.0}]
            def macro_china_consumer_goods_retail(self):
                return [{"月份": "2026年6月份", "同比增长": 3.0}]
            def macro_china_shrzgm(self):
                return [{"月份": "202606", "社会融资规模增量": 13000}]
            def macro_china_gdp(self):
                raise RuntimeError("GDP endpoint unavailable")
            def stock_hk_index_daily_sina(self, symbol):
                return [{"date": "2026-06-30", "close": 25000}]

        with patch.object(macro_data, "_akshare", return_value=FakeAkshare()), patch.object(
            macro_data, "fetch_social_financing_direct", return_value=[]
        ), patch.object(macro_data, "fetch_pbc_social_financing", return_value=[]), patch.object(
            macro_data, "fetch_nbs_gdp", return_value={2026 * 4 + 1: 700000.0, 2026 * 4: 330000.0}
        ):
            result = macro_data.fetch_akshare("2025-06", "2026-06")
        self.assertEqual(result["gdp"][2026 * 4 + 1], 700000.0)
        self.assertTrue(result["sources"]["gdp"].startswith("国家统计局"))

    def test_akshare_empty_json_response_retries_and_names_source(self):
        calls = []
        def endpoint():
            calls.append(1)
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        with patch.object(macro_data.time, "sleep"):
            with self.assertRaisesRegex(macro_data.DataUpdateError, "社零.*macro_china_consumer_goods_retail.*空响应"):
                macro_data._call_akshare("社零（macro_china_consumer_goods_retail）", endpoint)
        self.assertEqual(len(calls), 2)

    def test_social_financing_direct_fallback_parses_mofcom_rows(self):
        values = ["202610", 1, 2, 3, 4, 5, 6000, 7, 8]
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps([{"date": "202610", "tiosfs": 6000}]).encode()
        with patch.object(macro_data.urllib.request, "urlopen", return_value=response) as open_url:
            rows = macro_data.fetch_social_financing_direct()
        self.assertEqual(rows[0], {"月份": "202610", "社会融资规模增量": 6000})
        request = open_url.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertIn("data.mofcom.gov.cn", request.get_header("Referer"))

    def test_social_financing_sources_are_merged_with_later_source_precedence(self):
        historical = [
            {"月份": "202604", "社会融资规模增量": 12000},
            {"月份": "202605", "社会融资规模增量": 13000},
        ]
        official = [
            {"月份": "202605", "社会融资规模增量": 20293},
            {"月份": "202606", "社会融资规模增量": 33671},
        ]
        self.assertEqual(
            macro_data.merge_social_financing(historical, official),
            {"2026-04": 12000.0, "2026-05": 20293.0, "2026-06": 33671.0},
        )

    def test_pbc_html_parser_reads_monthly_increment(self):
        content = """<table><tr><td>2026.05</td><td>20293</td></tr>
        <tr><td>2026.06</td><td>33671</td></tr></table>""".encode("gb2312")
        self.assertEqual(
            macro_data.parse_pbc_social_financing_html(content),
            [
                {"月份": "202605", "社会融资规模增量": 20293.0},
                {"月份": "202606", "社会融资规模增量": 33671.0},
            ],
        )

    def test_pbc_fetch_selects_national_flow_table_not_stock_or_provincial(self):
        page = """<meta charset="utf-8"><table>
        <tr><td><div>社会融资规模增量统计表</div><a href="/flow.htm">htm</a></td></tr>
        <tr><td><div>社会融资规模存量统计表</div><a href="/stock.htm">htm</a></td></tr>
        <tr><td><div>地区社会融资规模增量统计表</div><a href="/regional.htm">htm</a></td></tr>
        </table>""".encode("utf-8")
        flow = "<table><tr><td>2026.09</td><td>35476</td></tr></table>".encode("utf-8")
        payloads = {
            macro_data.PBC_SHRZGM_PAGE: (page, macro_data.PBC_SHRZGM_PAGE, "text/html"),
            "https://www.pbc.gov.cn/flow.htm": (flow, "https://www.pbc.gov.cn/flow.htm", "text/html"),
        }
        with patch.object(macro_data, "_urlopen", side_effect=lambda url: payloads[url]) as fetch:
            rows = macro_data.fetch_pbc_social_financing()
        self.assertEqual(rows, [{"月份": "202609", "社会融资规模增量": 35476.0}])
        self.assertEqual(fetch.call_args_list[1].args[0], "https://www.pbc.gov.cn/flow.htm")

    def test_update_calculates_m2_yoy_and_full_month_row(self):
        ak_data = {
            "ppi": {"2026-10": 2.0},
            "retail": {"2026-10": 3.0},
            "financing": {"2026-%02d" % month: 1 for month in range(5, 11)},
            "gdp": {2026 * 4 + 2: 100, 2026 * 4 + 1: 100},
            "hsi": {"2026-10": 25000.0},
        }
        ak_data["financing"].update({"2025-%02d" % month: 0.5 for month in range(5, 11)})
        with patch.object(macro_data, "fetch_akshare", return_value=ak_data), patch.object(
            macro_data, "fetch_hkma_m2", return_value={"2026-10": 10.0}
        ):
            result = macro_data.update_monthly_data("2026-10", "2026-10")
        self.assertEqual(result["months"], 1)
        self.assertAlmostEqual(result["rows"][0]["values"][0], 10.0)
        self.assertEqual(result["rows"][0]["values"][1:], [2.0, 3.0, 1.5])
        self.assertEqual(result["rows"][0]["hsi"], 25000.0)

    def test_missing_monthly_values_are_left_blank_and_annotated(self):
        ak_data = {"ppi": {}, "retail": {}, "financing": {}, "gdp": {}, "hsi": {}}
        with patch.object(macro_data, "fetch_akshare", return_value=ak_data), patch.object(
            macro_data, "fetch_hkma_m2", return_value={}
        ):
            result = macro_data.update_monthly_data("2026-10", "2026-10")
        self.assertEqual(result["incomplete_months"], 1)
        self.assertEqual(result["rows"][0]["values"], [None, None, None, None])
        self.assertIn("缺少", result["rows"][0]["note"])
        self.assertIn("缺少社融月份", result["rows"][0]["note"])

    def test_early_month_with_missing_hsi_and_credit_is_still_written(self):
        ak_data = {
            "ppi": {"2013-06": 1.2},
            "retail": {"2013-06": 2.3},
            "financing": {},
            "gdp": {},
            "hsi": {},
        }
        with patch.object(macro_data, "fetch_akshare", return_value=ak_data), patch.object(
            macro_data, "fetch_hkma_m2", return_value={"2013-06": 4.5}
        ):
            result = macro_data.update_monthly_data("2013-06", "2013-06")
        row = result["rows"][0]
        self.assertEqual(row["values"], [4.5, 1.2, 2.3, None])
        self.assertIsNone(row["hsi"])
        self.assertIn("credit", row["note"])
        self.assertIn("hsi", row["note"])
        self.assertEqual(result["incomplete_months"], 1)


if __name__ == "__main__":
    unittest.main()
