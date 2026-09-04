# Market.Data.Filter
Filters Normalized Market Data Messages using a WatchList

# Benchmark Description
-  # of Symbols we are filtering in (Size of watchlist)
-  # of existing order per item on WatchList
-  Time it takes to filter out an Order
-  Time it takes to filter in an Order for each security


2 types of messages of interest
- AddOrder which explicitly has the symbol/ticker embedded within itself
- Other messages which only contain the OrderId

We are expecting Orders to come in randomly


Results:
For a watchlist of 5 symbols, and the following makeup of existing orders:
- Symbol_1 500 orders
- Symbol_2 250 orders
- Symbol_3 100 orders
- Symbol_4 150 orders
- Symbol_5 900 orders

It takes on average:
- x clock cycles to filter an AddOrder Message
  - AddOrder message whose Symbol is in the watchlist
  - AddOrder message whose Symbol is not in the watchlist
- y clock cycles to filter a non-AddOrder Message
  - OrderId whose corresponding Symbol is in the watchlist
  - OrderId whose corresponding Symbol is not in the watchlist


So now we want to generate the above condition(s), and run 4 tests to measure
the expected latencies/times.


