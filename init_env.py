"""Generate independent secrets, without dependencies or printing their values."""
import base64
import os
from pathlib import Path
import secrets


def main():
    target = Path(__file__).resolve().parent / '.env'
    key = base64.urlsafe_b64encode(os.urandom(32)).decode('ascii')
    content = (
        '# Private local configuration. Never share or commit this file.\n'
        f'PLATFORM_SECRET={key}\n'
        f'AUTH_CODE={secrets.token_urlsafe(32)}\n'
        'WEWE_PORT=8088\n'
        'SERVER_ORIGIN_URL=http://localhost:8088\n'
        'WEWE_NETWORK=\n'
    )
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print('.env already exists; preserved without changes.')
        return
    with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write(content)
    print('Created private .env. Read AUTH_CODE locally for the dashboard password.')


if __name__ == '__main__':
    main()
