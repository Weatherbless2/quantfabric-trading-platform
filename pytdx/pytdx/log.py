# coding=utf-8

import logging
import os

# 配置环境变量 TDX_DEBUG=True 开启调试模式
DEBUG = os.getenv("TDX_DEBUG", "")

if DEBUG:
    LOGLEVEL = logging.DEBUG
else:
    LOGLEVEL = logging.INFO

log = logging.getLogger("PYTDX")

log.setLevel(LOGLEVEL)
ch = logging.StreamHandler()
ch.setLevel(LOGLEVEL)
# create formatter
formatter = logging.Formatter('%(asctime)s.%(msecs)03d - %(name)s - %(levelname)s - %(message)s')
# add formatter to ch
ch.setFormatter(formatter)
log.addHandler(ch)