/* Phone menu (<details class="mobile-menu">): close after choosing a link, and on Escape. Added by tools/sync_from_live.py. */
document.addEventListener('click', function (e) {
  var a = e.target.closest && e.target.closest('.mobile-menu a');
  if (a) a.closest('details').open = false;
});
document.addEventListener('keydown', function (e) {
  if (e.key !== 'Escape') return;
  var d = document.querySelector('.mobile-menu[open]');
  if (d) { d.open = false; d.querySelector('summary').focus(); }
});
