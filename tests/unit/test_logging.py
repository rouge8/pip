import errno
import logging
import os
import time

import pytest
from mock import patch
from pip._vendor.six import PY2

from pip._internal.utils.logging import (
    BrokenStdoutLoggingError,
    ColorizedStreamHandler,
    IndentingFormatter,
)
from pip._internal.utils.misc import captured_stderr, captured_stdout

logger = logging.getLogger(__name__)


# This is a Python 2/3 compatibility helper.
def _make_broken_pipe_error():
    """
    Return an exception object representing a broken pipe.
    """
    if PY2:
        # This is one way a broken pipe error can show up in Python 2
        # (a non-Windows example in this case).
        return IOError(errno.EPIPE, 'Broken pipe')

    return BrokenPipeError()  # noqa: F821


class TestIndentingFormatter(object):
    """
    Test `pip._internal.utils.logging.IndentingFormatter`.
    """

    def setup(self):
        self.old_tz = os.environ.get('TZ')
        os.environ['TZ'] = 'UTC'
        # time.tzset() is not implemented on some platforms (notably, Windows).
        if hasattr(time, 'tzset'):
            time.tzset()

    def teardown(self):
        if self.old_tz:
            os.environ['TZ'] = self.old_tz
        else:
            del os.environ['TZ']
        if 'tzset' in dir(time):
            time.tzset()

    def make_record(self, msg, level_name):
        level_number = getattr(logging, level_name)
        attrs = dict(
            msg=msg,
            created=1547704837.040001,
            msecs=40,
            levelname=level_name,
            levelno=level_number,
        )
        record = logging.makeLogRecord(attrs)

        return record

    @pytest.mark.parametrize('level_name, expected', [
        ('DEBUG', 'hello\nworld'),
        ('INFO', 'hello\nworld'),
        ('WARNING', 'WARNING: hello\nworld'),
        ('ERROR', 'ERROR: hello\nworld'),
        ('CRITICAL', 'ERROR: hello\nworld'),
    ])
    def test_format(self, level_name, expected):
        """
        Args:
          level_name: a logging level name (e.g. "WARNING").
        """
        record = self.make_record('hello\nworld', level_name=level_name)
        f = IndentingFormatter(fmt="%(message)s")
        assert f.format(record) == expected

    @pytest.mark.parametrize('level_name, expected', [
        ('INFO',
         '2019-01-17T06:00:37,040 hello\n'
         '2019-01-17T06:00:37,040 world'),
        ('WARNING',
         '2019-01-17T06:00:37,040 WARNING: hello\n'
         '2019-01-17T06:00:37,040 world'),
    ])
    def test_format_with_timestamp(self, level_name, expected):
        record = self.make_record('hello\nworld', level_name=level_name)
        f = IndentingFormatter(fmt="%(message)s", add_timestamp=True)
        assert f.format(record) == expected

    @pytest.mark.parametrize('level_name, expected', [
        ('WARNING', 'DEPRECATION: hello\nworld'),
        ('ERROR', 'DEPRECATION: hello\nworld'),
        ('CRITICAL', 'DEPRECATION: hello\nworld'),
    ])
    def test_format_deprecated(self, level_name, expected):
        """
        Test that logged deprecation warnings coming from deprecated()
        don't get another prefix.
        """
        record = self.make_record(
            'DEPRECATION: hello\nworld', level_name=level_name,
        )
        f = IndentingFormatter(fmt="%(message)s")
        assert f.format(record) == expected


class TestColorizedStreamHandler(object):

    def _make_log_record(self):
        attrs = {
            'msg': 'my error',
        }
        record = logging.makeLogRecord(attrs)

        return record

    def test_broken_pipe_in_stderr_flush(self):
        """
        Test sys.stderr.flush() raising BrokenPipeError.

        This error should _not_ trigger an error in the logging framework.
        """
        record = self._make_log_record()

        with captured_stderr() as stderr:
            handler = ColorizedStreamHandler(stream=stderr)
            with patch('sys.stderr.flush') as mock_flush:
                mock_flush.side_effect = _make_broken_pipe_error()
                # The emit() call raises no exception.
                handler.emit(record)

            err_text = stderr.getvalue()

        assert err_text.startswith('my error')
        # Check that the logging framework tried to log the exception.
        if PY2:
            assert 'IOError: [Errno 32] Broken pipe' in err_text
            assert 'Logged from file' in err_text
        else:
            assert 'Logging error' in err_text
            assert 'BrokenPipeError' in err_text
            assert "Message: 'my error'" in err_text

    def test_broken_pipe_in_stdout_write(self):
        """
        Test sys.stdout.write() raising BrokenPipeError.

        This error _should_ trigger an error in the logging framework.
        """
        record = self._make_log_record()

        with captured_stdout() as stdout:
            handler = ColorizedStreamHandler(stream=stdout)
            with patch('sys.stdout.write') as mock_write:
                mock_write.side_effect = _make_broken_pipe_error()
                with pytest.raises(BrokenStdoutLoggingError):
                    handler.emit(record)

    def test_broken_pipe_in_stdout_flush(self):
        """
        Test sys.stdout.flush() raising BrokenPipeError.

        This error _should_ trigger an error in the logging framework.
        """
        record = self._make_log_record()

        with captured_stdout() as stdout:
            handler = ColorizedStreamHandler(stream=stdout)
            with patch('sys.stdout.flush') as mock_flush:
                mock_flush.side_effect = _make_broken_pipe_error()
                with pytest.raises(BrokenStdoutLoggingError):
                    handler.emit(record)

            output = stdout.getvalue()

        # Sanity check that the log record was written, since flush() happens
        # after write().
        assert output.startswith('my error')
