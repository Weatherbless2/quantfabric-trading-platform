# coding=utf-8

from numpy import dtype

from OxQuant.pytdx.params import TDXParams
from OxQuant.pytdx.parser.base import BaseParser
from OxQuant.pytdx.helper import get_datetime, get_volume, get_price, decode_bytes_safely
from collections import OrderedDict
import struct


class GetSecurityList(BaseParser):

    def setParams(self, market, start):
        pkg = bytearray.fromhex(u'0c 01 18 64 01 01 06 00 06 00 50 04')
        pkg_param = struct.pack("<HH", market, start)
        pkg.extend(pkg_param)
        self.send_pkg = pkg

    def parseResponse(self, body_buf):

        pos = 0
        (num, ) = struct.unpack("<H", body_buf[:2])
        print(f"GetSecurityList: num= {num}")
        pos += 2
        stocks = []
        for i in range(num):

            # b'880023d\x00\xd6\xd0\xd0\xa1\xc6\xbd\xbe\xf9.9\x04\x00\x02\x9a\x99\x8cA\x00\x00\x00\x00'
            # 880023 100 中小平均 276782 2 17.575001 0 80846648

            one_bytes = body_buf[pos: pos + 29]

            (code, volunit,
             name_bytes, reversed_bytes1, decimal_point,
            #  pre_close_raw, reversed_bytes2) = struct.unpack("<6sH12sBI4s", one_bytes)
            # pre_close_raw, reversed_bytes2) = struct.unpack("<6sH8s4sBI4s", one_bytes)
            pre_close_raw, reversed_bytes2) = struct.unpack("<6sH8sIBfI", one_bytes)

            code = code.decode("utf-8")
            # name = name_bytes.decode("utf-8").rstrip("\x00")
            name = decode_bytes_safely(name_bytes, "gbk").rstrip("\x00")

            # pre_close = get_volume(pre_close_raw) # 20251016 改为按浮点数格式直接取，get_volume 算法有问题，导致很多昨收价格错误
            pos += 29

            one = OrderedDict(
                [
                    ('code', str(code)),
                    ('volunit', volunit),
                    ('decimal_point', decimal_point),
                    ('name', name),
                    ('pre_close', f"{round(pre_close_raw, decimal_point):.{decimal_point}f}"),
                    ('resv1', reversed_bytes1),
                    ('resv2', reversed_bytes2),
                ]
            )

            stocks.append(one)

        return stocks

MAX_RECORD_COUNT = 1000

if __name__ == '__main__':
    from OxQuant.pytdx.util.best_ip import select_best_ip
    from OxQuant.pytdx.hq import TdxHq_API
    import pandas as pd
    from datetime import datetime
    import os
    
    api = TdxHq_API(raise_exception=True)
    init_time = datetime.now()

    with api.connect("124.71.85.110"): # 通达信广州双线主站1
    # with api.connect("175.178.112.197"): # 通达信广州双线主站2
    # with api.connect("175.178.128.227"): # 通达信深圳双线主站5 盘后可用
        iCnt = 0
        nTotal = 0
        nCurrRows = 0
        df = pd.DataFrame()
        all_data = pd.DataFrame()
        end_time = datetime.now()
        # market = TDXParams.MARKET_BJ # 0:深市 1:沪市
        market = TDXParams.MARKET_SZ # 0:深市 1:沪市 44 北交所必须通过ext api获取
        # market = 2 # 0:深市 1:沪市

        # 创建一个包含数字3-9和字母a-z的列表
        # markets_to_test = list(range(3, 10)) + [chr(c) for c in range(ord('a'), ord('z') + 1)]
        
        # for mkt in markets_to_test:     
        #     # 如果是字符串，使用ord()转换为ASCII码；如果是数字，直接使用
        #     market = ord(mkt) if isinstance(mkt, str) else mkt
        #     print(f"Testing market: {market}")
        #     try:
        #         df = pd.DataFrame(api.get_security_list(market,  iCnt*1000))
        #         if df is not None and len(df) > 0:
        #             print(f"Market: {market}, Code: {df['code'].iloc[0]}, Name: {df['name'].iloc[0]}")
        #             break
        #     except Exception as e:
        #         print(f"Error: {e}")
        #         continue


        print(f"Start Time: {init_time}, End Time: {end_time}, Elapsed Time(ms): {(end_time - init_time).total_seconds() * 1000}")
            
        for iCnt in range(100):
            start_time = datetime.now()
            
            df = pd.DataFrame(api.get_security_list(market,  iCnt*1000))
            # print(df)
            if df is not None and len(df) > 0:
                nCurrRows = len(df)
                all_data = pd.concat([all_data, df], ignore_index=True)
                nTotal += len(df)
            if df is None or len(df) < 1000:
                break

            print(f"Times: {iCnt}, nCurrRows: {nCurrRows}, Total: {nTotal}")

            
        end_time = datetime.now()
        print(f"Start Time: {start_time}, End Time: {end_time}, Elapsed Time(ms): {(end_time - start_time).total_seconds() * 1000}")

        print(all_data.head(100))

        # 检查all_data是否为空并且包含datetime列
        # all_data.drop(columns=['year', 'month', 'day', 'hour', 'minute'], inplace=True)
        
        # 根据code列排序
        all_data['code'] = '\t' + all_data['code']
        all_data.sort_values('code', inplace=True)
        
        csvFile = os.path.join(os.getcwd(), "data_tdx", f"{'sh' if market==1 else 'sz' if market==0 else 'bj'}_security_list.csv")
        all_data.to_csv(csvFile, index=False, encoding='utf-8-sig')
        print(f'All Data [rows={nTotal}] Save In File [{csvFile}]')

        end_time = datetime.now()
        print(
            f"Start Time: {init_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}, "
            f"End Time: {end_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}, "
            f"Elapsed Time(ms): {(end_time - init_time).total_seconds() * 1000:.3f}"
            )
