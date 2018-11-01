""" Command-line interface """
import logging
import click

from client.config import get_config, get_secrets
from client.oauth import TokenStore, token_source
from client.notifiers import post_payloads, CloudNotifier
from client.job import Job, ProcessExecutable
from client.logger import setup_logging


setup_logging()
LOGGER = logging.getLogger(__name__)

CONFIG = get_config()
SECRETS = get_secrets()


def notify():
    """
    Test notifying server for finished job. Requires setting credentials and setting URLs in config.yaml.
    :return:
    """
    auth_url = CONFIG['auth']['url']
    client_id = SECRETS['auth']['client_id']
    client_secret = SECRETS['auth']['client_secret']
    fetch_token = token_source(auth_url=auth_url, client_id=client_id, client_secret=client_secret)
    token_store = TokenStore(fetch_token=fetch_token)
    post_payload = post_payloads(cloud_url=CONFIG['cloud']['url'], token_store=token_store)
    notifier = CloudNotifier(post_payload=post_payload)
    notifier.notify(Job(ProcessExecutable.from_str("echo hello"), job_id=10))


@click.command()
@click.argument('cmd', type=click.Choice(['notify']))
def main(cmd):
    if cmd == 'notify':
        notify()


if __name__ == '__main__':
    # pylint: disable=no-value-for-parameter
    main()