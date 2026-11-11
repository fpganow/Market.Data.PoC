# docs/site -- pages for fpganow.com

WordPress block-editor HTML for the pages on fpganow.com that describe this project. Keep the
numbers here in step with `optimize.txt`, `vivado_rtl/README.md` and the dated log in `CLAUDE.md`;
this directory is the source, the site is a copy.

| File | Page slug on fpganow.com |
|------|--------------------------|
| `benchmarks.html` | `benchmarks` (latest measured numbers, both parsers, how they are taken) |
| `models.html` | `models` (the three implementations, where each lives, how to build and switch) |

Publishing (needs a WordPress Application Password: Users -> Profile -> Application Passwords):

```bash
export WP_USER=<login> WP_APP_PASSWORD='xxxx xxxx xxxx xxxx xxxx xxxx'
python3 scripts/site_publish.py docs/site/benchmarks.html --slug benchmarks --title Benchmarks            # dry run: shows what would change
python3 scripts/site_publish.py docs/site/benchmarks.html --slug benchmarks --title Benchmarks --apply    # creates the page (draft) or updates it
python3 scripts/site_publish.py docs/site/models.html --slug models --title Models --apply --status publish
```

Or paste a file's contents into the block editor's Code editor view (Options -> Code editor).
