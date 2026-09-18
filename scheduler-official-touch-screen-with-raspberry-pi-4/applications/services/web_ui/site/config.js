/* The only file that differs between the copy served from the device and a copy uploaded
   to a static host. tools/build_static_site.py rewrites it.

   DEVICE also decides whether the pages offer anything that acts on the Raspberry Pi -
   the settings link and the mute button. Neither has any meaning away from the device. */
window.DATA = "/api/day";
window.DEVICE = true;
