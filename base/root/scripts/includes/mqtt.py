# -*- coding: utf-8 -*-

from os import getenv

from includes.python_logger import create_logger  # pylint: disable=no-name-in-module

LOGGER = create_logger("mqtt")


def mqtt_auth(username, password):
    if username and password:
        return {"username": username, "password": password}
    return None


def settings():
    return {
        "hostname": getenv("MQTT_SERVER", "localhost"),
        "port": int(getenv("MQTT_SERVER_PORT", "1883")),
        "auth": mqtt_auth(getenv("MQTT_USERNAME", None), getenv("MQTT_PASSWORD", None)),
    }


def publish(topic, payload, single=None, protocol=None):
    if single is None or protocol is None:
        from paho.mqtt.client import MQTTv311
        from paho.mqtt.publish import single as mqtt_single

        if single is None:
            single = mqtt_single
        if protocol is None:
            protocol = MQTTv311

    chosen = settings()
    LOGGER.info("MQTT %s payload %s", topic, payload)
    single(
        topic,
        payload=payload,
        qos=0,
        retain=True,
        hostname=chosen["hostname"],
        port=chosen["port"],
        client_id="",
        keepalive=60,
        will=None,
        auth=chosen["auth"],
        tls=None,
        protocol=protocol,
        transport="tcp",
    )
