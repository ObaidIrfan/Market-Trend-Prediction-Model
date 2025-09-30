import argparse
from collections import deque
from enum import Enum
import time
import socket
import json
from itertools import chain


team_name = "MANKEY"

# Global price tracking with proper structure
price_history = {
    'XLF': deque(maxlen=5),
    'WFC': deque(maxlen=5),
    'GS': deque(maxlen=5),
    'MS': deque(maxlen=5),
    'VALE': deque(maxlen=5),
    'VALBZ': deque(maxlen=5)
}

# Throttling to prevent excessive order sending
last_order_time = {}
ORDER_COOLDOWN = 0.1  # 100ms between orders per symbol

# Position limits
POSITION_LIMITS = {
    'BOND': 100,
    'XLF': 100,
    'WFC': 100,
    'GS': 100,
    'MS': 100,
    'VALE': 10,
    'VALBZ': 10
}

def on_startup(state_manager):
    """Initialize with a safe BOND position"""
    state_manager.send_order("BOND", "BUY", 999, 10)


def should_send_order(symbol):
    """Check if enough time has passed since last order for this symbol"""
    current_time = time.time()
    if symbol not in last_order_time:
        last_order_time[symbol] = current_time
        return True
    
    if current_time - last_order_time[symbol] >= ORDER_COOLDOWN:
        last_order_time[symbol] = current_time
        return True
    return False


def get_moving_average(symbol):
    """Calculate moving average with proper error handling"""
    if len(price_history[symbol]) < 3:
        return None
    return sum(price_history[symbol]) / len(price_history[symbol])


def check_position_limit(state_manager, symbol, size, direction):
    """Ensure we don't exceed position limits"""
    current_pos = state_manager.position_for_symbol(symbol)
    limit = POSITION_LIMITS.get(symbol, 100)
    
    if direction == Dir.BUY:
        return current_pos + size <= limit
    else:
        return current_pos - size >= -limit


def on_book(state_manager, book_message):
    """Called whenever the book for a symbol updates."""
    try:
        # Get best prices from the book
        symbol = book_message['symbol']
        
        if symbol != 'XLF':
            return
            
        # XLF arbitrage logic
        xlf_orders = state_manager.open_and_pending_orders_in_symbol_and_direction_by_price_level('XLF', Dir.BUY)
        bond_orders = state_manager.open_and_pending_orders_in_symbol_and_direction_by_price_level('BOND', Dir.BUY)
        gs_orders = state_manager.open_and_pending_orders_in_symbol_and_direction_by_price_level('GS', Dir.BUY)
        ms_orders = state_manager.open_and_pending_orders_in_symbol_and_direction_by_price_level('MS', Dir.BUY)
        wfc_orders = state_manager.open_and_pending_orders_in_symbol_and_direction_by_price_level('WFC', Dir.BUY)

        XLF_price = max(xlf_orders.keys(), default=None)
        BOND_price = max(bond_orders.keys(), default=None)
        GS_price = max(gs_orders.keys(), default=None)
        MS_price = max(ms_orders.keys(), default=None)
        WFC_price = max(wfc_orders.keys(), default=None)

        if None in [XLF_price, BOND_price, GS_price, MS_price, WFC_price]:
            return

        # Calculate basket value
        stocks_sum = 3 * BOND_price + 2 * GS_price + 3 * MS_price + 2 * WFC_price
        conversion_cost = 100  # Conversion fee

        # Check arbitrage opportunity
        if XLF_price * 10 + conversion_cost < stocks_sum:
            xlf_holdings = state_manager.position_for_symbol("XLF")
            if xlf_holdings > 0:
                # Convert and sell components
                state_manager.send_convert_message(state_manager.next_order_id(), "XLF", Dir.SELL, min(xlf_holdings, 10))
                
                state_manager.send_order("BOND", Dir.SELL, BOND_price, 3)
                state_manager.send_order("GS", Dir.SELL, GS_price, 2)
                state_manager.send_order("MS", Dir.SELL, MS_price, 3)
                state_manager.send_order("WFC", Dir.SELL, WFC_price, 2)

    except (IndexError, KeyError) as e:
        pass


def on_fill(state_manager, fill_message):
    """Called when one of your orders is filled."""
    pass


def on_trade(state_manager, trade_message):
    """Called when someone else's order is filled."""
    symbol = trade_message['symbol']
    price = trade_message['price']
    
    # Update price history only for relevant symbol
    if symbol in price_history:
        price_history[symbol].append(price)
    
    # BOND mean reversion
    if symbol == 'BOND' and should_send_order('BOND'):
        bond_position = state_manager.position_for_symbol("BOND")
        target_position = 0
        
        if bond_position < target_position - 5:
            if check_position_limit(state_manager, "BOND", 1, Dir.BUY):
                state_manager.send_order("BOND", Dir.BUY, 999, 1)
        elif bond_position > target_position + 5:
            if check_position_limit(state_manager, "BOND", 1, Dir.SELL):
                state_manager.send_order("BOND", Dir.SELL, 1001, 1)
    
    # Market making with moving averages
    avg_price = get_moving_average(symbol)
    if avg_price is None or not should_send_order(symbol):
        return
    
    if symbol == 'XLF':
        spread = 3
        if check_position_limit(state_manager, symbol, 1, Dir.BUY):
            state_manager.send_order(symbol, Dir.BUY, int(avg_price - spread), 1)
        if check_position_limit(state_manager, symbol, 1, Dir.SELL):
            state_manager.send_order(symbol, Dir.SELL, int(avg_price + spread), 1)
    
    elif symbol in ['WFC', 'GS', 'MS']:
        spread = 1
        if check_position_limit(state_manager, symbol, 1, Dir.BUY):
            state_manager.send_order(symbol, Dir.BUY, int(avg_price - spread), 1)
        if check_position_limit(state_manager, symbol, 1, Dir.SELL):
            state_manager.send_order(symbol, Dir.SELL, int(avg_price + spread), 1)
    
    # VALE/VALBZ arbitrage
    if symbol in ['VALE', 'VALBZ']:
        vale_avg = get_moving_average('VALE')
        valbz_avg = get_moving_average('VALBZ')
        
        if vale_avg is not None and valbz_avg is not None:
            spread_threshold = 30
            
            # VALE more expensive than VALBZ
            if vale_avg - valbz_avg > spread_threshold and should_send_order('VALE_ARB'):
                if check_position_limit(state_manager, 'VALBZ', 1, Dir.BUY):
                    state_manager.send_order("VALBZ", Dir.BUY, int(valbz_avg), 1)
                    state_manager.send_convert_message(state_manager.next_order_id(), "VALBZ", Dir.SELL, 1)
                    state_manager.send_order("VALE", Dir.SELL, int(vale_avg - 5), 1)


def main():
    args = parse_arguments()

    exchange = ExchangeConnection(args=args)
    state_manager = State_manager(exchange)

    hello_message = exchange.read_message()
    print("First message from exchange:", hello_message)
    state_manager.on_hello(hello_message)

    on_startup(state_manager)

    while True:
        message = exchange.read_message()

        if message["type"] == "close":
            print("The round has ended")
            break
        elif message["type"] == "error":
            print(message)
        elif message["type"] == "reject":
            state_manager.on_reject(message)
        elif message["type"] == "fill":
            print(message)
            state_manager.on_fill(message)
            on_fill(state_manager, message)
        elif message["type"] == "trade":
            on_trade(state_manager, message)
        elif message["type"] == "ack":
            state_manager.on_ack(message)
        elif message["type"] == "out":
            state_manager.on_out(message)
        elif message["type"] == "book":
            on_book(state_manager, message)


# ~~~~~============== PROVIDED CODE ==============~~~~~

class Dir(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class ExchangeConnection:
    def __init__(self, args):
        self.message_timestamps = deque(maxlen=500)
        self.exchange_hostname = args.exchange_hostname
        self.port = args.port
        exchange_socket = self._connect(add_socket_timeout=args.add_socket_timeout)
        self.reader = exchange_socket.makefile("r", 1)
        self.writer = exchange_socket

        self._write_message({"type": "hello", "team": team_name.upper()})

    def read_message(self):
        """Read a single message from the exchange"""
        message = json.loads(self.reader.readline())
        if "dir" in message:
            message["dir"] = Dir(message["dir"])
        return message

    def send_add_message(
        self, order_id: int, symbol: str, dir: Dir, price: int, size: int
    ):
        """Add a new order"""
        self._write_message(
            {
                "type": "add",
                "order_id": order_id,
                "symbol": symbol,
                "dir": dir,
                "price": price,
                "size": size,
            }
        )

    def send_convert_message(self, order_id: int, symbol: str, dir: Dir, size: int):
        """Convert between related symbols"""
        self._write_message(
            {
                "type": "convert",
                "order_id": order_id,
                "symbol": symbol,
                "dir": dir,
                "size": size,
            }
        )

    def send_cancel_message(self, order_id: int):
        """Cancel an existing order"""
        self._write_message({"type": "cancel", "order_id": order_id})

    def _connect(self, add_socket_timeout):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        if add_socket_timeout:
            s.settimeout(5)
        s.connect((self.exchange_hostname, self.port))
        return s

    def _write_message(self, message):
        what_to_write = json.dumps(message)
        if not what_to_write.endswith("\n"):
            what_to_write = what_to_write + "\n"

        length_to_send = len(what_to_write)
        total_sent = 0
        while total_sent < length_to_send:
            sent_this_time = self.writer.send(
                what_to_write[total_sent:].encode("utf-8")
            )
            if sent_this_time == 0:
                raise Exception("Unable to send data to exchange")
            total_sent += sent_this_time

        now = time.time()
        self.message_timestamps.append(now)
        if len(
            self.message_timestamps
        ) == self.message_timestamps.maxlen and self.message_timestamps[0] > (now - 1):
            print(
                "WARNING: You are sending messages too frequently. The exchange will start ignoring your messages. Make sure you are not sending a message in response to every exchange message."
            )


class Order:
    def __init__(self, symbol, size, price, dir):
        self.symbol = symbol
        self.size = size
        self.price = price
        self.dir = dir

    def __str__(self):
        return f'Order(size={self.size}, dir={self.dir.value}, price={self.price}, size={self.size})'

    def __repr__(self):
        return self.__str__()


class State_manager:
    def __init__(self, exchange):
        self.exchange = exchange
        self.order_id_counter = -1
        self.positions_by_symbol = {}
        self.unacked_orders = {}
        self.open_orders = {}
        self.pending_cancels = set()

    def position_for_symbol(self, symbol):
        return self.positions_by_symbol.get(symbol, 0)

    def next_order_id(self):
        self.order_id_counter += 1
        return self.order_id_counter

    def on_ack(self, message):
        assert(message['type'] == 'ack')
        order_id = message['order_id']
        if order_id in self.unacked_orders:
            self.open_orders[order_id] = self.unacked_orders.pop(order_id)

    def on_fill(self, message):
        assert(message['type'] == 'fill')
        order_id = message['order_id']
        symbol = message['symbol']
        dir = message['dir']
        raw_size = message['size']
        size_multiplier = 1 if dir == Dir.BUY.value else -1
        size = raw_size * size_multiplier
        if order_id in self.open_orders:
            self.open_orders[order_id].size -= raw_size
            self.positions_by_symbol[symbol] = self.positions_by_symbol.get(symbol, 0) + size

    def on_out(self, message):
        assert(message['type'] == 'out')
        order_id = int(message['order_id'])
        if order_id in self.open_orders:
            del self.open_orders[order_id]
            self.pending_cancels.discard(order_id)

    def on_hello(self, message):
        assert(message['type'] == 'hello')
        symbol_positions = message['symbols']
        for symbol_position in symbol_positions:
            symbol = symbol_position['symbol']
            position = symbol_position['position']
            self.positions_by_symbol[symbol] = position

    def on_reject(self, message):
        assert(message['type'] == 'reject')
        order_id = message['order_id']
        self.unacked_orders.pop(order_id, None)

    def send_order(self, symbol, dir, price, size):
        order_id = self.next_order_id()
        order = Order(symbol, size, price, Dir(dir))
        self.unacked_orders[order_id] = order
        self.exchange.send_add_message(order_id, symbol, dir, price, size)

    def send_convert_message(self, order_id, symbol, dir, size):
        order = Order(symbol, size, 0, Dir(dir))
        self.unacked_orders[order_id] = order
        self.exchange.send_convert_message(order_id, symbol, dir, size)

    def cancel_order(self, order_id):
        self.pending_cancels.add(order_id)
        self.exchange.send_cancel_message(order_id)

    def open_and_pending_orders_in_symbol_and_direction_by_price_level(self, symbol, dir):
        output = {}
        for order_id, order in chain(self.open_orders.items(), self.unacked_orders.items()):
            if order.symbol == symbol and order.dir == dir and order_id not in self.pending_cancels:
                price_level = order.price
                if price_level not in output:
                    output[price_level] = {}
                output[price_level][order_id] = order
        return output

    def set_orders_in_symbol_for_direction(self, symbol, dir, size_by_price_level):
        current_orders = self.open_and_pending_orders_in_symbol_and_direction_by_price_level(symbol, dir)
        for price_level in (size_by_price_level | current_orders):
            current_orders_by_order_id = current_orders.get(price_level, {})
            current_size_at_price_level = 0

            for order in current_orders_by_order_id.values():
                current_size_at_price_level += order.size

            desired_size_for_price_level = size_by_price_level.get(price_level, 0)

            assert(desired_size_for_price_level >= 0)

            if current_size_at_price_level == desired_size_for_price_level:
                pass
            elif current_size_at_price_level < desired_size_for_price_level:
                self.send_order(symbol, dir, price_level, desired_size_for_price_level - current_size_at_price_level)
            else:
                for order_id in current_orders_by_order_id:
                    if order_id not in self.pending_cancels:
                        self.cancel_order(order_id)

                if desired_size_for_price_level != 0:
                    self.send_order(symbol, dir, price_level, desired_size_for_price_level)


def parse_arguments():
    test_exchange_port_offsets = {"prod-like": 0, "slower": 1, "empty": 2}

    parser = argparse.ArgumentParser(description="Trade on an ETC exchange!")
    exchange_address_group = parser.add_mutually_exclusive_group(required=True)
    exchange_address_group.add_argument(
        "--production", action="store_true", help="Connect to the production exchange."
    )
    exchange_address_group.add_argument(
        "--test",
        type=str,
        choices=test_exchange_port_offsets.keys(),
        help="Connect to a test exchange.",
    )

    exchange_address_group.add_argument(
        "--specific-address", type=str, metavar="HOST:PORT", help=argparse.SUPPRESS
    )

    args = parser.parse_args()
    args.add_socket_timeout = True

    if args.production:
        args.exchange_hostname = "production"
        args.port = 25000
    elif args.test:
        args.exchange_hostname = "test-exch-" + team_name
        args.port = 22000 + test_exchange_port_offsets[args.test]
        if args.test == "empty":
            args.add_socket_timeout = False
    elif args.specific_address:
        args.exchange_hostname, port = args.specific_address.split(":")
        args.port = int(port)

    return args


if __name__ == "__main__":
    assert (
        team_name != "REPLAC" + "EME"
    ), "Please put your team name in the variable [team_name]."

    main()
