# frame-art-library

Catalog of ~1000 public-domain paintings for the "Art Library" tab of the Frame Art feature in the
Samsung TV remote app (`com.wac.samRemote`). The app reads `docs/catalog/v1.json` from GitHub Pages:

    https://waclabs.github.io/frame-art-library/catalog/v1.json

Only metadata lives here. Images are hotlinked from the museums:

| Source | Thumb | Full | Description |
|---|---|---|---|
| [National Gallery of Art](https://github.com/NationalGalleryOfArt/opendata) (CC0) | IIIF `!400,400` | IIIF `!3840,3840` | `assistivetext` (English) |
| [Cleveland Museum of Art Open Access](https://openaccess-api.clevelandart.org/) (CC0) | `web` (900px) | `print` (≤3400px) | `description` (English) |

To move images to another host later, rewrite the `thumb`/`full` URLs and republish. The catalog URL can also be changed through the
Remote Config key `frame_art_library_url`.

## Versioning

`publish` bumps `version` in `v1.json` whenever the items change and writes the same number to
`docs/catalog/v1.version.json`. The app keeps its cached catalog, polls the small version file, downloads
`v1.json` only when the version is higher, then shows a "new artworks" banner that swaps the data in when
tapped. No app release is needed.

Some networks block GitHub Pages, so the app falls back to the jsDelivr mirror of this repo
(`https://cdn.jsdelivr.net/gh/WacLabs/frame-art-library@main/docs/catalog/v1.json`). jsDelivr caches a
branch for up to 12 hours; the app ignores a mirror copy whose version is not higher than its own.

## Schema (`schemaVersion: 1`)

`items[]`: `id` (`nga-<objectid>` / `cma-<id>`, `[A-Za-z0-9_-]`), `source` (`nga` / `cma`), `title`, `artist`, `date`,
`medium`, `description` (nullable), `descriptionLang`, `theme`, `width`/`height` (pixel size of `full`),
`thumb`, `full`, `page`, `license`.

`theme` is one of `landscape`, `seascape`, `flowers`, `still_life`, `city`, `japan_asia`, `portrait`, `modern`,
`classic`. The app treats an unknown theme as `classic`.

A breaking schema change must ship as `v2.json` while `v1.json` stays live for older app versions.

## Rebuild

```sh
python3 tools/build_catalog.py candidates   # NGA CSVs + Cleveland API → build/candidates.json (~1100, auto-filtered)
python3 tools/contact_sheet.py              # build/review.html: click to reject, paste ids into curation/rejects.txt
python3 tools/build_catalog.py publish      # candidates − rejects → docs/catalog/v1.json (1000)
python3 tools/build_catalog.py validate     # every thumb/full URL answers 200
```

The scripts use the Python 3 standard library only. The NGA CSVs are cached in `.cache/nga/`, which is not
committed.
