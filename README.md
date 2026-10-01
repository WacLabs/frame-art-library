# frame-art-library

Catalog of every open-access painting from the two sources below, plus Cleveland's Japanese prints (~5,600;
long side ≥2000px, auto-filtered and hand-reviewed), for the "Art Library" tab of the Frame Art feature in
the Samsung TV remote app (`com.wac.samRemote`). The app reads `docs/catalog/v2/catalog.json` from GitHub Pages:

    https://waclabs.github.io/frame-art-library/catalog/v2/catalog.json

`docs/catalog/v1.json` is frozen at the earlier 1000-item catalog for app versions without search; `publish`
no longer writes it.

Only metadata lives here. Images come from the museums, routed through the [wsrv.nl](https://wsrv.nl) image
CDN (`IMAGE_PROXY` in `tools/build_catalog.py`), which resizes them and caches them on Cloudflare for a year:

| Source | Thumb (proxied to ≤600px) | Full (proxied to ≤3840px) | Description |
|---|---|---|---|
| [National Gallery of Art](https://github.com/NationalGalleryOfArt/opendata) (CC0) | IIIF `!600,600` | IIIF `!3840,3840` | `assistivetext` (English) |
| [Cleveland Museum of Art Open Access](https://openaccess-api.clevelandart.org/) (CC0) | `web` (900px) | `print` (≤3400px) | `description` (English) |

Why the proxy: `api.nga.gov` was measured at 5–20 KB/s from Vietnam (a 3 MB painting took minutes) and
Cleveland's smallest rendition is 300–900 KB, too heavy for a grid. If wsrv.nl ever becomes a problem, set
`IMAGE_PROXY = ""` and publish again; the app picks the new URLs up through the version check.

To move images to another host later, rewrite the `thumb`/`full` URLs and republish. The catalog URL can also be changed through the
Remote Config key `frame_art_library_url`.

`catalog.json` is ~390 KB on the wire (GitHub Pages and both mirrors gzip it; the app's HTTP clients
decompress transparently). Descriptions, which were 2/3 of the bytes, live in 64 shards `v2/desc/NN.json`
(~12 KB gzip each) that the app fetches only when a detail sheet opens.

`validate` checks the museum URLs behind the proxy and only a handful of proxied ones, slowly: wsrv.nl bans an
IP (Cloudflare error 1006, HTTP 403) that sends it many parallel requests.

## Versioning

`publish` bumps `version` in `v2/catalog.json` whenever the items or descriptions change and writes the same
number to `v2/catalog.version.json` and every desc shard. The app keeps its cached catalog, polls the small version file, downloads
`catalog.json` only when the version is higher, then shows a "new artworks" banner that swaps the data in when
tapped. No app release is needed.

Some networks block GitHub Pages, so the app falls back to two mirrors of this repo:
`https://raw.githubusercontent.com/WacLabs/frame-art-library/main/docs/catalog/v2/catalog.json` (5 minute cache) and
`https://cdn.jsdelivr.net/gh/WacLabs/frame-art-library@main/docs/catalog/v2/catalog.json`. jsDelivr caches a
branch for up to 12 hours; the app ignores a mirror copy whose version is not higher than its own.

## Schema (`schemaVersion: 2`)

`items[]`: `id` (`nga-<objectid>` / `cma-<id>`, `[A-Za-z0-9_-]`), `source` (`nga` / `cma`), `title`, `artist`, `date`,
`medium`, `desc` (desc shard number, absent = no description), `theme`, `width`/`height` (pixel size of `full`),
`thumb`, `full`, `page`, `license`.

`theme` is one of `landscape`, `seascape`, `flowers`, `still_life`, `city`, `japan_asia`, `portrait`, `modern`,
`classic`. The app treats an unknown theme as `classic`.

`desc/NN.json`: `{"version", "items": {"<id>": {"text", "lang"}}}`.

v1 (`schemaVersion: 1`) had `description` and `descriptionLang` inline instead of `desc`. A breaking change
must ship as a new `vN/` directory while the older ones stay live for older app versions.

## Rebuild

```sh
python3 tools/build_catalog.py candidates   # NGA CSVs + Cleveland API → build/candidates.json (every painting, auto-filtered)
python3 tools/contact_sheet.py              # build/review.html: click to reject, paste ids into curation/rejects.txt
python3 tools/build_catalog.py publish      # candidates − rejects → docs/catalog/v2/ (all kept items)
python3 tools/build_catalog.py validate     # every thumb source + a sample of full/proxied URLs answer 200
```

The scripts use the Python 3 standard library only. The NGA CSVs are cached in `.cache/nga/`, which is not
committed.
