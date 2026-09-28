# Sakina — public prayer times

The daily prayer list and the countdown from the devices' website, one site per city,
served by Cloudflare Pages at `https://sakina-<city>.pages.dev` — and, at `/d/<name>/`, the
app a device hands out, whose settings icon opens that device on its own wifi.

```
<city>/city.ini           Arabic name, daylight_saving (true/false), IANA timezone
<city>/prayer-times.csv   symlink into the devices' config/prayers-config/
<city>/public/            generated — never edit by hand
icons/                    the Sakina icon, shared by every city; source-thkr-allah.jpeg is
                          the original, icon-*.png are cut from it full-bleed
build.py                  builds every city, this year and next, copies every city's
                          years into every site (data/<city>/) so the pages can switch
                          between them, and writes the devices' web_ui/public_sites.json
```

`public/` is rebuilt and committed by `.github/workflows/sakina-static-website.yml` on any
push that changes the pages or anything the build reads, and every 1 December.

Adding a city and setting up its Cloudflare project: `ADMIN_MANUAL.md` §18,
"The public city sites".
