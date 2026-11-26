"""Local server, migration and public collection administration commands."""
import argparse
import os
from dataclasses import replace

import uvicorn

from .app import create_app
from .core.config import Settings
from .database import initialize_database


def main(argv=None):
    parser = argparse.ArgumentParser(description='校园通知独立后端')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('init-db', help='升级数据库并导入中南大学公开目录')
    serve = commands.add_parser('serve', help='启动后端HTTP服务')
    serve.add_argument('--host', default='127.0.0.1')
    serve.add_argument('--port', type=int, default=8000)
    serve.add_argument('--dev', action='store_true', help='仅本机HTTP开发：允许非Secure Cookie')
    from .collection.cli import COMMANDS, add_commands, execute
    add_commands(commands)
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    if args.command in COMMANDS:
        status = execute(args, settings)
        return status
    if args.command == 'init-db':
        initialize_database(settings)
        print(f'数据库初始化完成：{settings.database_url}')
        return
    if args.dev:
        if args.host not in ('127.0.0.1', 'localhost', '::1'):
            parser.error('--dev仅允许绑定本机地址')
        origins = settings.allowed_origins
        if 'CAMPUS_ALLOWED_ORIGINS' not in os.environ:
            origins = (f'http://127.0.0.1:{args.port}', f'http://localhost:{args.port}', f'http://[::1]:{args.port}')
        settings = replace(settings, cookie_secure=False, allowed_origins=origins)
    uvicorn.run(create_app(settings), host=args.host, port=args.port, log_level='info')
