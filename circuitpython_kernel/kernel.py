# -*- coding: utf-8 -*-
"""Basic functionality of CircuitPython kernel."""
import ast
import logging
import re
import time

from serial.serialutil import SerialException
from ipykernel.kernelbase import Kernel
from .board import Board, BoardError
from .version import __version__

# Create global KERNEL_LOGGER for debug messages.
KERNEL_LOGGER = logging.getLogger(__name__)


class CircuitPyKernel(Kernel):
    """CircuitPython kernel implementation."""

    protocol_version = '4.5.2'
    implementation = 'circuitpython_kernel'
    implementation_version = __version__
    language_info = {
        'name': 'python',
        'version': '3',
        'mimetype': 'text/x-python',
        'file_extension': '.py',
        'pygments_lexer': 'python3',
        'codemirror_mode': {'name': 'python', 'version': 3},
    }
    banner = "CircuitPython"
    help_links = [
        {
            'text': 'CircuitPython kernel',
            'url': 'https://github.com/adafruit/circuitpython_kernel',
        }
    ]

    def __init__(self, **kwargs):
        """Set up connection to board"""
        super().__init__(**kwargs)
        KERNEL_LOGGER.debug(f"circuitpython_kernel version {__version__}")
        self.board = Board()
        self.upload_delay = 0.06

    def is_magic(self, line):
        """Returns true if line was handled"""
        if line.startswith("%softreset"):
            self.board.softreset()
        elif line.startswith("%upload_delay"):
            try:
                s = line.split(' ')
                self.upload_delay = float(s[1])
                KERNEL_LOGGER.debug(f"upload_delay set to {float(s[1])} s")
            except:
                pass
        else:
            return False
        return True

    def run_code(self, code, silent=True):
        """Run a code snippet.

        Parameters
        ----------
        code : str
            Code to be executed.
        silent : bool
            Controls output to notebook.

        Returns
        -------
        out
            Decoded bytearray output result from code run.
        err
            Decoded bytearray error from code run.
        """
        # make sure we are connected to the board
        self.board.connect()
        # Send code to board & fetch results (if any) after each line sent
        for line in code.splitlines(False):
            if not self.is_magic(line):
                self.board.write(line.encode('utf-8'))
                self.board.write(b'\r\n')
                # The Featherboard M4 cannot keep up with long code cells
                time.sleep(self.upload_delay)
        # Kick off evaluation ...
        self.board.write(b'\r\x04')   # Control-D
        # Set up a bytearray to hold the result from the code run
        retval = bytearray()
        # response starts with OK
        self.board.read_until(b'OK')  # swallow response head
        while True:
            result = self.board.read_all()
            if b'\x04' in result:
                # \x04 marks error if any, wait for rest of message
                while not result.endswith(b'\x04>'):
                    result.extend(self.board.read_all())
                    time.sleep(0.1)
                result = result[0:-2]
                retval.extend(result)
                out, err = result.split(b'\x04', 1)
                self.send_stdout(out.decode('utf-8', 'replace'), silent)
                self.send_stderr(err.decode('utf-8', 'replace'), silent)
                break
            # show result received so far ...
            retval.extend(result)
            self.send_stdout(result.decode('utf-8', 'replace'), silent)
            time.sleep(0.1)

        # send result back to caller (for _eval)
        out, err = retval.split(b'\x04', 1)  # split return value
        KERNEL_LOGGER.debug('Output: "%s"', out.decode('utf-8', 'replace'))
        KERNEL_LOGGER.debug('Error:  "%s"', err.decode('utf-8', 'replace'))
        return out.decode('utf-8', 'replace'), err.decode('utf-8', 'replace')

    def do_execute(self, code, silent, store_history=True,
                   user_expressions=None, allow_stdin=False):
        """Execute a user's code cell.

        Parameters
        ----------
        code : str
            Code, one or more lines, to be executed.
        silent : bool
            True, signals kernel to execute code quietly, and output is not
            displayed.
        store_history : bool
            Whether to record code in history and increase execution count. If
            silent is True, this is implicitly false.
        user_expressions : dict, optional
            Mapping of names to expressions to evaluate after code is run.
        allow_stdin : bool
            Whether the frontend can provide input on request (e.g. for
            Python’s raw_input()).

        Returns
        -------
        dict
            Execution results.

        """
        if not code.strip():
            return {'status': 'ok',
                'execution_count': self.execution_count,
                'payload': [],
                'user_expressions': {}}
        # evaluate code on board
        out = err = None
        try:
            self.run_code(code, silent)
        except (BoardError, SerialException) as e:
            KERNEL_LOGGER.debug(f'no connection {e}')
            self.send_stderr(f"No connection to CiruitPython VM: {e}")
        except KeyboardInterrupt:
            KERNEL_LOGGER.debug(f'keyboard interrupt')
            self.send_stderr("Keyboard Interrupt")
        return {
            'status': 'ok',
            'execution_count': self.execution_count,
            'payload': [],
            'user_expressions': {},
        }

    def send_stdout(self, msg, silent=False):
        """Send msg to stdout stream (display in notebook)."""
        if silent or not msg: return
        content = {'name': 'stdout', 'text': msg}
        self.send_response(self.iopub_socket, 'stream', content)

    def send_stderr(self, msg, silent=False):
        """Send msg to stderr stream (display in notebook)."""
        if silent or not msg: return
        content = {'name': 'stderr', 'text': msg}
        self.send_response(self.iopub_socket, 'stream', content)

    def _eval(self, expr):
        """Evaluate the expression.

        Use ast's literal_eval to prevent strange input from execution.

        """
        try:
            out, err = self.run_code('print({})'.format(expr))
        except (BoardError, SerialException) as e:
            out = ""
            err = f"Lost connection to CiruitPython VM: {e}"
        KERNEL_LOGGER.debug('Output: %s', out)
        KERNEL_LOGGER.debug('Error:  %s', err)
        return ast.literal_eval(out)

    def do_shutdown(self, restart):
        """Handle the kernel shutting down."""
        KERNEL_LOGGER.debug('Shutting down CircuitPython Board Connection..')
        self.board.write(b'\r\x02')
        KERNEL_LOGGER.debug('closing board connection..')
        self.board.close()

    def do_complete(self, code, cursor_pos):
        """Support code completion."""
        code = code[:cursor_pos]
        match = re.search(r'(\w+\.)*(\w+)?$', code)
        if match:
            prefix = match.group()
            if '.' in prefix:
                obj, prefix = prefix.rsplit('.')
                names = self._eval('dir({})'.format(obj))
            else:
                names = self._eval('dir()')
            matches = [n for n in names if n.startswith(prefix)]
            return {
                'matches': matches,
                'cursor_start': cursor_pos - len(prefix),
                'cursor_end': cursor_pos,
                'metadata': {},
                'status': 'ok',
            }

        else:
            return {
                'matches': [],
                'cursor_start': cursor_pos,
                'cursor_end': cursor_pos,
                'metadata': {},
                'status': 'ok',
            }
