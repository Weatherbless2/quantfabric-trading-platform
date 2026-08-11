# coding=utf-8

from OxQuant.pytdx.parser.base import BaseParser
from OxQuant.pytdx.helper import get_datetime, get_volume, get_price
from collections import OrderedDict
import struct

"""
tradex 结果

﻿        7、查询分时...

时间    价格    均价    成交量  成交额
09:30   3706.199951     3706.199951     27      13336
09:31   3705.199951     3705.910400     11      13335
09:32   3704.600098     3705.473633     19      13328
09:33   3701.399902     3704.717041     13      13324
09:34   3700.800049     3704.556152     3       13323
09:35   3699.800049     3703.379395     24      13321
09:36   3695.800049     3702.544922     12      13319
09:37   3700.600098     3702.510010     2       13318
"""


class GetMinuteTimeData(BaseParser):

    def setParams(self, market, code):
        pkg = bytearray.fromhex("01 07 08 00 01 01 0c 00 0c 00 0b 24")
        code = code.encode("utf-8")
        pkg.extend(struct.pack('<B9s', market, code))
        self.send_pkg = pkg


    def parseResponse(self, body_buf):
        pos = 0
        market, code, num = struct.unpack('<B9sH', body_buf[pos: pos+12])
        pos += 12

        result = []
        for i in range(num):

            (raw_time, price, avg_price, volume, amount) = struct.unpack("<HffII", body_buf[pos: pos+18])
            pos += 18
            hour = int(raw_time // 60)
            minute = int(raw_time % 60)

            result.append(OrderedDict([
                ("hour", hour),
                ("minute", minute),
                ("price", price),
                ("avg_price", avg_price),
                ("volume", volume),
                ("open_interest", amount),
            ]))

        return result
    
EXT_MAX_RECORD_COUNT = 1800
if __name__ == "__main__":
    from OxQuant.pytdx.exhq import TdxExHq_API
    from OxQuant.QAUtil import QA_util_get_real_tradeday
    import pandas as pd
    from datetime import datetime
    import os
    apiX = TdxExHq_API(raise_exception=True)
    init_time = datetime.now()
    tradeday = QA_util_get_real_tradeday()
    with apiX.connect('116.205.143.214', 7727): # 扩展市场广州双线1
        iCnt = 0
        nTotal = 0
        nCurrRows = 0
        all_data = pd.DataFrame()
        end_time = datetime.now()
        # symbol = 'IFL8' # 沪深主连 代码
        symbol = 'HSIL8' # 沪深主连 代码
        print(f"Start Time: {init_time}, End Time: {end_time}, Elapsed Time(ms): {(end_time - init_time).total_seconds() * 1000}")
        while True:
            start_time = datetime.now()
            # df = pd.DataFrame(apiX.get_minute_time_data(47, symbol)) # 沪深主连
            df = pd.DataFrame(apiX.get_minute_time_data(23, symbol)) # 沪深主连
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
        
        all_data['time'] = all_data.apply(
            lambda row: f"{int(row['hour']):02d}:{int(row['minute']):02d}:00",
            axis=1
        )
        print(all_data)
        all_data.set_index('time', inplace=True)
        csvFile = os.path.join(os.getcwd(), "data_tdx", f"{symbol}_min_time.csv")
        all_data.to_csv(csvFile, index=True, encoding='utf-8-sig')
        print(f'All Data[{nTotal} rows]Save In File[{csvFile}]')
        end_time = datetime.now()
        print(
            f"Start Time: {init_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}, "
            f"End Time: {end_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}, "
            f"Elapsed Time(ms): {(end_time - init_time).total_seconds() * 1000:.3f}"
            )
