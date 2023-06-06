import logging

from huobi.client.account import AccountClient
from huobi.client.algo import AlgoClient
from huobi.client.market import MarketClient
from huobi.client.trade import TradeClient
from huobi.connection.impl.websocket_manage import WebsocketManage
from huobi.utils import PrintBasic

from exch.huobi.broker.HuobiBroker import HuobiBroker
from exch.huobi.feed.HuobiCandlesFeed import HuobiCandlesFeed
from exch.huobi.feed.HuobiWebsocketFeed import HuobiWebsocketFeed


class HuobiExchange:
    def __init__(self, config: dict):
        # Apply fixes to reduce rubbish in logs
        PrintBasic.print_basic = lambda data, name: None  # Supress hiobi api print response ts for each response
        WebsocketManage.on_close = lambda msg: self._log.info("Web socket on close called")

        self._log = logging.getLogger(self.__class__.__name__)
        self.config = config

        # Attrs for lazy initialization
        self.__market_client: MarketClient = None
        self.__trade_client: TradeClient = None
        self.__algo_client: AlgoClient = None
        self.__account_client: AccountClient = None
        self.__broker: HuobiBroker = None
        self.__websocket_feed: HuobiWebsocketFeed = None
        self.__candles_feed: HuobiCandlesFeed = None
        # Supress rubbish logging
        logging.getLogger('apscheduler.executors.default').setLevel(logging.WARNING)

    def websocket_feed(self) -> HuobiWebsocketFeed:
        """ Binance websocket feed lazy creation """
        if not self.__websocket_feed:
            self.__websocket_feed = HuobiWebsocketFeed(config=self.config, market_client=self._market_client())
        return self.__websocket_feed

    def candles_feed(self) -> HuobiCandlesFeed:
        """ Binance candles feed lazy creation """
        if not self.__candles_feed:
            self.__candles_feed = HuobiCandlesFeed(self._market_client())
        return self.__candles_feed

    def broker(self) -> HuobiBroker:
        """ Binance broker lazy creation """
        if not self.__broker:
            self.__broker = HuobiBroker(config=self.config,
                                        account_client=self._account_client(),
                                        trade_client=self._trade_client(),
                                        market_client=self._market_client(),
                                        algo_client=self._algo_client())
        return self.__broker

    def _key_secret(self):
        key = self.config["pytrade2.exchange.huobi.connector.key"]
        secret = self.config["pytrade2.exchange.huobi.connector.secret"]
        return key, secret

    def _market_client(self):
        if not self.__market_client:
            key, secret = self._key_secret()
            # url = self.config.get("pytrade2.exchange.huobi.market.client.url")
            self._log.info(f"Creating huobi market client, key: ***{key[-3:]}, secret: ***{secret[-3:]}")
            self.__market_client = MarketClient(api_key=key, secret_key=secret, init_log=True)
        return self.__market_client

    def _trade_client(self):
        """ Huobi trade client creation."""
        if not self.__trade_client:
            key, secret = self._key_secret()
            # url = self.config.get("pytrade2.exchange.huobi.trade.client.url")
            self._log.info(f"Creating huobi trade client, key: ***{key[-3:]}, secret: ***{secret[-3:]}")
            self.__trade_client = TradeClient(api_key=key, secret_key=secret, init_log=True)
        return self.__trade_client

    def _algo_client(self):
        """ Huobi algo client creation."""
        if not self.__algo_client:
            key, secret = self._key_secret()
            # url = self.config.get("pytrade2.exchange.huobi.trade.client.url")
            self._log.info(f"Creating huobi algo trade client, key: ***{key[-3:]}, secret: ***{secret[-3:]}")
            self.__algo_client = AlgoClient(api_key=key, secret_key=secret, init_log=True)
        return self.__algo_client

    def _account_client(self):
        if not self.__account_client:
            key, secret = self._key_secret()
            # url = self.config.get("pytrade2.exchange.huobi.account.client.url")
            self._log.info(f"Creating huobi account client, key: ***{key[-3:]}, secret: ***{secret[-3:]}")
            self.__account_client = AccountClient(api_key=key, secret_key=secret, init_log=True)
        return self.__account_client