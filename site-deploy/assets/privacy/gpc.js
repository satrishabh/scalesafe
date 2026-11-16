/* Global Privacy Control: confirm that a GPC opt-out signal is honored (CCPA regs, from 1 Jan 2026).
   ScaleSafe never sells or shares personal information, so nothing else changes; this only tells the
   visitor their signal was received. No cookies, no storage, no network calls. */
(function () {
  var on = navigator.globalPrivacyControl === true;
  var inline = document.querySelectorAll("[data-gpc-inline]");
  for (var i = 0; i < inline.length; i++) {
    inline[i].textContent = on
      ? "sends a GPC signal. Opt-out request honored."
      : "does not send a GPC signal. We still do not sell or share your personal information.";
  }
  if (!on) return;
  var p = document.createElement("p");
  p.className = "gpc-status";
  p.setAttribute("role", "status");
  p.style.cssText = "margin:12px auto 0;max-width:1200px;padding:0 16px;font-size:13px;line-height:1.5";
  p.textContent = "Global Privacy Control signal detected: opt-out request honored. ScaleSafe does not sell or share personal information.";
  var host = document.querySelector("footer") || document.querySelector("main, article") || document.body;
  host.appendChild(p);
})();
