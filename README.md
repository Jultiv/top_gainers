# Crypto Trading Bot

A comprehensive cryptocurrency trading bot with real-time price analysis, automated trading strategies, and an interactive terminal display.

## Overview

This project is a feature-rich cryptocurrency trading bot that connects to Binance's API to monitor market data, analyze trends, and execute trading strategies with configurable risk profiles. The bot supports running on both testnet and mainnet environments with different execution modes for safety.

## Key Features

- **Real-time Market Analysis**: Monitors price movements and analyzes trends across multiple timeframes
- **Advanced Technical Indicators**: Incorporates RSI, ATR, and volatility ratio analysis
- **Smart Position Management**: Implements intelligent position sizing and capital allocation
- **Trailing Stop Loss**: Dynamic trailing stops for maximizing profits during trends
- **Event-driven Architecture**: Uses an asynchronous event system for decoupling components
- **Execution Mode Options**: Supports test orders, real orders on testnet, and real orders on production
- **Interactive Terminal Interface**: Rich terminal display with colored logs and command processing
- **Comprehensive Logging**: Detailed logs with configurable verbosity levels

## Components

The bot is built with a modular architecture consisting of the following main components:

### Core Components

- **CryptoTrader**: Main trading logic and coordination
- **PositionManager**: Handles position tracking, sizing, and risk management
- **PriceManager**: Processes market data and technical analysis
- **EventManager**: Asynchronous event system for inter-component communication
- **OrderExecutor**: Handles the actual execution of orders via Binance API
- **TerminalDisplay**: Interactive terminal UI and reporting

### Supporting Components

- **BinanceAPIManager**: Handles all Binance API communication
- **DataRecorder**: Records trading data and performance metrics
- **Logger Configuration**: Customizable logging with multiple severity levels

## Configuration

The bot is highly configurable through the `TradingConfig` class in `topgainers23.py`. Key configuration options include:

- `REFERENCE_CURRENCY`: Base currency for trading pairs (USDT, USDC, etc.)
- `ORDER_EXECUTION_MODE`: Trading mode (0: Test validation, 1: Real orders on testnet, 2: Real orders on mainnet)
- `POSITION_SIZE`: Percentage of capital to use per position
- Trading parameters for different risk profiles (safe and risky)
- Technical indicator settings (ATR, RSI periods, thresholds)
- Trailing stop activation thresholds and distances

## Usage

### Prerequisites

- Python 3.7+
- Binance API keys (with or without trading permissions depending on execution mode)
- Required Python packages (see requirements section)

### Setup

1. Create a `.env` file with your Binance API credentials:
   ```
   BINANCE_API_KEY=your_api_key
   BINANCE_API_SECRET=your_api_secret
   REFERENCE_CURRENCY=USDT  # or your preferred reference currency
   ```

2. Install required packages:
   ```
   pip install asyncio aiohttp websockets pandas python-dotenv
   ```

### Running the Bot

Run the bot with customized parameters:

```
python main.py --execution-mode 0 --reference-currency USDT --verbosity normal
```

#### Command-line Arguments

- `--execution-mode`: 0 (test orders), 1 (real orders on testnet), 2 (real orders on mainnet)
- `--reference-currency`: Base currency for trading (USDT, USDC, BUSD, etc.)
- `--verbosity`: Log detail level (minimal, normal, detailed, debug)

### Terminal Commands

Once running, you can use the following commands in the terminal:

- `help` or `?`: Display available commands
- `status` or `s`: Show system status
- `positions` or `p`: Display active positions
- `summary` or `sum`: Show performance summary
- `vol`: Display volatility rankings
- `verbose [min/normal/detailed/debug]`: Change verbosity level
- `quit` or `exit`: Stop the bot

## Safety Features

- Warm-up period before active trading to gather sufficient data
- Multiple execution modes for testing before using real funds
- Configurable position sizing with minimum thresholds
- Cooldown periods between trades on the same pair
- Transaction fee calculation and accounting
- Balance verification before order execution

## Architecture

The bot uses an event-driven asynchronous architecture with the following flow:

1. WebSocket connection streams real-time market data from Binance
2. Price data is processed and analyzed for trading opportunities
3. When conditions are met, an event is emitted for position opening
4. The order executor handles the actual order submission
5. Active positions are monitored for take profit, stop loss, or trailing stop conditions
6. When exit conditions are met, position close events are emitted
7. The terminal display provides real-time feedback and command processing

## Files Description

- `main.py`: Entry point with command-line argument parsing
- `topgainers23.py`: Core trading logic and configuration
- `event_manager.py`: Asynchronous event system
- `terminal_display.py`: Interactive terminal UI
- `order_executor.py`: Order execution through Binance API
- `binance_api_connection.py`: API communication with Binance
- `logger_config.py`: Advanced logging configuration
- `trader_display_integration.py`: Integrates terminal display with trader

## License

This project is provided for educational purposes. Use at your own risk and be aware of the financial risks associated with cryptocurrency trading.

## Disclaimer

This trading bot is not financial advice. Cryptocurrency trading involves significant risk. Always start with small amounts and test thoroughly before using significant funds. The developers are not responsible for any financial losses incurred from using this software.
