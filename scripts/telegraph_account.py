"""One-off helper: create a Telegraph account and print its access token.

Usage:
    python scripts/telegraph_account.py "Your Name" [author_url]

Put the printed token in .env as TELEGRAPH_ACCESS_TOKEN. Run this once, not per post.
Docs: https://telegra.ph/api#createAccount
"""

import sys

import httpx


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    author_name = sys.argv[1]
    params = {"short_name": author_name[:32], "author_name": author_name[:128]}
    if len(sys.argv) > 2:
        params["author_url"] = sys.argv[2]

    response = httpx.post("https://api.telegra.ph/createAccount", data=params, timeout=10)
    data = response.json()
    if not data.get("ok"):
        print(f"Telegraph error: {data.get('error')}", file=sys.stderr)
        return 1
    print(f"TELEGRAPH_ACCESS_TOKEN={data['result']['access_token']}")
    print(f"TELEGRAPH_AUTHOR_NAME={author_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
