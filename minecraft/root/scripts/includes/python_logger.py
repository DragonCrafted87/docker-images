# -*- coding: utf-8 -*-

from logging import DEBUG
from logging import INFO
from logging import Formatter
from logging import StreamHandler
from logging import getLogger
from sys import stderr
from sys import stdout


class LogLevelFilter:
    def __init__(self, level):
        self.__level = level

    def filter(self, log_record):
        return log_record.levelno == self.__level


def create_logger(name=None):
    # create logger
    log = getLogger(name)
    log.setLevel(DEBUG)

    # create formatter and add it to the handlers
    log_format = Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    # create console handler with a higher log level
    info_handler = StreamHandler(stdout)
    info_handler.setLevel(INFO)
    info_handler.setFormatter(log_format)
    log.addHandler(info_handler)

    # create console handler with a higher log level
    debug_handler = StreamHandler(stderr)
    debug_handler.setLevel(DEBUG)
    debug_handler.setFormatter(log_format)
    debug_handler.addFilter(LogLevelFilter(DEBUG))
    log.addHandler(debug_handler)

    return log
