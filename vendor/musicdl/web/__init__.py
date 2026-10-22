'''
Function:
    Web interface for musicdl
Author:
    Zhenchao Jin / Enhanced Modern WebUI
'''
import os
import sys
import webbrowser
from .server import run_server

def main():
    import argparse
    parser = argparse.ArgumentParser(description="musicdl Modern WebUI")
    parser.add_argument('--host', default='127.0.0.1', help="Host to bind (default: 127.0.0.1)")
    parser.add_argument('--port', type=int, default=5050, help="Port to bind (default: 5050)")
    parser.add_argument('--work-dir', default=None, help="Directory to save downloaded files (optional)")
    parser.add_argument('--no-browser', action='store_true', help="Do not automatically open browser")
    args = parser.parse_args()

    if args.work_dir:
        os.environ['MUSICDL_DOWNLOAD_DIR'] = os.path.abspath(args.work_dir)

    url = f"http://{args.host}:{args.port}"
    print(f"\n=======================================================")
    print(f"  musicdl Modern WebUI is starting...")
    print(f"  Access URL: {url}")
    if args.work_dir:
        print(f"  Work Dir:   {os.path.abspath(args.work_dir)}")
    print(f"=======================================================\n")

    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    run_server(host=args.host, port=args.port, work_dir=args.work_dir)

if __name__ == '__main__':
    main()
