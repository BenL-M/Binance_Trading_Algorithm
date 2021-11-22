import websocket, json, config, talib, numpy
from datetime import datetime, timedelta
from binance import Client
from binance.enums import *
import math 

client = Client(config.API_KEY, config.API_SECRET)
SOCKET = "wss://stream.binance.com:9443/ws/ethusdt@kline_1m"
tradeSymbol = 'ETHUSDT'

indicators = {} # dictionary of indicators
closes = []  # array of past 200 close values
activeOrder = {} # {'id' : x, 'status': y}
buySignalTimer = datetime.now() - timedelta(minutes=500)
buySignalBool = False

def round_down(number, decimals):
    if not isinstance(decimals, int):
        raise TypeError("decimal places must be an integer")
    elif decimals < 0:
        raise ValueError("decimal places has to be 0 or more")
    elif decimals == 0:
        return math.floor(number)

    factor = 10 ** decimals 
    return math.floor(number*factor) / factor 

def load_indicators():
    global closes
    klines = client.get_historical_klines(tradeSymbol, Client.KLINE_INTERVAL_1MINUTE, '200 minutes ago UTC')
    closes = [float(el[4]) for el in klines]
    np_closes = numpy.array(closes)
    define_indicators(np_closes)
    print_indicators()

def update_indicators(message):
    global closes
    json_message = json.loads(message)
    if json_message['k']['x'] == True:
        closes.append(float(json_message['k']['c']))
        closes.pop(0)
        np_closes = numpy.array(closes)
        define_indicators(np_closes)
        # print_indicators()
        print('--------------------------')

def define_indicators(np_closes):
    indicators['sma200'] = talib.SMA(np_closes, timeperiod=200)[-1]
    indicators['sma50'] = talib.SMA(np_closes, timeperiod=50)[-1]
    indicators['sma21'] = talib.SMA(np_closes, timeperiod=21)[-1]
    indicators['rsi'] = talib.RSI(np_closes, 14)[-1]
    macd = talib.MACD(np_closes, fastperiod=12, slowperiod=26, signalperiod=9)
    indicators['macd'] = {
        'old': {
            'fast': macd[0][-2],
            'slow': macd[1][-2],
            'difference': macd[2][-2]
            },
        'new': {
            'fast': macd[0][-1],
            'slow': macd[1][-1],
            'difference': macd[2][-1]
            }
    }

def print_indicators():
    now = datetime.now()
    current_time = now.strftime("%H:%M:%S")
    print(f'Time: {current_time}')
    print(f'200 SMA: {indicators["sma200"]}')
    print(f'50 SMA: {indicators["sma50"]}')
    print(f'21 SMA: {indicators["sma21"]}')
    print(f'RSI: {indicators["rsi"]}')
    print(f'MACD: {indicators["macd"]}')

def buy_signal(indicators):
    if indicators['sma21'] > indicators['sma50'] and indicators['sma50'] > indicators['sma200'] and indicators['rsi'] < 30:
        return True
    else: 
        return False

def macd_signal(indicators):
        oldMacd= indicators['macd']['old']
        newMacd= indicators['macd']['new']
        if oldMacd['fast'] <= oldMacd['slow'] and newMacd['fast'] > newMacd['slow']:
            return True
        else: 
            return False

def buy_order(tradeSymbol, usdAmount, price): # string, float, float 
    print(f'Symbol: {tradeSymbol} Amount(usdt): {usdAmount} Price(usdt): {round(price, 5)}')
    order = client.create_order(
        symbol=tradeSymbol,
        side=SIDE_BUY,
        type=ORDER_TYPE_LIMIT,
        timeInForce=TIME_IN_FORCE_GTC,
        quantity=round(usdAmount/price, 5),
        price=str(round(price, 5))
    ) 
    print('Submitted buy limit order')
    print('--------------------------')
    return order

def check_order_status(orderToCheck):
    global activeOrder
    orders = client.get_all_orders(symbol=tradeSymbol, limit=10)
    order = [i for i in orders if i['orderId'] == orderToCheck['id']]
    activeOrder['status'] = order[0]['status']
    return order[0]['status']

def get_order_details(orderToCheck):
    global activeOrder
    orders = client.get_all_orders(symbol=tradeSymbol, limit=10)
    order = [i for i in orders if i['orderId'] == orderToCheck['id']]
    return order[0]

def OCO_order(tradeSymbol, coinAmount, price, stopPrice, stopLimitPrice):
    decimals = 2
    print(f'Symbol: {tradeSymbol} Amount(coin): {round_down(coinAmount, decimals+(5-decimals))} Price(usdt): {round(price, decimals)} Stop Price(usdt): {round(stopPrice, decimals)+0.01} Stop Limit Price(usdt): {round(stopLimitPrice, decimals)}')
    order = client.create_oco_order(
        side=SIDE_SELL,
        symbol = tradeSymbol,
        quantity = round_down(coinAmount, decimals+(5-decimals)),
        price = str(round(price, decimals)),
        stopPrice = str(round(stopPrice, decimals)+0.01),
        stopLimitPrice = str(round(stopLimitPrice, decimals)),
        stopLimitTimeInForce = 'GTC'
    )
    print('Submitted OCO sell order')
    return order

def cancel_order(tradeSymbol, activeOrder):
    if activeOrder != {}:
        order = client.cancel_order(
            symbol=tradeSymbol,
            orderId=str(activeOrder['id'])
            )
        return order

def on_open(ws):
    print('Connection opened')
    print('--------------------------')
    load_indicators()
    print('--------------------------')

def on_close(ws):
    print('Connection closed')
    print('--------------------------')
    
def on_message(ws, message):
    global buySignalTimer
    global activeOrder
    global buySignalBool
    # if incoming message contains closing candle, update indicators. 
    update_indicators(message)

    if buy_signal(indicators) == True and activeOrder == {}:
        buySignalTimer = datetime.now() + timedelta(minutes=15)
        buySignalBool = True 

    
    try:
        if macd_signal(indicators) == True and datetime.now() < buySignalTimer and activeOrder == {} and buySignalBool == True:
            json_message = json.loads(message)
            price = float(json_message['k']['c'])
            order = buy_order(tradeSymbol, 11, price)
            activeOrder = {'id': order['orderId'], 'status': order['status']} # {'id' : x, 'order status': y}
            buySignalTimer = datetime.now() + timedelta(minutes=15)
            buySignalBool = False
    except Exception as e:
        print('Buy order block error')
        print(e) 
    
    # cancel order if open too long and not filled.
    try:
        if datetime.now() >= buySignalTimer:
            buySignalTimer = datetime.now() - timedelta(minutes=500)
            if activeOrder != {} and check_order_status(activeOrder) == 'NEW' or 'REJECTED':
                order = cancel_order(tradeSymbol, activeOrder)
                activeOrder = {}
    except Exception as e:
        print('Cancel order block error')
        print(e)

    try:
        if activeOrder != {} and check_order_status(activeOrder) == 'FILLED':
            orderDetails = get_order_details(activeOrder)
            coinAmount = float(orderDetails['origQty'])
            price =  float(orderDetails['price'])
            order = OCO_order(tradeSymbol, coinAmount, price*1.02, price*0.99, price*0.99)
            activeOrder = {}
    except Exception as e:
        print('OCO order block error')
        print(e)

ws = websocket.WebSocketApp(SOCKET, on_open=on_open, on_close=on_close, on_message=on_message) 
ws.run_forever()