import http.client
from .logger import setup_logging
from .config import get_config
import logging
import json

logger = logging.getLogger(__name__)
conf = get_config()


def get_token():
    auth = conf['env']['auth']
    auth_url = auth['url']
    client_id = auth['client_id']
    client_secret = auth['client_secret']

    conn = http.client.HTTPSConnection(auth_url)

    payload = {
        'client_id': client_id,
        'client_secret': client_secret,
        'audience': "https://cloud-api.meeshkan.io",
        "grant_type":"client_credentials"
    }

    headers = {'content-type': "application/json"}
    conn.request("POST", "/oauth/token", json.dumps(payload), headers)

    res = conn.getresponse()
    return res.read().decode("utf-8")


def main():
    setup_logging()
    token = get_token()
    logger.info(token)


if __name__ == '__main__':
    main()
