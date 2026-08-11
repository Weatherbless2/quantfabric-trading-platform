# coding=utf-8

from OxQuant.pytdx.params import TDXParams
from OxQuant.pytdx.parser.base import BaseParser
from OxQuant.pytdx.helper import get_datetime, get_volume, get_price
from collections import OrderedDict
import struct
import pandas as pd


class GetInstrumentInfo(BaseParser):

    """
    01 08 04 0b 00 01 0b 00 0b 00

    00 24
    08 类别
    00 00 00 00
    26 00  数量  38 个
    01 00 未知

    In [8]: 11402/38
    Out[8]: 300.05263157894734

    In [9]: 11402%38
    Out[9]: 2

    """
    def setParams(self, start=0, count=100, category=0, market=0):
        pkg = bytearray.fromhex("01 04 48 67 00 01 08 00 08 00 f5 23")
        # pkg.extend(struct.pack('<IHHH', start, count, category, market))
        pkg.extend(struct.pack('<IH', start, count))
        self.send_pkg = pkg

    def parseResponse(self, body_buf):
        pos = 0
        start, count = struct.unpack("<IH", body_buf[:6])
        print(f"GetInstrumentInfo: start= {start}, count= {count}")
        pos += 6
        result = []
        for i in range(count):
            (category, market, unused_bytes, code_raw, name_raw, desc_raw) = \
                struct.unpack("<BB3s9s17s9s", body_buf[pos: pos+40])

            # if category == TDXParams.CATEGORY_NONE and market == TDXParams.MARKET_NONE:
            #     continue

            code = code_raw.decode("gbk", 'ignore')
            name = name_raw.decode("gbk", 'ignore')
            desc = desc_raw.decode("gbk", 'ignore')
            if market == TDXParams.MARKET_BJ :
            # if '4300' in code or '9200' in code:
                print(f"market={market} code={code} name={name} desc={desc}")

            # if (code[0:1] == '4' or code[0:1] == '9'):
                # print(f"market={market} code={code} name={name} desc={desc}")


            one = OrderedDict(
                [
                    ("category", category),
                    ("market", market),
                    ("code", code.rstrip("\x00")),
                    ("name", name.rstrip("\x00")),
                    ("desc", desc.rstrip("\x00")),
                ]
            )

            pos += 64
            result.append(one)

        return result

EXT_MAX_RECORD_COUNT = 1021 # 大于1021 只返回1021行，经过测试测试，多次调用主要耗时在api调用，所以设置为最大1020
TARGET_MARKETS = [2, 28, 29, 30, 42, 47, 60, 65, 66]

if __name__ == '__main__':
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
        # symbol = 'IFL8' # 沪深主连 代码
        print(f"Start Time: {init_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}, "
        f"End Time: {end_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}, "
        f"Elapsed Time(ms): {(end_time - init_time).total_seconds() * 1000:.3f}"
        )

        while True:
            start_time = datetime.now()
            df = pd.DataFrame(apiX.get_instrument_info(iCnt * EXT_MAX_RECORD_COUNT, EXT_MAX_RECORD_COUNT)) # 沪深主连
            iCnt += 1
            nCurrRows = len(df)
            nTotal += nCurrRows
            print(f"Times: {iCnt}, nCurrRows: {nCurrRows}, Total: {nTotal}")

            if nCurrRows > 0:
                # print(df)

                filter_data = df[df["market"].isin(TARGET_MARKETS)]
                # print(filter_data)
                all_data = pd.concat([all_data, filter_data], ignore_index=True)

            if nCurrRows < EXT_MAX_RECORD_COUNT:
                break

            end_time = datetime.now()
            print(f"Start Time: {start_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}, "
            f"End Time: {end_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}, "
            f"Elapsed Time(ms): {(end_time - start_time).total_seconds() * 1000:.3f}"
            )

        # all_data.drop(columns=['second', 'hour', 'minute'], inplace=True)
        # all_data.set_index('date', inplace=True)
        # all_data.sort_index(inplace=True)

        csvFile = os.path.join(os.getcwd(), "data_tdx", "instrument_info.csv")
        all_data.to_csv(csvFile, index=False, encoding='utf-8-sig')
        print(f'All Data[{nTotal} rows]Save In File[{csvFile}]')

        end_time = datetime.now()
        print(
            f"Start Time: {init_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}, "
            f"End Time: {end_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}, "
            f"Elapsed Time(ms): {(end_time - init_time).total_seconds() * 1000:.3f}"
            )