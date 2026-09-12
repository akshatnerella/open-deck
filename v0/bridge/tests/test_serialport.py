import os
import pty
import unittest

from opendeck.serialport import SerialPort


class SerialPortTest(unittest.TestCase):
    """Exercised against a real pty, so termios configuration is actually run."""

    def setUp(self):
        self.master, slave = pty.openpty()
        self.port = SerialPort(os.ttyname(slave))
        self.port.open()
        os.close(slave)
        self.addCleanup(self.port.close)
        self.addCleanup(self.close_master)

    def close_master(self) -> None:
        # Some tests close it themselves to simulate an unplug.
        try:
            os.close(self.master)
        except OSError:
            pass

    def feed(self, data: bytes) -> None:
        os.write(self.master, data)

    def test_reads_one_line_without_its_terminator(self):
        self.feed(b"HB 1234\n")
        self.assertEqual(self.port.readline(), b"HB 1234")

    def test_strips_carriage_return(self):
        self.feed(b"EVT KEY_TERM DOWN\r\n")
        self.assertEqual(self.port.readline(), b"EVT KEY_TERM DOWN")

    def test_splits_a_batch_arriving_in_one_read(self):
        self.feed(b"HB 1\nHB 2\nHB 3\n")
        self.assertEqual([self.port.readline() for _ in range(3)],
                         [b"HB 1", b"HB 2", b"HB 3"])

    def test_reassembles_a_line_split_across_reads(self):
        # USB CDC delivers whatever fits in a packet, so a line arriving in
        # pieces is normal rather than exceptional.
        self.feed(b"EVT ENC")
        self.assertEqual(self.port.readline(timeout=0.05), b"")
        self.feed(b"ODER +1\n")
        self.assertEqual(self.port.readline(), b"EVT ENCODER +1")

    def test_returns_empty_on_timeout_rather_than_blocking(self):
        self.assertEqual(self.port.readline(timeout=0.05), b"")

    def test_write_line_appends_a_newline(self):
        self.port.write_line("FACE busy")
        self.assertEqual(os.read(self.master, 64), b"FACE busy\n")

    def test_raises_once_closed(self):
        self.port.close()
        self.assertFalse(self.port.is_open)
        with self.assertRaises(OSError):
            self.port.readline()
        with self.assertRaises(OSError):
            self.port.write_line("FACE calm")

    def test_unplugging_raises_so_the_transport_can_reconnect(self):
        os.close(self.master)
        with self.assertRaises(OSError):
            for _ in range(10):
                self.port.readline(timeout=0.05)


class ContextManagerTest(unittest.TestCase):
    def test_closes_on_exit(self):
        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        with SerialPort(os.ttyname(slave)) as port:
            os.close(slave)
            self.assertTrue(port.is_open)
        self.assertFalse(port.is_open)


if __name__ == "__main__":
    unittest.main()
