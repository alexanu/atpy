import collections
import datetime
import pickle

import lmdb

import atpy.data.iqfeed.util as iqfeedutil
import pyevents.events as events
from atpy.data.iqfeed.filters import *
from atpy.data.iqfeed.util import *
import typing
import pandas as pd


class TicksFilter(NamedTuple):
    """
    Ticks filter parameters
    """

    ticker: typing.Union[list, str]
    max_ticks: int
    ascend: bool
    timeout: int

TicksFilter.__new__.__defaults__ = (False, None)


class TicksForDaysFilter(NamedTuple):
    """
    Ticks for days filter parameters
    """

    ticker: typing.Union[list, str]
    num_days: int
    bgn_flt: datetime.time
    end_flt: datetime.time
    ascend: bool
    max_ticks: int
    timeout: int

TicksForDaysFilter.__new__.__defaults__ = (None, None, False, None, None)


class TicksInPeriodFilter(NamedTuple):
    """
    Ticks in period filter parameters
    """

    ticker: typing.Union[list, str]
    bgn_prd: datetime.datetime
    end_prd: datetime.datetime
    bgn_flt: datetime.time
    end_flt: datetime.time
    ascend: bool
    max_ticks: int
    timeout: int

TicksInPeriodFilter.__new__.__defaults__ = (None, None, False, None, None)


class BarsFilter(NamedTuple):
    """
    Bars filter parameters
    """

    ticker: typing.Union[list, str]
    interval_len: int
    interval_type: str
    max_bars: int
    ascend: bool
    timeout: int

BarsFilter.__new__.__defaults__ = (False, None)


class BarsForDaysFilter(NamedTuple):
    """
    Bars for days filter parameters
    """

    ticker: typing.Union[list, str]
    interval_len: int
    interval_type: str
    days: int
    num_days: int
    bgn_flt: datetime.time
    end_flt: datetime.time
    ascend: bool
    max_bars: int
    timeout: int

BarsForDaysFilter.__new__.__defaults__ = (None, None, False, None, None)


class BarsInPeriodFilter(NamedTuple):
    """
    Bars in period filter parameters
    """

    ticker: typing.Union[list, str]
    interval_len: int
    interval_type: str
    bgn_prd: datetime.datetime
    end_prd: datetime.datetime
    bgn_flt: datetime.time
    end_flt: datetime.time
    ascend: bool
    max_ticks: int
    timeout: int

TicksInPeriodFilter.__new__.__defaults__ = (None, None, False, None, None)


class BarsDailyFilter(NamedTuple):
    """
    Daily bars filter parameters
    """

    ticker: typing.Union[list, str]
    num_days: int
    ascend: bool = False
    timeout: int = None

BarsDailyFilter.__new__.__defaults__ = (False, None)


class BarsDailyForDatesFilter(NamedTuple):
    """
    Daily bars for dates filter parameters
    """

    ticker: typing.Union[list, str]
    bgn_dt: datetime.date
    end_dt: datetime.date
    ascend: bool = False
    max_days: int = None
    timeout: int = None

BarsDailyForDatesFilter.__new__.__defaults__ = (False, None, None)


class BarsWeeklyFilter(NamedTuple):
    """
    Weekly bars filter parameters
    """

    ticker: typing.Union[list, str]
    num_weeks: int
    ascend: bool
    timeout: int

BarsWeeklyFilter.__new__.__defaults__ = (False, None)


class BarsMonthlyFilter(NamedTuple):
    """
    Monthly bars filter parameters
    """

    ticker: typing.Union[list, str]
    num_months: int
    ascend: bool
    timeout: int

BarsMonthlyFilter.__new__.__defaults__ = (False, None)


class IQFeedHistoryListener(object, metaclass=events.GlobalRegister):
    """
    IQFeed historical data listener. See the unit test on how to use
    """

    def __init__(self, minibatch=None, fire_batches=False, fire_ticks=False, column_mode=True, key_suffix='', filter_provider=DefaultFilterProvider(), lmdb_path=None):
        """
        :param minibatch: size of the minibatch
        :param fire_batches: raise event for each batch
        :param fire_ticks: raise event for each tick
        :param column_mode: whether to organize the data in columns or rows
        :param key_suffix: suffix for field names
        :param filter_provider: news filter list
        :param lmdb_path: path to lmdb database. If not None, then the data is cached
        """
        self.minibatch = minibatch
        self.fire_batches = fire_batches
        self.fire_ticks = fire_ticks
        self.column_mode = column_mode
        self.key_suffix = key_suffix
        self.current_minibatch = None
        self.filter_provider = filter_provider

        self.db = lmdb.open(lmdb_path) if lmdb_path is not None else None

        self.conn = None

    def __enter__(self):
        iqfeedutil.launch_service()
        self.conn = iq.HistoryConn()
        self.conn.connect()
        self.is_running = True
        self.producer_thread = threading.Thread(target=self.produce, daemon=True)
        self.producer_thread.start()

        return self

    def __exit__(self, exception_type, exception_value, traceback):
        self.conn.disconnect()
        self.conn = None
        self.is_running = False

    def __del__(self):
        if self.conn is not None:
            self.conn.disconnect()
            self.cfg = None

    def __getattr__(self, name):
        if self.conn is not None:
            return getattr(self.conn, name)
        else:
            raise AttributeError

    def produce(self):
        for f in self.filter_provider:
            if isinstance(f.ticker, str):
                self._produce_signal(f)
            elif isinstance(f.ticker, list):
                self._produce_signals(f)

            if not self.is_running:
                return

    def _produce_signal(self, f):
        data = self._request_data(f)

        event_type = self._event_type(f)

        for datum in data:
            if self.fire_ticks:
                self.process_datum({'type': event_type, 'data': self._process_data(iqfeedutil.iqfeed_to_dict(datum, self.key_suffix), f)})

            if self.minibatch is not None:
                self.current_minibatch = self.current_minibatch if self.current_minibatch is not None else list()
                self.current_minibatch.append(datum)

                if len(self.current_minibatch) == self.minibatch:
                    mb_data = self._process_data(iqfeedutil.create_batch(self.current_minibatch, self.column_mode, self.key_suffix), f)
                    self.process_minibatch({'type': event_type + '_mb', 'data': mb_data})
                    self.current_minibatch = list()

        if self.fire_batches:
            batch_data = self._process_data(iqfeedutil.create_batch(data, self.column_mode, self.key_suffix), f)
            self.process_batch({'type': event_type + '_batch', 'data': batch_data})

    def _produce_signals(self, f):
        signals = dict()
        filters = dict()
        length = None
        for t in f.ticker:
            filters[t] = f._replace(ticker=t)
            d = self._request_data(filters[t])

            length = length if length is not None else len(d)

            if len(d) != length:
                raise Exception("Signal point count doesn't match other signals")

            signals[t] = d

        event_type = self._event_type(f)

        for i in range(length):
            if self.fire_ticks:
                datum = dict()
                for t in f.ticker:
                    datum[t] = self._process_data(iqfeedutil.iqfeed_to_dict(signals[t][i], self.key_suffix), filters[t])

                self.process_datum({'type': event_type, 'data': datum})

            if self.minibatch is not None:
                self.current_minibatch = self.current_minibatch if self.current_minibatch is not None else dict()

                for t in f.ticker:
                    if t not in self.current_minibatch:
                        self.current_minibatch[t] = list()

                    self.current_minibatch[t].append(signals[t][i])

            if len(self.current_minibatch[f.ticker[0]]) == self.minibatch:
                mb_signals = dict()
                for t in f.ticker:
                    mb_signals[t] = pd.DataFrame.from_dict(self._process_data(iqfeedutil.create_batch(self.current_minibatch[t], True, self.key_suffix), filters[t]))

                mb_data = pd.Panel.from_dict(mb_signals)
                self.process_minibatch({'type': event_type + '_mb', 'data': mb_data})
                self.current_minibatch = None

        if self.fire_batches:
            batch_signals = dict()
            for t in f.ticker:
                batch_signals[t] = pd.DataFrame.from_dict(self._process_data(iqfeedutil.create_batch(signals[t], True, self.key_suffix), filters[t]))

            batch = pd.Panel.from_dict(batch_signals)
            self.process_batch({'type': event_type + '_batch', 'data': batch})

    def _request_data(self, f):
        if isinstance(f, TicksFilter):
            method = self.conn.request_ticks
        elif isinstance(f, TicksForDaysFilter):
            method = self.conn.request_ticks_for_days
        elif isinstance(f, TicksInPeriodFilter):
            method = self.conn.request_ticks_in_period
        elif isinstance(f, BarsFilter):
            method = self.conn.request_bars
        elif isinstance(f, BarsForDaysFilter):
            method = self.conn.request_bars_for_days
        elif isinstance(f, BarsInPeriodFilter):
            method = self.conn.request_bars_in_period
        elif isinstance(f, BarsDailyFilter):
            method = self.conn.request_daily_data
        elif isinstance(f, BarsDailyForDatesFilter):
            method = self.conn.request_daily_data_for_dates
        elif isinstance(f, BarsWeeklyFilter):
            method = self.conn.request_weekly_data
        elif isinstance(f, BarsMonthlyFilter):
            method = self.conn.request_monthly_data

        if self.db is not None:
            with self.db.begin() as txn:
                data = txn.get(bytearray(f.__str__(), encoding='ascii'))

            if data is None:
                data = method(*f)

                with self.db.begin(write=True) as txn:
                    txn.put(bytearray(f.__str__(), encoding='ascii'), pickle.dumps(data))
            else:
                data = pickle.loads(data)
        else:
            data = method(*f)

        return data

    def _process_data(self, data, data_filter):
        if isinstance(data_filter, TicksFilter) or isinstance(data_filter, TicksForDaysFilter) or isinstance(data_filter, TicksInPeriodFilter):
            return self._process_ticks_data(data, data_filter)
        elif isinstance(data_filter, BarsFilter) or isinstance(data_filter, BarsForDaysFilter) or isinstance(data_filter, BarsInPeriodFilter):
            return self._process_bars_data(data, data_filter)
        elif isinstance(data_filter, BarsDailyFilter) or isinstance(data_filter, BarsDailyForDatesFilter) or isinstance(data_filter, BarsWeeklyFilter) or isinstance(data_filter, BarsMonthlyFilter):
            return self._process_daily_data(data, data_filter)

    def _process_ticks_data(self, data, data_filter):
        if isinstance(data, dict):
            result = dict()

            result['Date'] = data.pop('date')
            result['Time'] = data.pop('time')
            result['Last'] = data.pop('last')
            result['Last Size'] = data.pop('last_sz')
            result['Total Volume'] = data.pop('tot_vlm')
            result['Bid'] = data.pop('bid')
            result['Ask'] = data.pop('ask')
            result['TickID'] = data.pop('tick_id')
            result['Basis For Last'] = data.pop('last_type')
            result['Trade Market Center'] = data.pop('mkt_ctr')
            result['cond1'] = data.pop('cond1')
            result['cond2'] = data.pop('cond2')
            result['cond3'] = data.pop('cond3')
            result['cond4'] = data.pop('cond4')

            if isinstance(result['Date'], collections.Iterable):
                result['Symbol'] = [data_filter.ticker] * len(result['Date'])
            else:
                result['Symbol'] = data_filter.ticker
        elif isinstance(data, collections.Iterable):
            result = list()
            for d in data:
                result.append(self._process_ticks_data(d, data_filter))

        return result

    def _process_bars_data(self, data, data_filter):
        if isinstance(data, dict):
            result = dict()

            result['Date'] = data.pop('date')
            result['Time'] = data.pop('time')
            result['High'] = data.pop('high_p')
            result['Low'] = data.pop('low_p')
            result['Open'] = data.pop('open_p')
            result['Close'] = data.pop('close_p')
            result['Total Volume'] = data.pop('tot_vlm')
            result['Period Volume'] = data.pop('prd_vlm')
            result['Number of Trades'] = data.pop('num_trds')

            if isinstance(result['Date'], collections.Iterable):
                result['Symbol'] = [data_filter.ticker] * len(result['Date'])
            else:
                result['Symbol'] = data_filter.ticker
        elif isinstance(data, collections.Iterable):
            result = list()
            for d in data:
                result.append(self._process_bars_data(d, data_filter))

        return result

    def _process_daily_data(self, data, data_filter):
        if isinstance(data, dict):
            result = dict()

            result['Date'] = data.pop('date')
            result['High'] = data.pop('high_p')
            result['Low'] = data.pop('low_p')
            result['Open'] = data.pop('open_p')
            result['Close'] = data.pop('close_p')
            result['Period Volume'] = data.pop('prd_vlm')
            result['Open Interest'] = data.pop('open_int')

            if isinstance(result['Date'], collections.Iterable):
                result['Symbol'] = [data_filter.ticker] * len(result['Date'])
            else:
                result['Symbol'] = data_filter.ticker
        elif isinstance(data, collections.Iterable):
            result = list()
            for d in data:
                result.append(self._process_daily_data(d, data_filter))

        return result

    @staticmethod
    def _event_type(data_filter):
        if isinstance(data_filter, TicksFilter) or isinstance(data_filter, TicksForDaysFilter) or isinstance(data_filter, TicksInPeriodFilter):
            return 'level_1_tick'
        elif isinstance(data_filter, BarsFilter) or isinstance(data_filter, BarsForDaysFilter) or isinstance(data_filter, BarsInPeriodFilter):
            return 'bar'
        elif isinstance(data_filter, BarsDailyFilter) or isinstance(data_filter, BarsDailyForDatesFilter) or isinstance(data_filter, BarsWeeklyFilter) or isinstance(data_filter, BarsMonthlyFilter):
            return 'daily'

    @events.after
    def process_datum(self, data):
        return data

    @events.after
    def process_batch(self, data):
        return data

    def batch_provider(self):
        return IQFeedDataProvider(self.process_batch)

    @events.after
    def process_minibatch(self, data):
        return data

    def minibatch_provider(self):
        return IQFeedDataProvider(self.process_minibatch)
