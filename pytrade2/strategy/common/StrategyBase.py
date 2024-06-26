import gc
import logging
import multiprocessing
import traceback
import time
from datetime import datetime, timedelta
from threading import Thread, Event, Timer
from typing import Dict
import pandas as pd
import tensorflow.python.keras.backend
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler, MaxAbsScaler

from exch.Exchange import Exchange
from metrics.MetricServer import MetricServer
from strategy.common.RiskManager import RiskManager
from strategy.feed.BidAskFeed import BidAskFeed
from strategy.feed.CandlesFeed import CandlesFeed
from strategy.feed.Level2Feed import Level2Feed
from strategy.persist.DataPersister import DataPersister
from strategy.persist.ModelPersister import ModelPersister


class StrategyBase:
    """ Any strategy """

    def __init__(self, config: Dict, exchange_provider: Exchange, is_candles_feed: bool, is_bid_ask_feed: bool,
                 is_level2_feed: bool):
        self._logger = logging.getLogger(self.__class__.__name__)

        strategy_name = self.__class__.__name__
        self.data_persister = DataPersister(config, strategy_name)
        self.model_name = strategy_name.rstrip("Strategy")
        self.model_persister = ModelPersister(config, strategy_name)

        self.config = config
        self.tickers = self.config["pytrade2.tickers"].split(",")
        self.ticker = self.tickers[-1]

        self.risk_manager = None
        self.data_lock = multiprocessing.RLock()
        self.new_data_event: Event = Event()
        self.candles_feed = self.bid_ask_feed = self.level2_feed = None
        if is_candles_feed:
            self.candles_feed = CandlesFeed(config, self.ticker, exchange_provider, self.data_lock, self.new_data_event,
                                            strategy_name)
        if is_level2_feed:
            self.level2_feed = Level2Feed(config, exchange_provider, self.data_lock, self.new_data_event)
        if is_bid_ask_feed:
            self.bid_ask_feed = BidAskFeed(config, exchange_provider, self.data_lock, self.new_data_event)
        # self.learn_data_balancer = LearnDataBalancer()
        self.order_quantity = config["pytrade2.order.quantity"]
        self._logger.info(f"Order quantity: {self.order_quantity}")
        self.price_precision = config["pytrade2.price.precision"]
        self.amount_precision = config["pytrade2.amount.precision"]
        self.learn_interval = pd.Timedelta(config['pytrade2.strategy.learn.interval']) \
            if 'pytrade2.strategy.learn.interval' in config else None
        self._wait_after_loss = pd.Timedelta(config["pytrade2.strategy.riskmanager.wait_after_loss"])
        self.exchange_provider = exchange_provider
        self.model = None
        self.broker = None
        self.is_processing = False

        # Expected profit/loss >= ratio means signal to trade
        self.profit_loss_ratio = config.get("pytrade2.strategy.profitloss.ratio", 1)

        # stop loss should be above price * min_stop_loss_coeff
        # 0.00005 for BTCUSDT 30000 means 1,5
        self.stop_loss_min_coeff = config.get("pytrade2.strategy.stoploss.min.coeff", 0)

        # 0.005 means For BTCUSDT 30 000 max stop loss would be 150
        self.stop_loss_max_coeff = config.get("pytrade2.strategy.stoploss.max.coeff", float('inf'))
        # 0.002 means For BTCUSDT 30 000 max stop loss would be 60
        self.take_profit_min_coeff = config.get("pytrade2.strategy.take.profit.min.coeff", 0)
        self.take_profit_max_coeff = config.get("pytrade2.strategy.take.profit.max.coeff", float('inf'))

        self.history_min_window = pd.Timedelta(config["pytrade2.strategy.history.min.window"])
        self.history_max_window = pd.Timedelta(config["pytrade2.strategy.history.max.window"])

        self.trade_check_interval = timedelta(seconds=30)
        self.last_trade_check_time = datetime.utcnow() - self.trade_check_interval
        self.min_xy_len = 2
        self.X_pipe, self.y_pipe = None, None

        self.processing_interval = pd.Timedelta(config.get('pytrade2.strategy.processing.interval', '30 seconds'))

        self._logger.info("Strategy parameters:\n" + "\n".join(
            [f"{key}: {value}" for key, value in self.config.items() if key.startswith("pytrade2.strategy.")]))

    def run(self):
        exchange_name = self.config["pytrade2.exchange"]
        self.broker = self.exchange_provider.broker(exchange_name)
        if self.candles_feed:
            self.candles_feed.read_candles()
        self.risk_manager = RiskManager(self.broker, self._wait_after_loss)

        # Start main processing loop
        Thread(target=self.processing_loop).start()
        self.broker.run()

        self.learn()
        # # Start periodical jobs
        # if self.learn_interval:
        #     self._logger.info(f"Starting periodical learning, interval: {self.learn_interval}")
        #     Timer(self.learn_interval.seconds, self.learn).start()

    def processing_loop(self):
        self._logger.info("Starting processing loop")

        # If alive is None, not started, so continue loop
        is_alive = self.is_alive()
        while is_alive or is_alive is None:
            try:
                # Wait for new data received
                # while not self.new_data_event.is_set():
                if self.new_data_event:
                    self.new_data_event.wait()
                    self.new_data_event.clear()

                # Learn and predict only if no gap between level2 and bidask
                self.process_new_data()

                if self.processing_interval.total_seconds() > 0:
                    # Delay before next processing cycle
                    time.sleep(self.processing_interval.total_seconds())
                # Refresh live status
                is_alive = self.is_alive()
            except Exception as e:
                logging.exception(e)
                self._logger.error("Exiting")
                exit(1)

        self._logger.info("End main processing loop")

    def is_alive(self):
        maxdelta = self.history_min_window + pd.Timedelta("60s")
        feeds = filter(lambda f: f, [self.candles_feed, self.bid_ask_feed, self.level2_feed])
        is_alive = all([feed.is_alive(maxdelta) for feed in feeds])
        if not is_alive:
            self._logger.info(self.get_report())
            self._logger.error(f"Strategy is not alive for {maxdelta}")
        return is_alive

    def get_info(self) -> dict:
        """ Short info for """
        ...

    def get_report(self) -> dict:
        """ Short info for report """

        report = {}
        # Broker report
        if hasattr(self.broker, "get_report"):
            report.update(self.broker.get_report())
        # Feeds reports
        for feed in filter(lambda f: f, [self.candles_feed, self.bid_ask_feed, self.level2_feed]):
            report.update(feed.get_report())
            # msg.write("\n")
        return report

    def check_cur_trade(self):
        """ Update cur trade if sl or tp reached """
        if not self.broker.cur_trade:
            return

        # Timeout from last check passed
        if datetime.utcnow() - self.last_trade_check_time >= self.trade_check_interval:
            self.broker.update_cur_trade_status()
            self.last_trade_check_time = datetime.utcnow()

    def can_learn(self) -> bool:
        """ Check preconditions for learning"""
        feeds = filter(lambda f: f, [self.candles_feed, self.bid_ask_feed, self.level2_feed])
        status = {feed.__class__.__name__: feed.has_min_history() for feed in feeds}
        has_min_history = all([f for f in status.values()])
        if not has_min_history:
            self._logger.info(f"Can not learn because some datasets have not enough data. Filled status {status}")
        return has_min_history

    def create_model(self, x_size, y_size):
        raise NotImplementedError()

    def create_pipe(self, X, y) -> (Pipeline, Pipeline):
        """ Create feature and target pipelines to use for transform and inverse transform """

        time_cols = [col for col in X.columns if col.startswith("time")]
        float_cols = list(set(X.columns) - set(time_cols))

        x_pipe = Pipeline(
            [("xscaler", ColumnTransformer([("xrs", StandardScaler(), float_cols)], remainder="passthrough")),
             ("xmms", MaxAbsScaler())])
        x_pipe.fit(X)

        y_pipe = Pipeline(
            [("yrs", StandardScaler()),
             ("ymms", MaxAbsScaler())])
        y_pipe.fit(y)
        return x_pipe, y_pipe

    def prepare_xy(self):
        raise NotImplementedError("prepare_Xy")

    def learn(self):
        try:
            self.apply_buffers()
            self._logger.debug("Learning")
            if not self.can_learn():
                return

            train_X, train_y = self.prepare_xy()

            # Metrics
            train_period_sec = (train_X.index.max() - train_X.index.min()).total_seconds()
            MetricServer.metrics.strategy.learn.train_period_sec.set(train_period_sec)

            self._logger.info(
                f"Learning on last data. Train data len: {train_X.shape[0]} from {min(train_X.index)} to {max(train_X.index)}")
            if len(train_X.index) >= self.min_xy_len:
                start_time = datetime.utcnow()
                if not (self.X_pipe and self.y_pipe):
                    self.X_pipe, self.y_pipe = self.create_pipe(train_X, train_y)
                # Final scaling and normalization
                self.X_pipe.fit(train_X)
                self.y_pipe.fit(train_y)

                X_trans, y_trans = self.X_pipe.transform(train_X), self.y_pipe.transform(train_y)
                # If x window transformation applied, x size reduced => adjust y
                y_trans = y_trans[-X_trans.shape[0]:]

                # Get or create model, parameters
                if not self.model:
                    self.model, params = self.model_persister.get_last_trade_ready_model(self.model_name)
                    if not self.model:
                        self.model = self.create_model(X_trans.shape[-1], y_trans.shape[-1])
                    if params:
                        self.apply_params(params)

                # Train
                self.model.fit(X_trans, y_trans)

                # Save weights and xy new delta
                # todo: uncomment
                self.model_persister.save_model(self.model)

                # to avoid OOM
                tensorflow.keras.backend.clear_session()
                gc.collect()
                self._logger.info("Learning completed")
                learn_duration = datetime.utcnow() - start_time
                MetricServer.metrics.strategy.learn.train_exec_duration_sec.set(learn_duration.total_seconds())

            else:
                self._logger.info(f"Not enough train data to learn should be >= {self.min_xy_len}")
        finally:
            if self.learn_interval:
                Timer(self.learn_interval.seconds, self.learn).start()

    def apply_params(self, params: dict) -> None:
        """ After last model and params read from mlflow, apply params to strategy"""
        ...

    def prepare_last_x(self):
        raise NotImplementedError("prepare_Xy")

    def predict(self, x: pd.DataFrame):
        raise NotImplementedError()

    def apply_buffers(self):
        # Append new data from buffers to main data frames
        with (self.data_lock):
            save_dict = {}
            # Form saving dict structure and copy from buffers to main datasets
            if self.bid_ask_feed:
                save_dict["raw_bid_ask"] = self.bid_ask_feed.bid_ask_buf
                self.bid_ask_feed.apply_buf()
            # save_dict = {**{"raw_bid_ask": self.bid_ask_feed.bid_ask_buf},
            if self.candles_feed:
                save_dict.update({f"raw_candles_{period}": buf for period, buf in
                                  self.candles_feed.candles_by_interval_buf.items()})
                self.candles_feed.apply_buf()
            if self.level2_feed:
                # Don't call save_dict.update() because Level 2 is too big, don't save, just apply buf
                self.level2_feed.apply_buf()

            self.data_persister.save_last_data(self.ticker, save_dict)

    def process_new_data(self):
        self.apply_buffers()

        if self.model and not self.is_processing:
            try:
                self.is_processing = True
                x = self.prepare_last_x()
                # x can be dataframe or np array, check is it empty
                if (hasattr(x, 'empty') and x.empty) or (hasattr(x, 'shape') and x.shape[0] == 0):
                    self._logger.info('Cannot process new data: features are empty. ')
                    return
                # Predict
                y_pred = self.predict(x)

                # Update current trade status
                self.check_cur_trade()

                # Open or close or do nothing
                self.process_prediction(y_pred)

                # Save to disk for analysis
                self.data_persister.save_last_data(self.ticker, {'y_pred': y_pred})
            except Exception as e:
                self._logger.error(f"{e}. Traceback: {traceback.format_exc()}")
            finally:
                self.is_processing = False

    def process_prediction(self, y_pred):
        raise NotImplementedError()
