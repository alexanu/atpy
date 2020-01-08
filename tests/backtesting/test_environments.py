import unittest

from atpy.backtesting.environments import *
from atpy.data.iqfeed.iqfeed_postgres_cache import *
from pyevents.events import SyncListeners


class TestEnvironments(unittest.TestCase):

    def test_postgre_ohlc(self):
        logging.basicConfig(level=logging.INFO)

        listeners = SyncListeners()

        dre = data_replay_events(listeners)
        data_event_stream = dre.event_filter()
        event_stream_1d, filter_1d = add_postgres_ohlc_1d(dre, bgn_prd=datetime.datetime.now() - relativedelta(months=2))
        event_stream_5m, filter_5m = add_postgres_ohlc_5m(dre, bgn_prd=datetime.datetime.now() - relativedelta(months=2))
        add_current_period(listeners, filter_5m)
        add_current_phase(data_event_stream)
        add_daily_log(data_event_stream)
        add_rolling_mean(event_stream_1d, window=5)
        add_gaps(listeners, filter_1d)

        dct = {'bars_5m': 0, 'bars_1d': 0, 'latest_5m': None, 'latest_1d': None, 'phases': set(), 'periods': set(), 'phase_start': False}

        def asserts(e):
            if e['type'] == 'data':
                self.assertTrue(isinstance(e, dict))

                if 'bars_5m' in e:
                    self.assertTrue(isinstance(e['bars_5m'], pd.DataFrame))
                    self.assertFalse(e['bars_5m'].empty)
                    dct['bars_5m'] += 1

                    if dct['latest_5m'] is not None:
                        self.assertGreater(e['bars_5m'].iloc[-1].name[0], dct['latest_5m'])

                    dct['latest_5m'] = e['bars_5m'].iloc[-1].name[0]
                    self.assertTrue('bars_5m_current_period' in e)
                    self.assertTrue('period_name' in e)
                    dct['periods'].add(e['period_name'])

                    if e['period_start'] is True:
                        dct['period_start'] = True

                if 'bars_1d' in e:
                    self.assertTrue(isinstance(e['bars_1d'], pd.DataFrame))
                    self.assertFalse(e['bars_1d'].empty)
                    self.assertTrue('close_rm_5' in e['bars_1d'].columns)
                    dct['bars_1d'] += 1

                    if dct['latest_1d'] is not None:
                        self.assertGreater(e['bars_1d'].iloc[-1].name[0], dct['latest_1d'])

                    dct['latest_1d'] = e['bars_1d'].iloc[-1].name[0]

                    self.assertTrue('bars_1d_gaps' in e)
                    self.assertTrue('current_phase' in e)

                    dct['phases'].add(e['current_phase'])

                    if e['phase_start'] is True:
                        dct['phase_start'] = True

        listeners += asserts
        dre.start()

        self.assertGreater(dct['bars_5m'], 0)
        self.assertGreater(dct['bars_1d'], 0)
        self.assertIsNotNone(dct['latest_5m'])
        self.assertIsNotNone(dct['latest_1d'])
        self.assertEqual(dct['periods'], {'trading-hours', 'after-hours'})
        self.assertTrue(dct['period_start'])

    # TODO
    def test_postgre_backtest(self):
        logging.basicConfig(level=logging.INFO)

        listeners = SyncListeners()

        dre = data_replay_events(listeners)

        event_stream_1m, filter_1m = add_postgres_ohlc_1m(dre, bgn_prd=datetime.datetime.now() - relativedelta(years=10))

        strategy = add_random_strategy(listeners,
                                       portfolio_manager=None,
                                       bar_event_stream=event_stream_1m)

        me = add_mock_exchange(listeners,
                               order_requests_stream=strategy.order_requests_stream(),
                               bar_event_stream=event_stream_1m,
                               slippage_loss_ratio=0.1,
                               commission_per_share=0.05)

        pm = add_portfolio_manager(listeners=listeners,
                                   fulfilled_orders_stream=me.fulfilled_orders_stream(),
                                   bar_event_stream=event_stream_1m,
                                   initial_capital=10000000)

        strategy.portfolio_manager = pm

        add_daily_log(dre.event_filter())

        dct = {'bars_1m': 0, 'latest_1m': None}

        # def asserts(e):
        #     if e['type'] == 'data':
        #         self.assertTrue(isinstance(e, dict))
        #
        #         if 'bars_1m' in e:
        #             self.assertTrue(isinstance(e['bars_1m'], pd.DataFrame))
        #             self.assertFalse(e['bars_1m'].empty)
        #             dct['bars_1m'] += 1
        #
        #             if dct['latest_1m'] is not None:
        #                 self.assertGreater(e['bars_1m'].iloc[-1].name[0], dct['latest_1m'])
        #
        #             dct['latest_1m'] = e['bars_1m'].iloc[-1].name[0]
        #
        # listeners += asserts
        dre.start()

        self.assertGreater(dct['bars_1m'], 0)

    def test_postgre_ohlc_quandl_sf0(self):
        logging.basicConfig(level=logging.INFO)

        listeners = SyncListeners()

        dre = data_replay_events(listeners)
        data_event_stream = dre.event_filter()

        event_stream_1d, filter_1d = add_postgres_ohlc_1d(dre, bgn_prd=datetime.datetime.now() - relativedelta(months=2))
        add_daily_log(data_event_stream)
        add_current_period(listeners, filter_1d)
        add_quandl_sf(dre, bgn_prd=datetime.datetime.now() - relativedelta(years=2))

        dct = {'bars_1d': 0, 'quandl_sf0': 0, 'latest_1d': None, 'latest_quandl_sf0': None}

        def asserts(e):
            if e['type'] == 'data':
                self.assertTrue(isinstance(e, dict))

                if 'bars_1d' in e:
                    self.assertTrue(isinstance(e['bars_1d'], pd.DataFrame))
                    self.assertFalse(e['bars_1d'].empty)
                    dct['bars_1d'] += 1

                    if dct['latest_1d'] is not None:
                        self.assertGreater(e['bars_1d'].iloc[-1].name[0], dct['latest_1d'])

                    dct['latest_1d'] = e['bars_1d'].iloc[-1].name[0]

                if 'quandl_sf0' in e:
                    self.assertTrue(isinstance(e['quandl_sf0'], pd.DataFrame))
                    self.assertFalse(e['quandl_sf0'].empty)
                    dct['quandl_sf0'] += 1

                    if dct['latest_quandl_sf0'] is not None:
                        self.assertGreater(e['quandl_sf0'].iloc[-1].name[0], dct['latest_quandl_sf0'])

                    dct['latest_quandl_sf0'] = e['quandl_sf0'].iloc[-1].name[0]

        listeners += asserts
        dre.start()

        self.assertGreater(dct['bars_1d'], 0)
        self.assertGreater(dct['quandl_sf0'], 0)
        self.assertIsNotNone(dct['latest_1d'])
        self.assertIsNotNone(dct['latest_quandl_sf0'])


if __name__ == '__main__':
    unittest.main()
