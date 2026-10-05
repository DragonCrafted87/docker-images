def release_version(metadata):
    try:
        release = metadata["metadata"]["versioning"]["release"]
    except (KeyError, TypeError) as error:
        raise RuntimeError("Fabric metadata has no release version") from error
    if not isinstance(release, str) or not release:
        raise RuntimeError("Fabric metadata has no release version")
    return release


def fetch(  # pylint: disable=too-many-arguments
    url, *, get, sleep, log, attempts=5, timeout=(10, 60), transient=None
):
    if transient is None:
        from requests.exceptions import ConnectionError as RequestsConnectionError
        from requests.exceptions import Timeout

        transient = (RequestsConnectionError, Timeout, OSError)

    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            response = get(url, stream=True, timeout=timeout)
            response.raise_for_status()
            return response
        except transient as error:
            last_error = error
            if attempt == attempts:
                break
            delay = min(2 ** (attempt - 1), 30)
            log(url, attempt, attempts, error, delay)
            sleep(delay)
    raise last_error
