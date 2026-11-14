import base64
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from cryptography.fernet import Fernet


class InitConfigTests(unittest.TestCase):
    def test_generates_valid_private_values_and_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'init_env.py'
            shutil.copy2(Path(__file__).resolve().parents[1] / 'init_env.py', script)
            first = subprocess.run([sys.executable, str(script)], check=True, capture_output=True, text=True)
            target = Path(directory) / '.env'
            original = target.read_bytes()
            values = dict(line.split('=', 1) for line in original.decode().splitlines() if line and not line.startswith('#'))
            self.assertEqual(len(base64.urlsafe_b64decode(values['PLATFORM_SECRET'])), 32)
            cipher = Fernet(values['PLATFORM_SECRET'].encode())
            self.assertEqual(cipher.decrypt(cipher.encrypt(b'test')), b'test')
            self.assertGreaterEqual(len(values['AUTH_CODE']), 40)
            self.assertNotIn(values['AUTH_CODE'], first.stdout)
            self.assertNotIn(values['PLATFORM_SECRET'], first.stdout)
            subprocess.run([sys.executable, str(script)], check=True, capture_output=True)
            self.assertEqual(target.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
