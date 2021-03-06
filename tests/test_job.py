# pylint:disable=redefined-outer-name
import os
from pathlib import Path
import uuid

import pytest


from meeshkan.core.job import ProcessExecutable, Job, JobStatus

JOBS_OUTPUT_PATH = Path(os.path.dirname(__file__)).joinpath('resources', 'jobs')

STDOUT_FILE = JOBS_OUTPUT_PATH.joinpath('stdout')
STDERR_FILE = JOBS_OUTPUT_PATH.joinpath('stderr')


@pytest.fixture
def clean_up():
    def remove_file(path: Path):
        if path.is_file():
            os.remove(str(path))

    def remove_stdout_stderr():
        remove_file(STDOUT_FILE)
        remove_file(STDERR_FILE)

    yield remove_stdout_stderr()
    remove_stdout_stderr()


def test_proc_exec_output_path(clean_up):  # pylint: disable=unused-argument,redefined-outer-name
    some_string = str(uuid.uuid4())
    executable = ProcessExecutable(args=('echo', some_string), output_path=JOBS_OUTPUT_PATH)
    executable.launch_and_wait()
    assert STDOUT_FILE.is_file(), "stdout file should be created after the process was launched"
    assert STDERR_FILE.is_file(), "stderr file should be created after the process was launched"
    with open(STDOUT_FILE, 'r') as file:
        text = file.read()
    assert text == some_string + '\n', "Job was expected to write '{}' to stdout!".format(some_string)


def test_proc_exec_args_raise_file_not_found():
    with pytest.raises(IOError):
        ProcessExecutable(args=('python', "non_existing.py"))


def test_job_args_to_full_path_with_runtime():
    cwd, base = os.path.split(__file__)
    job = Job.create_job(args=(base, 'another_argument'), cwd=cwd, job_number=1)
    assert len(job.executable.args) == 3, "`create_job` should add the python executable to the argument list"
    assert job.executable.args[1] == __file__, "Expected '{}' to be full " \
                                               "path '{}'".format(job.executable.args[1], __file__)


JOB_NAME = "spameggs"


@pytest.fixture
def example_job():
    cwd, base = os.path.split(__file__)
    return Job.create_job(args=(base, 'another argument'), cwd=cwd, job_number=1, name=JOB_NAME)


@pytest.fixture
def notebook_job():
    cwd, _ = os.path.split(__file__)
    return Job.create_job(args=(os.path.join("resources", "dummy_nb.ipynb"),), cwd=cwd, job_number=1)

def test_job_cancel_changes_status(example_job):
    example_job.cancel()  # Runs with
    assert example_job.status == JobStatus.CANCELLED_BY_USER


def test_job_inherits_attributes(example_job):
    assert example_job.scalar_history is not None
    assert example_job.name == JOB_NAME


def test_job_add_tracked_works(example_job):
    example_job.add_scalar_to_history("scalar", 0.1)


def test_job_add_condition_works(example_job):
    example_job.add_condition("train loss", "evaluation loss",
                              condition=lambda train_loss, eval_loss: abs(train_loss - eval_loss) > 0.2,
                              only_relevant=True)

def test_executable_notebook(notebook_job):
    expected_conversion = "#!/usr/bin/env python\n# coding: utf-8\n\n# In[1]:\n\n\nget_ipython().run_line_magic" \
                          "('load_ext', 'autoreload  # Have some magic functions to convert')\nget_ipython().run_" \
                          "line_magic('autoreload', '2')\nimport numpy as np  # Some non-standard library\nimport " \
                          "non-existing-module  # Shouldn't fail anyway\n\n\n# In[2]:\n\n\nplus_one = True\n\n\n# " \
                          "In[3]:\n\n\ndef add(*args):  # Some bogus function here\n    global add_result\n    add_" \
                          "result = 0\n    if not args:\n        args = sys.argv[1:]\n    for val in args:\n        " \
                          "add_result += int(val)\n    if plus_one:\n        add_result += 1\n    print(add_result)" \
                          "\n\n\n# In[4]:\n\n\nadd(*['3', '5', '1'])\n\n\n# In[1]:\n\n\nfiles = get_ipython()" \
                          ".getoutput('ls  # Some more magic stuff')\n\n"
    args = notebook_job.executable.args
    assert len(args) == 2, "Expecting interpreter to be added to .ipynb Jobs"
    assert args[0] == "ipython", "Expecting interpreter to be ipython"
    assert open(args[1]).read() == expected_conversion, "Expected output of conversion does not match"

def test_executable_notebook_run(notebook_job):
    expected_outcome = '10\n'  # ANSI-encoded via IPython interpreter

    def clean_failing_lines(line):
        return "non-existing-module" not in line and "run_line_magic" not in line

    # Remove some false magic lines from the code
    converted_script = notebook_job.executable.args[1]
    with open(converted_script) as script_fd:
        script_code = list(filter(clean_failing_lines, script_fd.readlines()))
    with open(converted_script, 'w') as script_fd:
        script_fd.writelines(script_code)
        script_fd.flush()

    assert notebook_job.launch_and_wait() == 0, "Expected job to run smoothly"
    assert notebook_job.stdout.read_text().endswith(expected_outcome), "Expected outcome: 10"
