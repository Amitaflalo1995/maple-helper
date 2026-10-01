# Maple Helper website

The public download page for Maple Helper: a static site with no build step and no dependencies.
Hebrew is the default (`index.html`, right-to-left) and English lives in `en/index.html`.

```
site/
  index.html            Hebrew page (default, RTL)
  en/index.html         English page
  404.html              "page not found" (GitHub Pages serves it automatically)
  assets/css/site.css   all styles, light and dark (follows the system setting)
  assets/js/site.js     optional extras: OS detection, install tabs, latest version, scroll reveal
  assets/shots/         app screenshots, rendered from the real Qt widgets (light and dark)
  assets/img/           icons, mascot, social preview image (og.jpg)
  favicon.ico, site.webmanifest, robots.txt, sitemap.xml, .nojekyll
```

The page works without JavaScript. The script only adds conveniences: on a Mac it makes the macOS
button the primary one and opens the macOS install tab; on a phone it shows a "open this on your
computer" note; it asks the GitHub API for the latest version number and shows it if the call succeeds.

## Preview locally

```
cd site
python -m http.server 8000
```

Open http://localhost:8000/ (Hebrew) and http://localhost:8000/en/ (English).
Use a server rather than opening the file directly, so relative paths and the version lookup behave
as they will online.

## Deploy

All paths inside the pages are relative, so the folder works at a domain root or in a subfolder.

**GitHub Pages**

1. Repository **Settings → Pages**.
2. Either deploy from a branch and pick the folder (Pages only offers `/` or `/docs`, so you'd move
   or copy `site/` to `docs/`), or use a GitHub Actions workflow that uploads `site/` with
   `actions/upload-pages-artifact` (`path: site`) and `actions/deploy-pages`.
3. The site is then at `https://amitaflalo1995.github.io/maple-helper/`.

`.nojekyll` is already there, so GitHub serves the files as they are.

**Vercel**

1. Import the repository in Vercel.
2. Set **Root Directory** to `site`, **Framework Preset** to *Other*, and leave the build command
   and output directory empty.
3. Deploy. No `vercel.json` is needed.

## When the final URL is chosen

The placeholder address is `https://amitaflalo1995.github.io/maple-helper/`. Replace it everywhere
it appears (a search for `amitaflalo1995.github.io` finds every occurrence):

| File | What to change |
| --- | --- |
| `index.html` | `<link rel="canonical">`, the three `hreflang` links, `og:url`, `og:image`, `twitter:image`, and every URL inside the JSON-LD block (`@id`, `url`, `image`, `screenshot`) |
| `en/index.html` | the same list as `index.html` (its canonical and `og:url` end in `/en/`) |
| `sitemap.xml` | both `<loc>` entries and all `xhtml:link` alternates |
| `robots.txt` | the `Sitemap:` line |
| `404.html` | the two home links (`/maple-helper/` and `/maple-helper/en/`). On a custom domain at the root, change them to `/` and `/en/` |

Also update `<lastmod>` in `sitemap.xml` when the content changes.

The download buttons don't need changing: they point at
`https://github.com/Amitaflalo1995/maple-helper/releases/latest/download/…`, which always serves the
newest release, as long as each release keeps the asset names `MapleHelper-Setup.exe` and
`MapleHelper-macOS.dmg`.

## Editing the content

- Text lives directly in the two HTML files. Keep them in step: same sections, same facts.
- In the Hebrew page, wrap English words inside Hebrew sentences in `<bdi>…</bdi>` (for example
  `ל-<bdi>MapleStory Classic World</bdi>`), and key names in `<kbd>`. That keeps the word order and
  punctuation right in right-to-left text.
- The FAQ appears twice in each page: once as the visible `<details>` list and once in the
  `FAQPage` JSON-LD in `<head>`. If you change a question or an answer, change both.
- Colors are CSS variables at the top of `site.css`. Maple orange `#FF9533` / `#F07A12` is the only
  accent. Orange text uses the darker `--accent-text` so it stays readable (WCAG AA).

## Regenerating the screenshots

The screenshots are real renders of the app's Qt widgets (`Overlay`, `WishlistDialog`,
`SettingsDialog`) made with PySide6 and `widget.grab()`, in Hebrew, light and dark. They were made
with a throwaway `APPDATA` folder so no real user data is involved, then cropped to the window's
rounded edge (the app draws a transparent shadow margin around it) and saved as WebP. Re-render them
when the app's look changes, keeping the same file names and sizes, or update the `width`/`height`
attributes in the HTML.

## Credits

Game data and images courtesy of NiaMeowDB (meowdb.com). Font: Rubik (Google Fonts, SIL Open Font
License). Maple Helper is unofficial and not affiliated with Nexon; no Nexon or MapleStory logos
are used, only the game's name as text.
