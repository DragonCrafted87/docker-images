#!/usr/bin/python3
# -*- coding: utf-8 -*-

from datetime import datetime
from json import dumps as dump_to_json
from os import getenv
from pathlib import PurePath
from statistics import fmean as mean
from statistics import median
from time import sleep
from time import time

from includes.mqtt import publish  # pylint: disable=no-name-in-module
from includes.python_logger import create_logger  # pylint: disable=no-name-in-module
from ping3 import ping
from requests import get as requests_get
from requests import post as requests_post
from requests.exceptions import ConnectionError as RequestsConnectionError

LOGGER = create_logger(PurePath(__file__).stem)
SLEEP_BETWEEN_MEASUREMENTS = 5
MEASUREMENT_SIZES = [
    100000,
    1000000,
    10000000,
    25000000,
    50000000,
    100000000,
    250000000,
    500000000,
    1000000000,
]


def download(download_bytes):
    try:
        start_time = time()
        _ = requests_get(f"https://speed.cloudflare.com/__down?bytes={download_bytes}")
        finish_time = time()

        sleep(SLEEP_BETWEEN_MEASUREMENTS)

        duration = finish_time - start_time
        measurement = (download_bytes / duration) / 100000
    except RequestsConnectionError:
        measurement = 0

    return measurement


def upload(upload_bytes):
    try:
        upload_data = bytearray(upload_bytes)
        start_time = time()
        _ = requests_post("https://speed.cloudflare.com/__up", data=upload_data)
        finish_time = time()

        sleep(SLEEP_BETWEEN_MEASUREMENTS)

        duration = finish_time - start_time
        measurement = (upload_bytes / duration) / 100000
    except RequestsConnectionError:
        measurement = 0

    return measurement


def run_speed_test(iterations_list, operation):
    measurements = []

    for index, iterations in enumerate(iterations_list):
        size = MEASUREMENT_SIZES[index]

        for _ in range(iterations):
            measurements.append(operation(size))

    return measurements


def calculate_ping():
    ping_count = int(getenv("PING_COUNT", "20"))

    ping_measurements = []
    for _ in range(ping_count):
        value = None
        while not value:
            value = ping("cloudflare.com", unit="ms")
        ping_measurements.append(value)

    median_ping = median(ping_measurements)
    ping_jitter = mean(
        [
            abs(ping_measurements[index] - ping_measurements[index - 1])
            for index in range(1, len(ping_measurements))
        ]
    )
    return (median_ping, ping_jitter)


def calculate_percentile(data, percentile):
    sorted_data = sorted(data)
    count = len(sorted_data)
    rank = count * percentile / 100
    if rank.is_integer():
        return_value = sorted_data[int(rank)]
    else:
        rank = int(rank) - 1
        return_value = (sorted_data[rank] + sorted_data[rank + 1]) / 2
    return return_value


def iteration_counts(name, default):
    return list(map(int, getenv(name, default).split(",")))


def calculate_download_percentile(percentile):
    download_iterations = iteration_counts("DOWNLOAD_ITERATIONS", "10,8,6,4,2")

    download_measurements = run_speed_test(download_iterations, download)
    LOGGER.info("Download %s", download_measurements)

    return calculate_percentile(download_measurements, percentile)


def calculate_upload_percentile(percentile):
    upload_iterations = iteration_counts("UPLOAD_ITERATIONS", "8,6,4,2")

    upload_measurements = run_speed_test(upload_iterations, upload)
    LOGGER.info("Upload %s", upload_measurements)

    return calculate_percentile(upload_measurements, percentile)


def main():
    percentile = int(getenv("PERCENTILE", "90"))

    median_ping, ping_jitter = calculate_ping()
    download_percentile = calculate_download_percentile(percentile)
    upload_percentile = calculate_upload_percentile(percentile)

    LOGGER.info("Ping %s", median_ping)
    LOGGER.info("Jitter %s", ping_jitter)
    LOGGER.info("Download Percentile %s", download_percentile)
    LOGGER.info("Upload Percentile %s", upload_percentile)

    time_string_payload = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    json_payload = dump_to_json(
        {
            "median_ping": median_ping,
            "ping_jitter": ping_jitter,
            "download_mbps": download_percentile,
            "upload_mbps": upload_percentile,
        }
    )

    publish("speedtest", time_string_payload)
    publish("speedtest/attributes", json_payload)


if __name__ == "__main__":
    main()
