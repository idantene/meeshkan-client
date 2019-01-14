# type: ignore
# Ignore mypy tests for this file; Attributes for the `meeshkan` package are defined dynamically in
#     __init__.py, so mypy complains about attributes not existing (even though they're well defined).
#     examples for such errors: "error: Name 'meeshkan.Service' is not defined",
#                               "error: Module has no attribute "Service"

""" Command-line interface """
import logging
import sys
import tarfile
import shutil
import tempfile
import os
from typing import Optional

import random
import uuid

import click
import Pyro4
import requests
import tabulate

import meeshkan
from .core.api import Api
from .core.service import Service
from .core.logger import setup_logging, remove_non_file_handlers
from .core.job import Job
from .__utils__ import save_token, get_auth, _get_api, _build_cloud_client
from .start import start_agent

LOGGER = None

CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])


@click.group(context_settings=CONTEXT_SETTINGS)
@click.version_option(version=meeshkan.__version__)
@click.option("--debug", is_flag=True)
@click.option("--silent", is_flag=True)
def cli(debug, silent):
    if not debug:
        sys.tracebacklimit = 0

    global LOGGER  # pylint: disable=global-statement
    meeshkan.config.ensure_base_dirs()
    setup_logging(silent=silent)

    LOGGER = logging.getLogger(__name__)


@cli.command(name='help')
@click.pass_context
def help_cmd(ctx):
    """Show this message and exit."""
    print(ctx.parent.get_help())


@cli.command()
def setup():
    """Configures the Meeshkan client."""
    print("Welcome to Meeshkan!\n")
    if os.path.isfile(meeshkan.config.CREDENTIALS_FILE):
        res = input("Credential file already exists! Are you sure you want to overwrite it? [Y]/n: ")
        if res and res.lower() != "y":  # Any response other than empty or "Y"/"y"
            print("Aborting")
            sys.exit(2)
    token = input("Please enter your client secret: ")
    save_token(token)
    print("You're all set up! Now run \"meeshkan start\" to start the service.")


@cli.command()
def start():
    try:
        start_agent()
    except meeshkan.exceptions.UnauthorizedRequestException as ex:
        print(ex.message)
        sys.exit(1)
    except Exception as ex:  # pylint: disable=broad-except
        print("Starting service failed.")
        LOGGER.exception("Starting service failed.")
        # sys.exit(1)
        raise


@cli.command(name='status')
def daemon_status():
    """Checks and returns the service daemon status."""
    service = Service()
    is_running = service.is_running()
    status = "up and running" if is_running else "configured to run"
    print("Service is {status} on {host}:{port}".format(status=status, host=service.host, port=service.port))
    if is_running:
        print("URI for Daemon is {uri}".format(uri=service.uri))


@cli.command()
@click.argument("job_identifier")
def report(job_identifier):
    """Returns latest scalar from given job identifier."""
    api = _get_api()
    job_id = __find_job_by_identifier(job_identifier)
    if not job_id:
        print("Can't find job with given identifier {identifier}".format(identifier=job_identifier))
        sys.exit(1)
    print("Latest scalar reports for '{name}'".format(name=api.get_job(job_id).name))
    scalar_history = api.get_updates(job_id)
    values_without_time = dict()  # Remove timestamp from report
    for scalar_name, values_with_time in scalar_history.items():
        values_without_time[scalar_name] = [timevalue.value for timevalue in values_with_time]
    print(tabulate.tabulate(values_without_time, headers="keys", tablefmt="fancy_grid"))


@cli.command()
@click.argument('args', nargs=-1)
@click.option("--name", type=str)
@click.option("--report-interval", "-r", type=int, help="Number of seconds between each report for this job.",
              default=Job.DEF_POLLING_INTERVAL, show_default=True)
def submit(args, name, report_interval):
    """Submits a new job to the service daemon."""
    if not args:
        print("CLI error: Specify job.")
        return

    api = _get_api()  # type: Api
    cwd = os.getcwd()
    try:
        job = api.submit(args, name=name, poll_interval=report_interval, cwd=cwd)
    except IOError:
        print("Cannot create job from given arguments! Do all files given exist? {command}".format(command=args))
        sys.exit(1)
    print("Job {number} submitted successfully with ID {id}.".format(number=job.number, id=job.id))


@cli.command(name='cancel')
@click.argument("job_identifier")
def cancel_job(job_identifier):
    """Cancels a queued/running job."""
    job_id = __find_job_by_identifier(job_identifier)
    if not job_id:
        print("Can't find job with given identifier {identifier}".format(identifier=job_identifier))
        sys.exit(1)
    api = _get_api()
    job = api.get_job(job_id)  # type: Job
    if job.status.is_running:
        res = input("Job '{name}' is currently running! "
                    "Are you sure you want to cancel it? y/[N]: ".format(name=job.name))
        if not res or res.lower() != "y":  # Any response other than "Y"/"y"
            print("Aborted")
            sys.exit(2)
    api.cancel_job(job_id)
    print("Canceled '{name}'".format(name=api.get_job(job_id).name))


@cli.command()
def stop():
    """Stops the service daemon."""
    try:
        api = _get_api()  # type: Api
        api.stop()
        LOGGER.info("Service stopped.")
        print("Service stopped.")
    except meeshkan.exceptions.AgentNotAvailableException:
        pass


@cli.command(name='list')
def list_jobs():
    """Lists the job queue and status for each job."""
    api = _get_api()  # type: Api
    jobs = api.list_jobs()
    if not jobs:
        print('No jobs submitted yet.')
        return
    # keys = jobs[0].keys()
    # table_values = [[job[key] for key in keys] for job in jobs]
    print(tabulate.tabulate(jobs, headers="keys", tablefmt="fancy_grid"))


@cli.command()
@click.argument("job_identifier")
def logs(job_identifier):
    """Retrieves the logs for a given job. job_identifier can be UUID, job number of pattern for job name.
    First job name that matches is accessed (allows patterns)."""
    api = _get_api()
    job_id = __find_job_by_identifier(job_identifier)
    if not job_id:
        print("Can't find job with given identifier {identifier}".format(identifier=job_identifier))
        sys.exit(1)
    print("Output for '{name}'".format(name=api.get_job(job_id).name))
    output_path, stderr_file, stdout_file = api.get_job_output(job_id)
    for location in [stdout_file, stderr_file]:
        print(location.name, "\n==============================================\n")
        try:
            with location.open("r") as file_input:
                print(file_input.read())
        except FileNotFoundError:  # File has not yet been created, continue silently
            continue
    print("Job output folder:", output_path, "\n")


@cli.command()
@click.argument("job_identifier")
def notifications(job_identifier):
    """Retrieves notification history for a given job. job_identifier can be UUID, job number of pattern for job name.
    First job name that matches is accessed (allows patterns)."""
    api = _get_api()
    job_id = __find_job_by_identifier(job_identifier)
    if not job_id:
        print("Can't find job with given identifier {identifier}".format(identifier=job_identifier))
        sys.exit(1)
    notification_history = api.get_notification_history(job_id)
    print("Notifications for '{name}'".format(name=api.get_job(job_id).name))
    # Create index list based on longest history available
    row_ids = range(1, max([len(history) for history in notification_history.values()])+1)
    print(tabulate.tabulate(notification_history, headers="keys", showindex=row_ids, tablefmt="fancy_grid"))


@cli.command()
def sorry():
    """Send error logs to Meeshkan HQ. Sorry for inconvenience!
    """
    config, credentials = get_auth()
    status = 0
    cloud_client = _build_cloud_client(config, credentials)
    remove_non_file_handlers()

    # Collect log files to compressed tar
    fname = next(tempfile._get_candidate_names())  # pylint: disable=protected-access
    fname = os.path.abspath("{}.tar.gz".format(fname))
    with tarfile.open(fname, mode='w:gz') as tar:
        for handler in logging.root.handlers:
            try:
                tar.add(handler.baseFilename)
            except AttributeError:
                continue

    try:
        cloud_client.post_payload_with_file(fname, download_link=False)
        print("Logs uploaded to server succesfully.")
    except Exception:  # pylint: disable=broad-except
        LOGGER.exception("Failed uploading logs to server.")
        print("Failed uploading logs to server.")
        status = 1

    os.remove(fname)
    cloud_client.close()
    sys.exit(status)


@cli.command()
def clear():
    """Clears Meeshkan log and job directories in ~/.meeshkan."""
    print("Removing jobs directory at {}".format(meeshkan.config.JOBS_DIR))
    shutil.rmtree(str(meeshkan.config.JOBS_DIR))
    print("Removing logs directory at {}".format(meeshkan.config.LOGS_DIR))
    shutil.rmtree(str(meeshkan.config.LOGS_DIR))
    meeshkan.config.ensure_base_dirs()  # Recreate structure


@cli.command()
@click.pass_context
def clean(ctx):
    """Alias for `meeshkan clear`."""
    ctx.invoke(clear)


@cli.command()
def im_bored():
    "???"
    sources = [r'http://smacie.com/randomizer/family_guy/stewie.txt',
               r'http://smacie.com/randomizer/simpsons/bart.txt',
               r'http://smacie.com/randomizer/simpsons/homer.txt',
               r'http://smacie.com/randomizer/southpark/cartman.txt']
    source = sources[random.randint(0, len(sources)-1)]  # Choose source
    author = os.path.splitext(os.path.basename(source))[0].capitalize()  # Create "Author"
    res = requests.get(source).text.split('\n')  # Get the document and split per line
    print("{}: \"{}\"".format(author, res[random.randint(0, len(res)-1)]))  # Choose line at random


def __find_job_by_identifier(identifier: str) -> Optional[uuid.UUID]:
    """Finds a job by accessing UUID, job numbers and job names.
    Returns the actual job-id if matching. Otherwise returns None.
    """
    # Determine identifier type and search over scheduler
    api = _get_api()
    job_id = job_number = None
    try:
        job_id = uuid.UUID(identifier)
    except ValueError:
        pass

    try:
        job_number = int(identifier)
        if job_number < 1:  # Only accept valid job numbers.
            job_number = None
    except ValueError:
        pass

    # Treat `identifier` as pattern by default (bottom priority when looking up anyway)
    return api.find_job_id(job_id=job_id, job_number=job_number, pattern=identifier)


if __name__ == '__main__':
    cli()  # pylint: disable=no-value-for-parameter
