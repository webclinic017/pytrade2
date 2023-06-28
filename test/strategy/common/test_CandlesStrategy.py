import datetime
import os
import sys
from unittest import TestCase

import pandas as pd

from strategy.common.CandlesStrategy import CandlesStrategy

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".")))
from StrategyStub import StrategyStub


class TestCandlesStrategy(TestCase):
    def test_on_candle(self):
        strategy = StrategyStub()
        strategy.candles_by_period = {}

        # Candle 1 received
        dt1 = datetime.datetime(year=2023, month=6, day=28, hour=9, minute=52)
        candle1 = {"close_time": dt1, "interval": "1min", "close": 1}
        strategy.on_candle(candle1)
        self.assertEqual(1, len(strategy.candles_by_period))
        self.assertEqual([dt1], strategy.candles_by_period["1min"].index.tolist())
        self.assertEqual([pd.Timestamp(dt1)],
                         [pd.Timestamp(dt) for dt in strategy.candles_by_period["1min"]["close_time"].values.tolist()])
        self.assertEqual([1], strategy.candles_by_period["1min"]["close"].values.tolist())

        # Candle2 received in 59 sec - update of candle1
        dt2 = dt1 + datetime.timedelta(seconds=59)
        candle2 = {"close_time": dt2, "interval": "1min", "close": 2}
        strategy.on_candle(candle2)
        self.assertEqual(1, len(strategy.candles_by_period["1min"]))
        self.assertEqual([pd.Timestamp(dt1)],
                         [pd.Timestamp(dt) for dt in strategy.candles_by_period["1min"]["open_time"].values.tolist()])
        self.assertEqual([pd.Timestamp(dt2)],
                         [pd.Timestamp(dt) for dt in strategy.candles_by_period["1min"]["close_time"].values.tolist()])
        self.assertEqual([2], strategy.candles_by_period["1min"]["close"].values.tolist())

        # Candle2 received in 1 min - new candle
        dt3 = dt2 + datetime.timedelta(minutes=1)
        candle3 = {"close_time": dt3, "interval": "1min", "close": 3}
        strategy.on_candle(candle3)
        self.assertEqual(2, len(strategy.candles_by_period["1min"]))
        self.assertEqual([pd.Timestamp(dt1), pd.Timestamp(dt2)],
                         [pd.Timestamp(dt) for dt in strategy.candles_by_period["1min"]["open_time"].values.tolist()])
        self.assertEqual([pd.Timestamp(dt2), pd.Timestamp(dt3)],
                         [pd.Timestamp(dt) for dt in strategy.candles_by_period["1min"]["close_time"].values.tolist()])
        self.assertEqual([2, 3], strategy.candles_by_period["1min"]["close"].values.tolist())

    def test_has_history_empty(self):
        strategy = StrategyStub()
        strategy.candles_cnt_by_interval = {"1min": 2, "5min": 3}
        strategy.candles_by_period = {}

        self.assertFalse(strategy.has_all_candles())

    def test_has_all_candles_enough_history(self):
        strategy = StrategyStub()
        strategy.candles_cnt_by_interval = {"1min": 2, "5min": 3}
        strategy.candles_by_period = {"1min": [{}, {}],
                                      "5min": [{}, {}, {}]}

        self.assertTrue(strategy.has_all_candles())

    def test_has_all_candles_not_enough_history(self):
        strategy = StrategyStub()
        strategy.candles_cnt_by_interval = {"1min": 2, "5min": 3}
        strategy.candles_by_period = {"1min": [{}, {}],
                                      "5min": [{}, {}]}

        self.assertFalse(strategy.has_all_candles())

    def test_has_all_candles_not_all_periods(self):
        strategy = StrategyStub()
        strategy.candles_cnt_by_interval = {"1min": 2, "5min": 3}
        strategy.candles_by_period = {"1min": [{}, {}]}

        self.assertFalse(strategy.has_all_candles())

    def test_last_candle_min_time(self):
        # Prepare the data
        strategy = StrategyStub()
        dt1 = datetime.datetime(year=2023, month=6, day=28, hour=9, minute=1)
        dt2 = datetime.datetime(year=2023, month=6, day=28, hour=9, minute=2)
        dt3 = datetime.datetime(year=2023, month=6, day=28, hour=9, minute=3)

        strategy.candles_by_period = {
            "1min": pd.DataFrame([{"close_time": dt2}]).set_index("close_time"),
            "5min": pd.DataFrame([{"close_time": dt1}, {"close_time": dt3}]).set_index("close_time")
        }

        # Call
        actual = strategy.last_candle_min_time()

        # Assert
        self.assertEqual(dt2, actual)

    def test_last_candle_min_time__empty(self):
        # Prepare the data
        strategy = StrategyStub()
        strategy.candles_by_period={}

        # Call
        actual = strategy.last_candle_min_time()

        # Assert
        self.assertIsNone(actual)

    def test_candles_history_counts(self):
        periods = ["1min", "5min"]
        counts = [2, 2]
        history_window = "10min"
        predict_window = "1min"
        actual = CandlesStrategy.candles_history_counts(periods, counts, history_window, predict_window)
        self.assertEqual({"1min": 14, "5min": 5}, actual)

    def test_candles_history_counts__small_history(self):
        periods = ["1min", "5min"]
        counts = [2, 2]
        history_window = "10s"
        predict_window = "1s"
        actual = CandlesStrategy.candles_history_counts(periods, counts, history_window, predict_window)
        self.assertEqual({"1min": 3, "5min": 3}, actual)
