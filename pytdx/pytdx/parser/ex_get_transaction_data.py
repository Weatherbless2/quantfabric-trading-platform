# coding=utf-8

from OxQuant.pytdx.parser.base import BaseParser
from OxQuant.pytdx.helper import get_datetime, get_volume, get_price, get_time
from collections import OrderedDict
import struct
import six
import datetime

class GetTransactionData(BaseParser):

    def setParams(self, market, code, start, count):
        if type(code) is six.text_type:
            code = code.encode("utf-8")
        pkg = bytearray.fromhex('01 01 08 00 03 01 12 00 12 00 fc 23')
        pkg.extend(struct.pack("<B9siH", market, code, start, count))
        self.send_pkg = pkg

    def parseResponse(self, body_buf):

        pos = 0
        market, code, _rese, num = struct.unpack('<B9s4sH', body_buf[pos: pos + 16])
        print(f"market: {market}, code: {code.decode('utf-8')}, num: {num}, resv: {_rese}")
        pos += 16
        result = []
        for i in range(num):

            (raw_time, price, volume, zengcang, direction) = struct.unpack("<HIIiH", body_buf[pos: pos + 16])

            pos += 16
            hour = raw_time // 60
            minute = raw_time % 60
            second = direction % 10000
            nature = direction ### 保持老接口的兼容性

            if second > 59:
                second = 0

            date = datetime.datetime.combine(datetime.date.today(), datetime.time(hour,minute,second))

            value = direction // 10000
            price = price / 1000.0

            if value == 0:
                direction = 1
                if zengcang > 0:
                    if volume > zengcang:
                        nature_name = "多开"
                    elif volume == zengcang:
                        nature_name = "双开"
                elif zengcang == 0:
                    nature_name = "多换"
                else:
                    if volume == -zengcang:
                        nature_name = "双平"
                    else:
                        nature_name = "空平"
            elif value == 1:
                direction = -1
                if zengcang > 0:
                    if volume > zengcang:
                        nature_name = "空开"
                    elif volume == zengcang:
                        nature_name = "双开"
                elif zengcang == 0:
                    nature_name = "空换"
                else:
                    if volume == -zengcang:
                        nature_name = "双平"
                    else:
                        nature_name = "多平"
            else:
                direction = 0
                if zengcang > 0:
                    if volume > zengcang:
                        nature_name = "开仓"
                    elif volume == zengcang:
                        nature_name = "双开"
                elif zengcang < 0:
                    if volume > -zengcang:
                        nature_name = "平仓"
                    elif volume == -zengcang:
                        nature_name = "双平"
                else:
                    nature_name = "换手"

            if market in [31,48]:
                if nature == 0:
                    direction = 1
                    nature_name = 'B'
                elif nature == 256:
                    direction = -1
                    nature_name = 'S'
                else: #512
                    direction = 0
                    nature_name = ''


            result.append(OrderedDict([
                ("date", date),
                ("hour", hour),
                ("minute", minute),
                ("second", second),
                ("price", price),
                ("volume", volume),
                ("zengcang", zengcang),
                ("nature", nature),
                ("nature_mark", nature // 10000),
                ("nature_value", nature % 10000),
                ("nature_name", nature_name),
                ("direction", direction),
            ]))

        return result

EXT_MAX_RECORD_COUNT = 1800

if __name__ == "__main__":
    # from OxQuant.pytdx.exhq import TdxExHq_API

    # apiX = TdxExHq_API()
    # # with api.connect('121.14.110.210', 7727):
    #     print(apiX.to_df(apiX.get_transaction_data(47, 'IFL9', 0, 2000)))
        # print(api.to_df(api.get_transaction_data(31, "00020")))
    from OxQuant.pytdx.exhq import TdxExHq_API
    import pandas as pd
    from datetime import datetime
    import os
    apiX = TdxExHq_API(raise_exception=True)
    init_time = datetime.now()
    with apiX.connect('116.205.143.214', 7727): # 扩展市场广州双线1
        iCnt = 0
        nTotal = 0
        nCurrRows = 0
        all_data = pd.DataFrame()
        end_time = datetime.now()
        symbol = 'IFL8' # 沪深主连 代码
        print(f"Start Time: {init_time}, End Time: {end_time}, Elapsed Time(ms): {(end_time - init_time).total_seconds() * 1000}")
        while True:
            start_time = datetime.now()
            df = pd.DataFrame(apiX.get_transaction_data(47, symbol, iCnt * EXT_MAX_RECORD_COUNT, EXT_MAX_RECORD_COUNT)) # 沪深主连
            iCnt += 1
            nCurrRows = len(df)
            print(f"Times: {iCnt}, nCurrRows: {nCurrRows}")
            if nCurrRows > 0:
                print(df)
                nTotal += nCurrRows
                all_data = pd.concat([all_data, df], axis=0)
            if nCurrRows < EXT_MAX_RECORD_COUNT:
                break
            end_time = datetime.now()
            print(f"Start Time: {start_time}, End Time: {end_time}, Elapsed Time(ms): {(end_time - start_time).total_seconds() * 1000}")
        all_data.drop(columns=['second', 'hour', 'minute'], inplace=True)
        all_data.set_index('date', inplace=True)
        all_data.sort_index(inplace=True)
        csvFile = os.path.join(os.getcwd(), "data_tdx", f"{symbol}_transactions.csv")
        all_data.to_csv(csvFile, index=True, encoding='utf-8-sig')
        print(f'All Data[{nTotal} rows]Save In File[{csvFile}]')
        end_time = datetime.now()
        print(
            f"Start Time: {init_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}, "
            f"End Time: {end_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}, "
            f"Elapsed Time(ms): {(end_time - init_time).total_seconds() * 1000:.3f}"
            )
