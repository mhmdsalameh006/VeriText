import argparse
import getpass
import re
import uuid
from .db import init_db, connect, now
from .security import ph


def main():
    parser = argparse.ArgumentParser(description='VeriText administrator tools')
    sub = parser.add_subparsers(dest='command',required=True)
    create = sub.add_parser('create-admin')
    create.add_argument('--email',required=True)
    create.add_argument('--name',default='Platform Administrator')
    args = parser.parse_args()
    init_db()
    if args.command == 'create-admin':
        email = args.email.strip().lower()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):
            parser.error('Email address is invalid')
        password = getpass.getpass('Choose administrator password (12+ characters): ')
        confirm = getpass.getpass('Confirm password: ')
        if len(password) < 12 or password != confirm:
            parser.error('Passwords must match and be at least 12 characters long')
        with connect() as db:
            if db.execute('SELECT 1 FROM users WHERE email=?',(email,)).fetchone():
                parser.error('Account already exists')
            db.execute('INSERT INTO users(id,email,name,password_hash,role,created_at) VALUES(?,?,?,?,?,?)',
                       (str(uuid.uuid4()),email,args.name,ph.hash(password),'admin',now()))
        print('Administrator created:',email)


if __name__=='__main__':
    main()
