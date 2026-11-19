/* ScaleSafe website forms (installed by tools/forms.py as /assets/site/forms-v1.js).
 * The walkthrough enquiry and privacy requests go to the ScaleSafe platform on Azure (partner-service public API).
 * Each form names its endpoint in data-endpoint; nginx points it at the right API host per domain.
 * Bots: a hidden "website" field that people never fill (honeypot), plus the API's own per-IP rate limit.
 * No third-party scripts, no cookies. */
(function () {
  "use strict";
  var REG = { "Investment Adviser": "IA", "Research Analyst": "RA", "PMS": "PMS", "AIF": "AIF" };
  var FALLBACK_CONTACT = "We could not send your enquiry just now. Please try again in a few minutes, or write to hello@scalesafe.co.in.";
  var FALLBACK_RIGHTS = "We could not send your request just now. Please try again in a few minutes, or email privacy@scalesafe.co.in.";

  function say(out, text, ok) {
    if (!out) return;
    out.setAttribute("role", ok ? "status" : "alert");
    out.textContent = text;
  }

  function fieldErrors(body) {
    if (!body || !body.errors || !body.errors.length) return "";
    return body.errors.map(function (e) {
      return typeof e === "string" ? e : [e.field, e.message].filter(Boolean).join(": ");
    }).join("; ");
  }

  function send(form, payload, out, success, fallback) {
    var trap = form.querySelector('input[name="website"]');
    if (trap && trap.value) { form.reset(); say(out, success({}), true); return; } // honeypot: pretend, send nothing
    var button = form.querySelector('button[type="submit"]');
    if (button) button.disabled = true;
    say(out, "Sending…", true);
    fetch(form.getAttribute("data-endpoint"), {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      credentials: "omit",
      body: JSON.stringify(payload)
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (b) { return { status: r.status, body: b }; });
    }).then(function (res) {
      if (res.status >= 200 && res.status < 300) { form.reset(); say(out, success(res.body || {}), true); }
      else if (res.status === 429) say(out, "Too many attempts from this connection. Please wait a minute and try again.", false);
      else if (res.status === 400 && fieldErrors(res.body)) say(out, "Please check: " + fieldErrors(res.body) + ".", false);
      else say(out, fallback, false);
    }).catch(function () {
      say(out, fallback, false);
    }).then(function () {
      if (button) button.disabled = false;
    });
  }

  function value(id) { var el = document.getElementById(id); return el ? el.value.trim() : ""; }
  function checked(id) { var el = document.getElementById(id); return !!(el && el.checked); }

  var contact = document.getElementById("contactForm");
  if (contact && contact.getAttribute("data-endpoint")) {
    contact.addEventListener("submit", function (e) {
      e.preventDefault();
      var reg = value("cReg");
      var message = value("cMessage");
      if (reg && !REG[reg]) message = ("Registration: " + reg + ". " + message).trim();
      send(contact, {
        name: value("cName"),
        email: value("cEmail"),
        entityType: REG[reg] || null,
        message: message || null,
        consentEssential: checked("essentialConsent"),
        consentMarketing: checked("marketingConsent")
      }, document.getElementById("formMsg"), function () {
        return "Thank you. Your enquiry has reached ScaleSafe and we will reply by email.";
      }, FALLBACK_CONTACT);
    });
  }

  var rights = document.getElementById("rightsForm");
  if (rights && rights.getAttribute("data-endpoint")) {
    rights.addEventListener("submit", function (e) {
      e.preventDefault();
      send(rights, {
        type: value("rType").toUpperCase(),
        name: value("rName"),
        email: value("rEmail"),
        details: value("rDetails"),
        confirmAccurate: true
      }, document.getElementById("rightsMsg"), function (b) {
        var text = "Request received.";
        if (b.reference) text += " Your reference is " + b.reference + ".";
        if (b.respondBy) text += " We will respond by " + new Date(b.respondBy).toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric" }) + ".";
        return text + " We may contact you to verify your identity before acting on it.";
      }, FALLBACK_RIGHTS);
    });
  }
})();
