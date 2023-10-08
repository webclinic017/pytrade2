import datetime
from unittest import TestCase
from unittest.mock import MagicMock, Mock, patch

import pandas as pd

from strategy.common.LongCandleStrategyBase import LongCandleStrategyBase
from strategy.common.features.CandlesFeatures import CandlesFeatures


class LongCandleStrategyBaseTest(TestCase):

    def new_strategy(self):
        conf = {"pytrade2.tickers": "test", "pytrade2.strategy.learn.interval.sec": 60,
                "pytrade2.data.dir": "tmp",
                "pytrade2.price.precision": 2,
                "pytrade2.amount.precision": 2,
                "pytrade2.strategy.predict.window": "10s",
                "pytrade2.strategy.past.window": "1s",
                "pytrade2.strategy.history.min.window": "10s",
                "pytrade2.strategy.history.max.window": "10s",
                "pytrade2.strategy.riskmanager.wait_after_loss": "0s",

                "pytrade2.feed.candles.periods": "1min,5min",
                "pytrade2.feed.candles.counts": "1,1",
                "pytrade2.order.quantity": 0.001}

        LongCandleStrategyBase.__init__ = MagicMock(return_value=None)
        strategy = LongCandleStrategyBase(conf, None)
        strategy.target_period = "1min"
        strategy.x_unchecked = pd.DataFrame()
        strategy.y_unchecked = pd.DataFrame()

        return strategy

    def test_get_sl_tp_trdelta_buy(self):
        strategy = self.new_strategy()
        strategy.candles_by_interval = {strategy.target_period: pd.DataFrame([{"high": 3, "low": 1}])}
        sl, tp, trd = strategy.get_sl_tp_trdelta(1)

        self.assertEqual(1, sl)
        self.assertEqual(3, tp)
        self.assertEqual(2, trd)

    def test_get_sl_tp_trdelta_sell(self):
        strategy = self.new_strategy()
        strategy.candles_by_interval = {strategy.target_period: pd.DataFrame([{"high": 3, "low": 1}])}
        sl, tp, trd = strategy.get_sl_tp_trdelta(-1)

        self.assertEqual(3, sl)
        self.assertEqual(1, tp)
        self.assertEqual(2, trd)

    def test_update_unchecked(self):
        # Prepare strategy
        strategy = self.new_strategy()
        # CandlesFeatures.targets_of = MagicMock(return_value=pd.DataFrame(data=[1], index=[1]))
        strategy.candles_by_interval = {strategy.target_period: pd.DataFrame(
            data=[{'low': 1, 'high': 1}, {'low': 2, 'high': 2}, {'low': 3, 'high': 3}],
            index=[1, 2, 3])}

        # Add candle 1
        checked_x, checked_y = strategy.update_unchecked(pd.DataFrame([{'low': 1, 'high': 1}], index=[1]),
                                                         pd.DataFrame(data=[1], index=[1]))
        self.assertTrue(checked_x.empty)
        self.assertTrue(checked_y.empty)

        # Add candle 2
        checked_x, checked_y = strategy.update_unchecked(pd.DataFrame([{'low': 2, 'high': 2}], index=[2]),
                                                         pd.DataFrame(data=[2], index=[2]))

        self.assertTrue(checked_x.empty)
        self.assertTrue(checked_y.empty)

        # Add candle3
        checked_x, checked_y = strategy.update_unchecked(pd.DataFrame([{'low': 3, 'high': 3}], index=[3]),
                                                         pd.DataFrame(data=[3], index=[3]))

        # Candle1 is old, has targets
        self.assertListEqual([1], checked_x.index.tolist())
        self.assertListEqual([1], checked_y.index.tolist())

        # Candle 2,3 are still without targets
        self.assertListEqual([2, 3], strategy.x_unchecked.index.tolist())
        self.assertListEqual([2, 3], strategy.y_unchecked.index.tolist())
