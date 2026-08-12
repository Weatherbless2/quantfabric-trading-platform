# coding=utf-8

from OxQuant.pytdx.parser.base import BaseParser
from OxQuant.pytdx.helper import get_datetime, get_volume, get_price
from collections import OrderedDict
import six
import struct

class GetInstrumentBars(BaseParser):

    # ﻿ff232f49464c30007401a9130400010000000000f000
    """

    first：

    ﻿0000   01 01 08 6a 01 01 16 00 16 00                    ...j......


    second：
    ﻿0000   ff 23 2f 49 46 4c 30 00 74 01 a9 13 04 00 01 00  .#/IFL0.t.......
    0010   00 00 00 00 f0 00                                ......

    ﻿0000   ff 23 28 42 41 42 41 00 00 00 a9 13 04 00 01 00  .#(BABA.........
    0010   00 00 00 00 f0 00                                ......

    ﻿0000   ff 23 28 42 41 42 41 00 00 00 a9 13 03 00 01 00  .#(BABA.........
    0010   00 00 00 00 f0 00                                ......

    ﻿0000   ff 23 08 31 30 30 30 30 38 34 33 13 04 00 01 00  .#.10000843.....
    0010   00 00 00 00 f0 00                                ......
    """

    def setup(self):
        pass
        #self.client.send(bytearray.fromhex('01 01 08 6a 01 01 16 00 16 00'))

    def setParams(self, category, market, code, start, count):

        if type(code) is six.text_type:
            code = code.encode("utf-8")
        pkg = bytearray.fromhex('01 01 08 6a 01 01 16 00 16 00')
        pkg.extend(bytearray.fromhex("ff 23"))

        self.category = category

        #pkg = bytearray.fromhex("ff 23")

        #count
        last_value = 0x00f00000
        # 这个1还不确定是什么作用，疑似和是否复权有关
        pkg.extend(struct.pack('<B9sHHIH', market, code, category, 1, start, count))
        self.send_pkg = pkg

    def parseResponse(self, body_buf):
        pos = 0

        # 算了，前面不解析了，没太大用
        # (market, code) = struct.unpack("<B9s", body_buf[0: 10])
        pos += 18
        (ret_count, ) = struct.unpack('<H', body_buf[pos: pos+2])
        pos += 2

        klines = []

        for i in range(ret_count):
            year, month, day, hour, minute, pos = get_datetime(self.category, body_buf, pos)
            (open_price, high, low, close, position, volume, price) = struct.unpack("<ffffIIf", body_buf[pos: pos+28])
            # (amount, ) = struct.unpack("f", body_buf[pos+16: pos+16+4]) # 接口无成交额
            amount = 0.0

            pos += 28
            kline = OrderedDict([
                ("open", open_price),
                ("high", high),
                ("low", low),
                ("close", close),
                ("position", position),
                ("volume", volume),
                ("price", price),
                ("year", year),
                ("month", month),
                ("day", day),
                ("hour", hour),
                ("minute", minute),
                ("datetime", "%d-%02d-%02d %02d:%02d" % (year, month, day, hour, minute)),
                ("amount", amount),
            ])

            klines.append(kline)

        return klines



if __name__ == '__main__':
    from OxQuant.pytdx.exhq import TdxExHq_API
    import pandas as pd
    from datetime import datetime
    import os

    api = TdxExHq_API(raise_exception=True)
    init_time = datetime.now()
    # cmd.setParams(4, 7, "10000843", 0, 10)
    # print(cmd.send_pkg)
    # 116.205.143.214
    with api.connect('116.205.143.214', 7727):
    # with api.connect('112.74.214.43', 7727):
        # print(api.to_df(api.get_instrument_bars(TDXParams.KLINE_TYPE_EXHQ_1MIN, 74, 'BABA')).tail())
        iCnt = 0
        nTotal = 0
        nCurrRows = 0
        all_data = pd.DataFrame()
        end_time = datetime.now()

        # 合约/标的代码，K线分类，市场类型
        # symbol = 'IFL8' # 沪深主连 代码
        symbol = 'HSIL8' # 沪深主连 代码
        category = 7; #0 5mins; 1 15mins; 2 30mins; 3 1hour; 4,9 日K; 7,8 1min
        market = 23 # 23 香港恒生指数期货，47 中金所
        EXT_MAX_RECORD_COUNT = 700  # 每次获取的最大记录数700条，每个接口一般不一样

        print(f"Start Time: {init_time}, End Time: {end_time}, Elapsed Time(ms): {(end_time - init_time).total_seconds() * 1000}")

        while True:
            start_time = datetime.now()
            # df = pd.DataFrame(api.get_instrument_bars(9, 47, 'IFL8', iCnt * 700, 700)) # 沪深主连
            # df = pd.DataFrame(api.get_instrument_bars(9, 47, 'IFL8', iCnt * 700, 700)) # 沪深主连
            # df = pd.DataFrame(api.get_instrument_bars(9, 23, symbol, iCnt * EXT_MAX_RECORD_COUNT, EXT_MAX_RECORD_COUNT)) # 香港期货-恒生指数主连 HSIL8
            df = pd.DataFrame(api.get_instrument_bars(category, market, symbol, iCnt * EXT_MAX_RECORD_COUNT, EXT_MAX_RECORD_COUNT)) # 沪深主连
            iCnt += 1
            nCurrRows = len(df)
            print(f"Times: {iCnt}, nCurrRows: {nCurrRows}")

            if nCurrRows > 0:
                nTotal += nCurrRows
                all_data = pd.concat([all_data, df], axis=0)
                print(df)
                # 每次获取数据后都添加到all_data中，而不是只在nCurrRows < 700不成立时添加

            if nCurrRows < EXT_MAX_RECORD_COUNT:
                break

            end_time = datetime.now()
            print(f"Start Time: {start_time}, End Time: {end_time}, Elapsed Time(ms): {(end_time - start_time).total_seconds() * 1000}")

        # 检查all_data是否为空并且包含datetime列
        # all_data.drop(columns=['year', 'month', 'day', 'hour', 'minute'], inplace=True)
        all_data.set_index('datetime', inplace=True)
        all_data.sort_index(inplace=True)
        csvFile = os.path.join(os.getcwd(), "data_tdx", f"{market}_{symbol}_{category}.csv")
        all_data.to_csv(csvFile, index=True, encoding='utf-8-sig')
        print(f'All Data [Rows = {nTotal}] Save In File [{csvFile}]')

        end_time = datetime.now()
        print(
            f"Start Time: {init_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}, "
            f"End Time: {end_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}, "
            f"Elapsed Time(ms): {(end_time - init_time).total_seconds() * 1000:.3f}"
            )
