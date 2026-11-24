"""UCI state machine against a real deterministic child process, without Qt."""
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from engine_protocol import UciSession
from models import Move, PositionSnapshot, STARTING_FEN

START = PositionSnapshot(STARTING_FEN)
E4 = PositionSnapshot('rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1')


class ProcessDriver:
    def __init__(self, log):
        self.lines = queue.Queue()
        self.results, self.completed, self.errors = [], [], []
        fixture = Path(__file__).with_name('fake_uci.py')
        self.process = subprocess.Popen([sys.executable, str(fixture), '--log', str(log)],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True)
        def read():
            for line in self.process.stdout:
                self.lines.put(line.rstrip('\r\n'))
        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()
        self.session = UciSession(send=self.write, result=self.results.append,
                                  ready=lambda: None, finished=self.completed.append,
                                  error=self.errors.append, state_changed=lambda *args: None)
        self.session.boot()
        self.wait(lambda: self.session.state == 'idle')

    def write(self, line):
        self.process.stdin.write(line + '\n')
        self.process.stdin.flush()

    def wait(self, condition):
        deadline = time.monotonic() + 5
        while not condition():
            if time.monotonic() > deadline:
                raise AssertionError('Test UCI process timed out')
            try:
                self.session.line(self.lines.get(timeout=.05))
            except queue.Empty:
                pass

    def close(self):
        self.session.close()
        try:
            self.write('quit')
        except (BrokenPipeError, OSError):
            pass
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.reader.join(timeout=1)
        self.process.stdin.close()
        self.process.stdout.close()
        self.process.stderr.close()


class EngineProcessTests(unittest.TestCase):
    def test_full_handshake_search_and_white_perspective(self):
        with tempfile.TemporaryDirectory() as directory:
            driver = ProcessDriver(Path(directory) / 'commands.txt')
            try:
                first = driver.session.analyse(START, START, movetime_ms=100)
                driver.wait(lambda: first in driver.completed)
                self.assertEqual(driver.results[-1].score_cp, 34)
                second = driver.session.analyse(E4, START, (Move.from_uci('e2e4'),), movetime_ms=100)
                driver.wait(lambda: second in driver.completed)
                self.assertEqual(driver.results[-1].score_cp, -34)
                self.assertEqual(driver.results[-1].best_move.uci, 'e7e5')
                self.assertFalse(driver.errors)
            finally:
                driver.close()

    def test_cancellation_discards_old_results_and_coalesces_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'commands.txt'
            driver = ProcessDriver(log)
            try:
                first = driver.session.analyse(START, START, movetime_ms=100)
                driver.wait(lambda: bool(driver.results))
                count_before = len(driver.results)
                discarded = driver.session.analyse(E4, START, (Move.from_uci('e2e4'),), movetime_ms=100)
                latest = driver.session.analyse(START, START, movetime_ms=100)
                driver.wait(lambda: latest in driver.completed)
                self.assertTrue(all(result.request_id == latest for result in driver.results[count_before:]))
                self.assertNotIn(discarded, driver.completed)
                self.assertNotIn(first, driver.completed)
                self.assertNotIn(999, [result.score_cp for result in driver.results])
            finally:
                driver.close()
            commands = log.read_text(encoding='utf-8').splitlines()
            self.assertEqual(sum(c.startswith('go ') for c in commands), 2)
            self.assertEqual(commands.count('stop'), 1)
