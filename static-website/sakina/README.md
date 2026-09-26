# Sakina — public prayer times

The daily prayer list from the devices' website, one site per city, served by Cloudflare
Pages at `https://sakina-<city>.pages.dev`.

```
<city>/city.ini           Arabic name, daylight_saving (true/false), IANA timezone
<city>/prayer-times.csv   symlink into the devices' config/prayers-config/
<city>/public/            generated — never edit by hand
build.py                  builds every city, this year and next
```

`public/` is rebuilt and committed by `.github/workflows/sakina-static-website.yml` on any
push that changes the pages or anything the build reads, and every 1 December.

Adding a city and setting up its Cloudflare project: `ADMIN_MANUAL.md` §18,
"The public city sites".
