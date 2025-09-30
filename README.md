Algorithmic Trading Bot

Overview
This algorithmic trading system is a Python-based application that executes quantitative trading strategies in real-time across seven financial instruments (BOND, XLF, VALE, VALBZ, GS, MS, WFC). The bot connects to an exchange via socket connections and processes live market data to identify and exploit pricing inefficiencies, handling over 500 messages per second while maintaining accurate position tracking and risk controls.

Trading Strategies
The system implements three concurrent strategies. The first is statistical arbitrage on XLF ETF and its underlying basket. XLF comprises three units of BOND, two units of GS, three units of MS, and two units of WFC. When XLF trades at a discount relative to its constituent stocks (specifically when ten XLF units plus the 100-point conversion fee costs less than the basket value), the system converts XLF shares into underlying stocks and sells them at market prices, capturing the price discrepancy.
The second strategy provides market making using rolling five-period moving averages. The bot places simultaneous buy and sell orders around these averages, with spread widths varying by instrument. XLF uses a three-tick spread due to higher volatility, while WFC, GS, and MS use tighter one-tick spreads. As new trades occur, moving averages update continuously and the bot adjusts its quotes accordingly.
The third strategy implements pairs trading between VALE and VALBZ, two correlated instruments representing the same underlying asset on different exchanges. When the spread between their five-period moving averages exceeds 30 ticks, the bot executes a mean-reversion trade by buying the cheaper instrument, converting it, and selling the expensive one.

Risk Management
The system enforces position limits for every instrument (100 shares for most instruments, 10 for VALE/VALBZ) to cap maximum exposure. Before executing trades, the bot verifies that position limits won't be exceeded. Order throttling implements a 100-millisecond cooldown between orders per symbol, preventing exchange rate limiting and allowing existing orders time to fill. The system requires a minimum of three historical price points before generating trading signals, ensuring decisions are based on sufficient data.
Technical Implementation
Built entirely with Python's standard library, the system uses a state manager class that tracks all open positions, pending orders, and order lifecycle states. Communication occurs through TCP socket connections transmitting JSON-formatted messages. Orders progress through states: unacknowledged (sent but not confirmed), open (live in the order book), and out (filled or cancelled). Price history uses efficient deque data structures with automatic eviction, storing the five most recent trades per instrument for constant-time moving average calculations.

Usage
Run python trading_bot.py --test prod-like for testing or python trading_bot.py --production for live trading. Configuration parameters like position limits (POSITION_LIMITS dictionary) and order throttling (ORDER_COOLDOWN constant) can be adjusted at the top of the source file. The system requires Python 3.x with no external dependencies.
Performance

The system achieves order submission latency under 100 milliseconds and processes 500+ messages per second. The event-driven architecture maintains causal consistency by processing market events in received order. Trading activity varies with market conditions—market making generates steady order flow while arbitrage and pairs trading activate opportunistically when specific pricing conditions occur.
