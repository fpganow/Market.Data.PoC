from hamcrest import assert_that, contains_string, equal_to, has_length, starts_with
from unittest import TestCase


from filter_msg_gen import FilterBench


class TestCommandGenerator(TestCase):
    def test_basic_config_from_file(self):
        # GIVEN
        config_toml = 'sim/bench_1.cfg'

        # Construct/set up FilterBench
        filter_bench = FilterBench(path_or_str='fake_path.cfg',
                                   backup_path=config_toml)

        assert_that(filter_bench.has_more_commands(), equal_to(True))

        assert_that(filter_bench.name(), equal_to('Benchmark #1'))
        assert_that(filter_bench.description(), starts_with('This is my description'))
        assert_that(filter_bench.watch_list(), has_length(2))

        assert_that(filter_bench.number_of_messages(), equal_to(100))


    def test_basic_config_from_string_watchlist(self):
        # GIVEN
        config_toml = """\
name = "Test 1 Security"
description = '''
benchmark_name
Test how long it takes
for one string
'''
watchlist = [
  "MSFT",
  "AAPL"
]
[generator]
number_of_messages = 500
msgs_p_second = 10

[[security]]
symbol = "TSLA"
weight = 0.25
book_size_range = [5, 10]
price_range = [75.00, 125.00]
size_range = [25, 200]

[[security]]
symbol = "MSFT"

# Comment
[messages]
csv=[
[    'Type', 'Side',  'OrderId', 'Quantity', 'Symbol', 'Price', 'Exe Quantity', 'Can Quantity', 'Rem Quantity', 'Seconds', 'Nanoseconds',  'Op', 'SeqNo'],
['AddOrder',    'B', 'ORID0001',        150,   'AAPL',  172.75,              0,              0,              0,       100,             0, 'add',       1],
['AddOrder',    'B', 'ORID0002',         50,   'MSFT',  404.52,              0,              0,              0,       100,             0, 'add',       2],
['AddOrder',    'B', 'ORID0003',        250,   'AAPL',  172.76,              0,              0,              0,       100,             0, 'add',       3],
['AddOrder',    'B', 'ORID0004',        150,   'MSFT',  404.53,              0,              0,              0,       100,             0, 'add',       4],
]
"""

        # Construct/set up FilterBench
        filter_bench = FilterBench(path_or_str=config_toml)

        assert_that(filter_bench.has_more_commands(), equal_to(True))

        assert_that(filter_bench.name(), equal_to('Test 1 Security'))
        assert_that(filter_bench.description(), starts_with('benchmark_name\nTest how long'))
        assert_that(filter_bench.watch_list(), has_length(2))

        assert_that(filter_bench.print_header(), contains_string('benchmark_name'))

        assert_that(filter_bench.number_of_messages(), equal_to(500))


class TestWatchList(TestCase):
    def test_get_single_watchlist(self):
        # GIVEN
        config_toml = 'sim/bench_1.cfg'

        # Construct/set up FilterBench
        filter_bench = FilterBench(path_or_str=config_toml)
        watchlist_words = []

        # WHEN
        watchlist_size = filter_bench.watchlist_get_size()
        for i in range(watchlist_size):
            watchlist_words.append(filter_bench.watchlist_get_item(i))

        # THEN
        assert_that(watchlist_size, equal_to(2))
        assert_that(watchlist_words, has_length(2))
        assert_that(watchlist_words[0], equal_to(0x4d53465420202020))
        assert_that(watchlist_words[1], equal_to(0x4141504c20202020))

        # Type
        #  Time
        #  AddOrder
        #  OrderExecuted
        #  OrderExecutedAtPriceSize
        #  ReduceSize
        #  ModifyOrder
        #  DeleteOrder
        #  Get.Everything
        #  Get.All.Orders
        #  Get.Top

        # SerializeCommand
        # [0] type
        # side
        # orderid
        # quantity
        # symbol
        # price
        # exe.qty
        # can.qty
        # rem.qty
        # seconds
        # nanoseconds
        # [11] add
        # [12] edit
        # [13] remove

