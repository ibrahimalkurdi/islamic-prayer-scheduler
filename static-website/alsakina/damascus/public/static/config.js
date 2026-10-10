/* Written by tools/build_static_site.py. This copy is served from a static
   host, so it reads a baked year rather than a device's API, and offers
   nothing that would act on a Raspberry Pi. */
window.DATA = "/data/{year}.json";
window.DEVICE = false;
window.PLACE = "دمشق";
window.VERSION = "1.6.3";
window.TIMEZONE = "Asia/Damascus";
window.CITY = "damascus";
window.CITIES = [
    {
        "id": "aachen",
        "place": "آخن",
        "timezone": "Europe/Berlin",
        "data": "/data/aachen/{year}.json"
    },
    {
        "id": "berlin",
        "place": "برلين",
        "timezone": "Europe/Berlin",
        "data": "/data/berlin/{year}.json"
    },
    {
        "id": "damascus",
        "place": "دمشق",
        "timezone": "Asia/Damascus",
        "data": "/data/{year}.json"
    },
    {
        "id": "lagos",
        "place": "لاغوس",
        "timezone": "Africa/Lagos",
        "data": "/data/lagos/{year}.json"
    }
];
