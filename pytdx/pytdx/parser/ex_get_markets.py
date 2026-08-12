# coding=utf-8

from OxQuant.pytdx.parser.base import BaseParser
from OxQuant.pytdx.helper import get_datetime, get_volume, get_price
from collections import OrderedDict
import struct
import pandas as pd

class GetMarkets(BaseParser):

    def setup(self):
        self.send_pkg = bytearray.fromhex("01 02 48 69 00 01 02 00 02 00 f4 23")

    def parseResponse(self, body_buf):

        pos = 0
        (cnt, ) = struct.unpack("<H", body_buf[pos: pos + 2])
        print(f"返回记录数：{cnt}")

        pos += 2

        result = []
        for i in range(cnt):
            # 64byte for one
            (category, raw_name, market, raw_short_name, _, unknown_bytes) = struct.unpack("<B32sB2s26s2s", body_buf[pos: pos+64])
            pos += 64

            # if category == 0 and market == 0:
            #     continue

            name = raw_name.decode("gbk")
            short_name = raw_short_name.decode("gbk")

            result.append(OrderedDict(
                [
                    ("market", market),
                    ("category", category),
                    ("name", name.rstrip("\x00")),
                    ("short_name", short_name.rstrip("\x00")),
                    #('unknown_bytes', unknown_bytes)
                ]
            ))

        return result

if __name__ == '__main__':

    from OxQuant.pytdx.exhq import TdxExHq_API
    import pandas as pd
    from datetime import datetime
    import os
    apiX = TdxExHq_API(raise_exception=True)
    init_time = datetime.now()
    # cmd.setParams(4, 7, "10000843", 0, 10)
    # print(cmd.send_pkg)
    # with api.connect('112.74.214.43', 7727):
    with apiX.connect('116.205.143.214', 7727): # 扩展市场广州双线1
        iCnt = 0
        nTotal = 0
        nCurrRows = 0
        all_data = pd.DataFrame()
        end_time = datetime.now()
        print(f"Start Time: {init_time}, End Time: {end_time}, Elapsed Time(ms): {(end_time - init_time).total_seconds() * 1000}")
        df = pd.DataFrame(apiX.get_markets())
        nCurrRows = len(df)
        print(f"Times: {iCnt+1}, nCurrRows: {nCurrRows}")
        if nCurrRows > 0:
            print(df)

        all_data = pd.concat([all_data, df], axis=0)
        csvFile = os.path.join(os.getcwd(), "data_tdx", "EX_Markets.csv")
        all_data.to_csv(csvFile, index=False, encoding='utf-8-sig')
        print(f'All Data[rows={nCurrRows}] Save in File [{csvFile}]')
        end_time = datetime.now()
        print(f"Start Time: {init_time}, End Time: {end_time}, Elapsed Time(ms): {(end_time - init_time).total_seconds() * 1000}")