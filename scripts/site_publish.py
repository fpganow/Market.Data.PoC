#!/usr/bin/env python3
"""Push a WordPress block-HTML file to a page on fpganow.com by slug.

Uses the WordPress REST API with an Application Password (Users -> Profile ->
Application Passwords in wp-admin). Credentials come from the environment:
WP_USER and WP_APP_PASSWORD. Without --apply nothing is written.

    python3 scripts/site_publish.py docs/site/benchmarks.html --slug benchmarks --title Benchmarks
    python3 scripts/site_publish.py docs/site/benchmarks.html --slug benchmarks --title Benchmarks --apply
"""
import argparse, base64, json, os, sys, urllib.error, urllib.parse, urllib.request

DEFAULT_SITE = "https://fpganow.com/index.php/wp-json/wp/v2"


def call(site, path, auth, method="GET", body=None):
    url = site + path
    data = None
    headers = {"Accept": "application/json", "User-Agent": "site_publish"}
    if auth:
        headers["Authorization"] = "Basic " + base64.b64encode(auth.encode()).decode()
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        msg = e.read().decode(errors="replace")
        sys.exit(f"{method} {url} -> HTTP {e.code}: {msg[:400]}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("html", help="file with the page content (WordPress block HTML)")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--title", help="page title (required when the page does not exist yet)")
    ap.add_argument("--status", default=None, help="draft | publish (default: keep; draft for a new page)")
    ap.add_argument("--site", default=DEFAULT_SITE)
    ap.add_argument("--apply", action="store_true", help="write to the site (default: dry run)")
    a = ap.parse_args()

    user, pw = os.environ.get("WP_USER"), os.environ.get("WP_APP_PASSWORD")
    auth = f"{user}:{pw}" if (user and pw) else None
    if a.apply and not auth:
        sys.exit("set WP_USER and WP_APP_PASSWORD")

    content = open(a.html, encoding="utf-8").read()
    # status=any (drafts too) is only allowed when authenticated
    q = f"/pages?slug={urllib.parse.quote(a.slug)}&_fields=id,link,status,title,modified" + ("&status=any" if auth else "")
    found = call(a.site, q, auth)
    page = found[0] if found else None

    if page:
        print(f"page {page['id']} '{page['title']['rendered']}' {page['status']} {page['link']} (modified {page['modified']})")
        body = {"content": content}
        if a.title:
            body["title"] = a.title
        if a.status:
            body["status"] = a.status
        if not a.apply:
            print(f"dry run: would update page {page['id']} with {len(content)} chars of content")
            return
        r = call(a.site, f"/pages/{page['id']}", auth, "POST", body)
        print(f"updated: {r['link']} ({r['status']})")
    else:
        if not a.title:
            sys.exit(f"no page with slug '{a.slug}'; pass --title to create it")
        body = {"slug": a.slug, "title": a.title, "content": content, "status": a.status or "draft"}
        if not a.apply:
            print(f"dry run: would create page '{a.title}' (slug {a.slug}, {body['status']}) with {len(content)} chars")
            return
        r = call(a.site, "/pages", auth, "POST", body)
        print(f"created: {r['link']} ({r['status']})")


if __name__ == "__main__":
    main()
