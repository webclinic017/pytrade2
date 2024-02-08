import logging
from typing import Dict
import lightgbm as lgb
import pandas as pd
from sklearn.multioutput import MultiOutputRegressor
from exch.Exchange import Exchange
from strategy.common.StrategyBase import StrategyBase
from strategy.features.LowHighTargets import LowHighTargets
from strategy.features.MultiIndiFeatures import MultiIndiFeatures
from strategy.signal.SignalByFutLowHigh import SignalByFutLowHigh


class LongCandleLgbStrategy(StrategyBase):
    """
     Lgb regression, multiple indicators are features, predicts low/high
   """

    def __init__(self, config: Dict, exchange_provider: Exchange):
        self.websocket_feed = None

        StrategyBase.__init__(self, config=config,
                              exchange_provider=exchange_provider,
                              is_candles_feed=True,
                              is_bid_ask_feed=False,
                              is_level2_feed=False)
        comissionpct = float(config.get('pytrade2.broker.comissionpct'))
        self.signal_calc = SignalByFutLowHigh(self.profit_loss_ratio, self.stop_loss_min_coeff,
                                              self.stop_loss_max_coeff, self.profit_min_coeff,
                                              self.profit_max_coeff, comissionpct, self.price_precision)

        self.features_periods = [s.strip() for s in
                                 str(config["pytrade2.strategy.candles.features.periods"]).split(",")]

        # Should keep 1 more candle for targets
        predict_window = config["pytrade2.strategy.predict.window"]
        self.target_period = predict_window

        logging.info(f"Target period: {self.target_period}")

    def prepare_xy(self) -> (pd.DataFrame, pd.DataFrame):
        # Candles with minimal period will be resampled in feature engineering
        candles = self.candles_feed.candles_by_interval[min(self.candles_feed.candles_by_interval)]
        x = MultiIndiFeatures.multi_indi_features(candles, self.features_periods)

        y = LowHighTargets.fut_lohi(candles, self.target_period)
        x = x[x.index.isin(y.index)]
        # Balance by signal
        return x, y

    def prepare_last_x(self) -> (pd.DataFrame, pd.DataFrame, pd.DataFrame):
        candles = self.candles_feed.candles_by_interval[min(self.candles_feed.candles_by_interval)]
        x = MultiIndiFeatures.multi_indi_features(candles, self.features_periods).tail(1)
        return x

    def predict(self, x):
        x_trans = self.X_pipe.transform(x)
        y_arr = self.model.predict(x_trans)
        y_arr = self.y_pipe.inverse_transform(y_arr)
        y_arr = y_arr.reshape((-1, 2))[-1]  # Last and only row
        fut_low, fut_high = y_arr[0], y_arr[1]
        y_df = pd.DataFrame(data={'fut_low': fut_low, 'fut_high': fut_high}, index=x.tail(1).index)
        return y_df

    def process_prediction(self, y_pred: pd.DataFrame):
        # Calc signal
        fut_low, fut_high = y_pred.loc[y_pred.index[-1], ["fut_low", "fut_high"]]
        dt, open_, high, low, close = \
            self.candles_feed.candles_by_interval[self.target_period][
                ['close_time', 'open', 'high', 'low', 'close']].iloc[-1]
        signal, sl, tp = self.signal_calc.calc_signal(close, low, high, fut_low, fut_high)

        # Trade
        if signal:
            self.broker.create_cur_trade(symbol=self.ticker,
                                         direction=signal,
                                         quantity=self.order_quantity,
                                         price=close,
                                         stop_loss_price=sl,
                                         take_profit_price=tp,
                                         trailing_delta=None)

        # Persist signal data for later analysis
        signal_ext_df = pd.DataFrame(data=[{'signal': signal,
                                            'open': open_,
                                            'high': high,
                                            'low': low,
                                            'close': close,
                                            'stop_loss': sl,
                                            'take_profit': tp}],
                                     index=[dt])
        self.data_persister.save_last_data(self.ticker, {'signal_ext': signal_ext_df})

    def create_model(self, X_size, y_size):
        lgb_model = lgb.LGBMRegressor(verbose=-1)  # supress rubbish in log

        model = MultiOutputRegressor(lgb_model)
        logging.info(f'Created model: {model}')
        return model