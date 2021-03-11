import json
import websockets
import asyncio
from keys import BINANCE_API_KEY, BINANCE_API_SECRET_KEY, FTX_API_KEY, FTX_API_SECRET
from binance.client import Client
import csv
import os
import sys
import time
from datetime import datetime as dt
import datetime
import pandas as pd
import matplotlib.pyplot as plt
from typing import Optional, Dict, Any, List 
import urllib.parse  
from requests import Request, Session, Response
import hmac
from ciso8601 import parse_datetime

# Binance OHCL data
class BinanceDataProcessor:

    def __init__(self, key, secret):
        self.key = key
        self.secret = secret
        self.client = Client(self.key, self.secret)

    def binance_historical_data_recorder(self, name_of_csv, symbol="BTCUSDT"):
        ohlc_data = open(name_of_csv, 'w', newline='')
        ohlc_writer = csv.writer(ohlc_data, delimiter=',')

        ohlc = self.client.get_historical_klines(
            symbol, Client.KLINE_INTERVAL_1MINUTE, "1 Dec, 2016", "24 Feb, 2021")

        for candlestick in ohlc:
            ohlc_writer.writerow(candlestick)

        ohlc_data.close()


class FTXDataProcessor:
    
    _ENDPOINT = 'https://ftx.com/api/'

    def __init__(self, api_key=None, api_secret=None, subaccount_name=None):
        self._session = Session()
        self._api_key = api_key
        self._api_secret = api_secret
        self._subaccount_name = subaccount_name

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        return self._request('GET', path, params=params)

    def _post(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        return self._request('POST', path, json=params)

    def _delete(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        return self._request('DELETE', path, json=params)

    def _request(self, method: str, path: str, **kwargs) -> Any:
        request = Request(method, self._ENDPOINT + path, **kwargs)
        self._sign_request(request)
        response = self._session.send(request.prepare())
        return self._process_response(response)

    def _sign_request(self, request: Request) -> None:
        ts = int(time.time() * 1000)
        prepared = request.prepare()
        signature_payload = f'{ts}{prepared.method}{prepared.path_url}'.encode(
        )
        if prepared.body:
            signature_payload += prepared.body
        signature = hmac.new(self._api_secret.encode(),
                             signature_payload, 'sha256').hexdigest()
        request.headers['FTX-KEY'] = self._api_key
        request.headers['FTX-SIGN'] = signature
        request.headers['FTX-TS'] = str(ts)
        if self._subaccount_name:
            request.headers['FTX-SUBACCOUNT'] = urllib.parse.quote(
                self._subaccount_name)

    def _process_response(self, response: Response) -> Any:
        try:
            data = response.json()
        except ValueError:
            response.raise_for_status()
            raise
        else:
            if not data['success']:
                raise Exception(data['error'])
            return data['result']

    def list_futures(self) -> List[dict]:
        return self._get('futures')

    def list_markets(self) -> List[dict]:
        return self._get('markets')

    def get_orderbook(self, market: str, depth: int = None) -> dict:
        return self._get(f'markets/{market}/orderbook', {'depth': depth})

    def get_trades(self, market: str) -> dict:
        return self._get(f'markets/{market}/trades')

    def get_account_info(self) -> dict:
        return self._get(f'account')

    def get_open_orders(self, market: str = None) -> List[dict]:
        return self._get(f'orders', {'market': market})

    def get_order_history(self, market: str = None, side: str = None, order_type: str = None, start_time: float = None, end_time: float = None) -> List[dict]:
        return self._get(f'orders/history', {'market': market, 'side': side, 'orderType': order_type, 'start_time': start_time, 'end_time': end_time})

    def get_conditional_order_history(self, market: str = None, side: str = None, type: str = None, order_type: str = None, start_time: float = None, end_time: float = None) -> List[dict]:
        return self._get(f'conditional_orders/history', {'market': market, 'side': side, 'type': type, 'orderType': order_type, 'start_time': start_time, 'end_time': end_time})

    def modify_order(
        self, existing_order_id: Optional[str] = None,
        existing_client_order_id: Optional[str] = None, price: Optional[float] = None,
        size: Optional[float] = None, client_order_id: Optional[str] = None,
    ) -> dict:
        assert (existing_order_id is None) ^ (existing_client_order_id is None), \
            'Must supply exactly one ID for the order to modify'
        assert (price is None) or (
            size is None), 'Must modify price or size of order'
        path = f'orders/{existing_order_id}/modify' if existing_order_id is not None else \
            f'orders/by_client_id/{existing_client_order_id}/modify'
        return self._post(path, {
            **({'size': size} if size is not None else {}),
            **({'price': price} if price is not None else {}),
            ** ({'clientId': client_order_id} if client_order_id is not None else {}),
        })

    def get_conditional_orders(self, market: str = None) -> List[dict]:
        return self._get(f'conditional_orders', {'market': market})

    def place_order(self, market: str, side: str, price: float, size: float, type: str = 'limit',
                    reduce_only: bool = False, ioc: bool = False, post_only: bool = False,
                    client_id: str = None) -> dict:
        return self._post('orders', {'market': market,
                                     'side': side,
                                     'price': price,
                                     'size': size,
                                     'type': type,
                                     'reduceOnly': reduce_only,
                                     'ioc': ioc,
                                     'postOnly': post_only,
                                     'clientId': client_id,
                                     })

    def place_conditional_order(
        self, market: str, side: str, size: float, type: str = 'stop',
        limit_price: float = None, reduce_only: bool = False, cancel: bool = True,
        trigger_price: float = None, trail_value: float = None
    ) -> dict:
        """
        To send a Stop Market order, set type='stop' and supply a trigger_price
        To send a Stop Limit order, also supply a limit_price
        To send a Take Profit Market order, set type='trailing_stop' and supply a trigger_price
        To send a Trailing Stop order, set type='trailing_stop' and supply a trail_value
        """
        assert type in ('stop', 'take_profit', 'trailing_stop')
        assert type not in ('stop', 'take_profit') or trigger_price is not None, \
            'Need trigger prices for stop losses and take profits'
        assert type not in ('trailing_stop',) or (trigger_price is None and trail_value is not None), \
            'Trailing stops need a trail value and cannot take a trigger price'

        return self._post('conditional_orders',
                          {'market': market, 'side': side, 'triggerPrice': trigger_price,
                           'size': size, 'reduceOnly': reduce_only, 'type': 'stop',
                           'cancelLimitOnTrigger': cancel, 'orderPrice': limit_price})

    def cancel_order(self, order_id: str) -> dict:
        return self._delete(f'orders/{order_id}')

    def cancel_orders(self, market_name: str = None, conditional_orders: bool = False,
                      limit_orders: bool = False) -> dict:
        return self._delete(f'orders', {'market': market_name,
                                        'conditionalOrdersOnly': conditional_orders,
                                        'limitOrdersOnly': limit_orders,
                                        })

    def get_fills(self) -> List[dict]:
        return self._get(f'fills')

    def get_balances(self) -> List[dict]:
        return self._get('wallet/balances')

    def get_deposit_address(self, ticker: str) -> dict:
        return self._get(f'wallet/deposit_address/{ticker}')

    def get_positions(self, show_avg_price: bool = False) -> List[dict]:
        return self._get('positions', {'showAvgPrice': show_avg_price})

    def get_position(self, name: str, show_avg_price: bool = False) -> dict:
        return next(filter(lambda x: x['future'] == name, self.get_positions(show_avg_price)), None)

    def get_all_trades(self, market: str, start_time: float = None, end_time: float = None) -> List:
        ids = set()
        limit = 100
        results = []
        while True:
            response = self._get(f'markets/{market}/trades', {
                'end_time': end_time,
                'start_time': start_time,
            })
            deduped_trades = [r for r in response if r['id'] not in ids]
            results.extend(deduped_trades)
            ids |= {r['id'] for r in deduped_trades}
            print(f'Adding {len(response)} trades with end time {end_time}')
            if len(response) == 0:
                break
            end_time = min(parse_datetime(t['time'])
                           for t in response).timestamp()
            if len(response) < limit:
                break
        return results


# API Doc: https://docs.deribit.com/?python#public-get_instrument
class DeribitDataProcessor:

    def __init__(self, start_year, start_month, start_day, end_year=None, end_month=None, end_day=None, 
                symbol="BTC-PERPETUAL", time_interval='60'):
        
        str_start_time = f'{start_day}/{start_month}/{start_year}'
        self.start = dt.timestamp(
            dt.strptime(str_start_time, "%d/%m/%Y"))

        if end_year == None and end_month == None and end_day == None:
            self.end = dt.timestamp(dt.now())
        else:
            str_end_time = f'{end_day}/{end_month}/{end_year}'
            self.end = dt.timestamp(
                dt.strptime(str_end_time, "%d/%m/%Y"))

        self.symbol = symbol
        self.time_interval = time_interval

        self.msg = {
            "jsonrpc": "2.0",
            "id": 833,
            "method": "public/get_tradingview_chart_data",
            "params": {
                "instrument_name": self.symbol,
                "start_timestamp": int(round(self.start))*1000,
                "end_timestamp": int(round(self.end))*1000,
                "resolution": self.time_interval
            }
        }
        # print(self.msg)

    async def call_api(self, msg):
        async with websockets.connect('wss://test.deribit.com/ws/api/v2') as websocket:
            await websocket.send(msg)
            while websocket.open:
                response = await websocket.recv()
                return response

    def api_loop(self, api_func, msg):
        loop = asyncio.get_event_loop()
        return loop.run_until_complete((api_func(msg)))

    def retrieve_data(self):
        response = self.api_loop(self.call_api, json.dumps(self.msg))
        return response   # raw form, needs json.loads() later

    def to_pandas_df(self, response):
        jsoned_response = json.loads(response)
        df = pd.DataFrame(jsoned_response['result'])
        df['ticks'] = df.ticks/1000
        df['timestamp'] = [dt.fromtimestamp(time) for time in df.ticks]
        return df

    def deribit_historical_data_recorder(self, name_of_csv):
        df = self.to_pandas_df(self.retrieve_data())
        return df.to_csv(name_of_csv, encoding='utf-8', index=False)
    
    def df_column_orgnizer(self, df):
        needed_columns = ['volume', 'open',
                          'low', 'high', 'close', 'timestamp', 'next_open']
        for col in df.columns:
            if col not in needed_columns:
                del df[col]
        return df
    
    def REST_polling(self, write_file = True, name_of_csv='new_data.csv', cleaned_column=True):

        day_span = (dt.now()-dt.fromtimestamp(self.start)).days
        df = pd.DataFrame()
        new_day = dt.fromtimestamp(self.start)

        for d in range(day_span): 

            unix_past_day = dt.timestamp(new_day)
            new_day += datetime.timedelta(days=1)
            unix_future_day = dt.timestamp(new_day)

            new_request = {
                "jsonrpc": "2.0",
                "id": 833,
                "method": "public/get_tradingview_chart_data",
                "params": {
                    "instrument_name": self.symbol,
                    "start_timestamp": unix_past_day*1000,
                    "end_timestamp": unix_future_day*1000,
                    "resolution": self.time_interval
                }
            }

            response = self.api_loop(self.call_api, json.dumps(new_request))
            pandaed = self.to_pandas_df(response)
            pandaed['next_open'] = pandaed.open.shift(-1) #change this to the random price within one standard deviation from last ohlc 
            pandaed.drop(pandaed.tail(1).index,
                    inplace=True)
            
            if cleaned_column:
                pandaed = self.df_column_orgnizer(pandaed)
            
            df = df.append(pandaed, ignore_index=True)

            # print(f'showing data of {new_day}')
            # print(pandaed)
            time.sleep(0.01)

        if write_file:  
            df.to_csv(name_of_csv)
            return df
        else:
            return df



if __name__ == '__main__':

    # deribit = DeribitDataProcessor('2021', '02', '26', time_interval='30')
    # df = res.to_pandas_df(res.retrieve_data())
    # complete_data = deribit.REST_polling(True, 'BTCPerp-09-26-20-to-03-01-21')
    # dataframe = pd.read_csv('BTCPerp-09-26-20-to-03-01-21.csv')
    # plt.plot(dataframe.timestamp, dataframe.close)

# market: str, start_time: float = None, end_time: float = None
    acc = FTXDataProcessor(api_key=FTX_API_KEY, api_secret=FTX_API_SECRET)
    res = acc.get_all_trades(market='BTC-PERP')
    print(res)