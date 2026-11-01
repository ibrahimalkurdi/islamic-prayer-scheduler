/* The only file that differs between the copy served from the device and a copy uploaded
   to a static host. tools/build_static_site.py rewrites it.

   DEVICE also decides whether the pages offer anything that acts on the Raspberry Pi.
   The mute button is only ever here; the settings icon is here and in the app a device
   hands out from the public site (Site.ownerHost). */
window.DATA = "/api/day";
window.DEVICE = true;
