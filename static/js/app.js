// Small progressive enhancements. Every page still works without JavaScript.
(function () {
  "use strict";

  // Theme: follows the operating system until the user picks one; the choice is kept on this device.
  var themeButton = document.querySelector("[data-theme-toggle]");
  if (themeButton) {
    var root = document.documentElement;
    var systemDark = window.matchMedia("(prefers-color-scheme: dark)");
    var isDark = function () {
      var chosen = root.getAttribute("data-theme");
      return chosen ? chosen === "dark" : systemDark.matches;
    };
    var label = function () {
      var text = isDark() ? "Switch to light mode" : "Switch to dark mode";
      themeButton.setAttribute("aria-label", text);
      themeButton.title = text;
    };
    themeButton.addEventListener("click", function () {
      var next = isDark() ? "light" : "dark";
      root.setAttribute("data-theme", next);
      try { localStorage.setItem("theme", next); } catch (e) { /* private mode: the choice lasts for this page only */ }
      label();
    });
    if (systemDark.addEventListener) systemDark.addEventListener("change", label);
    label();
  }

  // Ctrl/Cmd+K focuses the client search in the top bar.
  var globalSearch = document.querySelector("[data-global-search]");
  var hint = document.querySelector("[data-shortcut-hint]");
  if (hint && !/Mac|iPhone|iPad/.test(navigator.platform)) hint.textContent = "Ctrl K";
  document.addEventListener("keydown", function (e) {
    if (globalSearch && (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      var box = globalSearch.offsetParent ? globalSearch : document.getElementById("q") || globalSearch;
      box.focus();
      box.select();
    }
  });

  // Show or hide the password on the login form.
  document.querySelectorAll("[data-pw-toggle]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var input = document.getElementById(btn.getAttribute("aria-controls"));
      var show = input.type === "password";
      input.type = show ? "text" : "password";
      btn.textContent = show ? "Hide" : "Show";
      btn.setAttribute("aria-pressed", show ? "true" : "false");
    });
  });

  // Filters apply as soon as a dropdown changes.
  document.querySelectorAll("[data-autosubmit]").forEach(function (el) {
    el.addEventListener("change", function () { el.form.submit(); });
  });

  // Confirmation prompts: forms and buttons with data-confirm ask before they act.
  document.addEventListener("submit", function (e) {
    var msg = e.target.getAttribute && e.target.getAttribute("data-confirm");
    if (msg && !window.confirm(msg)) e.preventDefault();
  });
  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest("button[data-confirm]");
    if (btn && !window.confirm(btn.getAttribute("data-confirm"))) e.preventDefault();
  });

  // Copy buttons (for example a client's email address).
  document.querySelectorAll("[data-copy]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      if (!navigator.clipboard) return;
      navigator.clipboard.writeText(btn.getAttribute("data-copy")).then(function () {
        var original = Array.from(btn.childNodes, function (n) { return n.cloneNode(true); });
        btn.textContent = "Copied";
        setTimeout(function () { btn.replaceChildren.apply(btn, original); }, 1200);
      });
    });
  });

  // Missing email/phone: edit inline and save without leaving the list.
  var quickForm = document.getElementById("quick-form");
  if (quickForm) {
    document.querySelectorAll("[data-quick-edit]").forEach(function (link) {
      link.addEventListener("click", function (e) {
        e.preventDefault();
        var field = link.getAttribute("data-field");
        var box = document.createElement("span");
        box.className = "quick-edit";
        var input = document.createElement("input");
        input.type = field === "email" ? "email" : "tel";
        input.placeholder = field === "email" ? "name@company.fi" : "040 123 4567";
        input.setAttribute("aria-label", (field === "email" ? "Email for " : "Phone for ") + link.getAttribute("data-client-name"));
        var save = document.createElement("button");
        save.type = "button";
        save.className = "btn btn-sm btn-primary";
        save.textContent = "Save";
        var cancel = document.createElement("button");
        cancel.type = "button";
        cancel.className = "btn btn-sm btn-ghost";
        cancel.textContent = "Cancel";
        box.append(input, save, cancel);

        var submit = function () {
          if (!input.value.trim()) { input.focus(); return; }
          quickForm.action = link.getAttribute("data-action");
          quickForm.elements.field.value = field;
          quickForm.elements.value.value = input.value;
          save.disabled = true;
          quickForm.submit();
        };
        var close = function () { box.replaceWith(link); link.focus(); };
        save.addEventListener("click", submit);
        cancel.addEventListener("click", close);
        input.addEventListener("keydown", function (ev) {
          // The row sits inside the bulk-action form: Enter must save this field, not submit that form.
          if (ev.key === "Enter") { ev.preventDefault(); submit(); }
          if (ev.key === "Escape") { ev.preventDefault(); close(); }
        });
        link.replaceWith(box);
        input.focus();
      });
    });
  }

  // Client list: select all, row highlight, selection counter, bulk action bar.
  var bulkForm = document.getElementById("bulk-form");
  if (bulkForm) {
    var rows = bulkForm.querySelectorAll("[data-row]");
    var all = bulkForm.querySelector("[data-select-all]");
    var bar = bulkForm.querySelector("[data-bulk-bar]");
    var count = bulkForm.querySelector("[data-selected-count]");
    var update = function () {
      var n = 0;
      rows.forEach(function (r) {
        r.closest("tr").classList.toggle("is-selected", r.checked);
        if (r.checked) n++;
      });
      count.textContent = n;
      bar.hidden = n === 0;
      all.checked = n > 0 && n === rows.length;
      all.indeterminate = n > 0 && n < rows.length;
    };
    all.addEventListener("change", function () {
      rows.forEach(function (r) { r.checked = all.checked; });
      update();
    });
    rows.forEach(function (r) { r.addEventListener("change", update); });
    update();
  }

  // SMS length: same rules as the server (messaging/sms.py), passed in as JSON.
  var rulesEl = document.getElementById("sms-rules");
  var rules = rulesEl ? JSON.parse(rulesEl.textContent) : null;
  var smsLength = function (text) {
    var gsm = true, count = 0;
    for (var ch of text) {
      if (rules.basic.indexOf(ch) !== -1) count += 1;
      else if (rules.extended.indexOf(ch) !== -1) count += 2;
      else { gsm = false; break; }
    }
    if (!gsm) count = text.length; // UTF-16 code units, as the operator counts them
    var single = gsm ? 160 : 70, multi = gsm ? 153 : 67;
    var parts = count === 0 ? 0 : (count <= single ? 1 : Math.ceil(count / multi));
    return { count: count, parts: parts, gsm: gsm };
  };
  var describeSms = function (info) {
    if (!info.count) return "";
    return info.count + " characters · " + info.parts + " SMS" +
      (info.gsm ? "" : " (special characters use more space)") +
      (info.parts > rules.max ? " · too long, max " + rules.max + " SMS" : "");
  };

  // Template form: SMS templates have no subject; show the SMS length while typing.
  var templateForm = document.querySelector("[data-template-form]");
  if (templateForm && rules) {
    var updateTemplateForm = function () {
      var checked = templateForm.querySelector("input[name=channel]:checked");
      var isSms = checked && checked.value === "sms";
      templateForm.querySelectorAll("[data-email-only]").forEach(function (el) { el.hidden = isSms; });
      templateForm.querySelectorAll("[data-sms-only]").forEach(function (el) { el.hidden = !isSms; });
      templateForm.querySelectorAll("[data-raw-counter]").forEach(function (counter) {
        var info = smsLength(templateForm.querySelector("[name=" + counter.getAttribute("data-raw-counter") + "]").value);
        counter.textContent = describeSms(info) + (info.count ? " (names make it longer)" : "");
        counter.classList.toggle("is-over", info.parts > rules.max);
      });
    };
    templateForm.addEventListener("input", updateTemplateForm);
    templateForm.addEventListener("change", updateTemplateForm);
    updateTemplateForm();
  }

  // Compose: template fill, insert personalisation fields, live preview.
  var compose = document.querySelector("[data-compose]");
  if (compose) {
    var templates = JSON.parse(document.getElementById("templates-data").textContent);
    var samples = JSON.parse(document.getElementById("samples-data").textContent);
    var field = function (name) { return compose.querySelector("[name=" + name + "]"); };
    var lastText = field("body_fi") || field("body_en");

    var formatDue = function () {
      var iso = (field("due_date").value || "").split("-"); // yyyy-mm-dd from the date picker
      return iso.length === 3 ? Number(iso[2]) + "." + Number(iso[1]) + "." + iso[0] : "{due_date}";
    };
    var fill = function (text, ctx) {
      return (text || "").replace(/\{([a-z_]+)\}/g, function (m, key) {
        return Object.prototype.hasOwnProperty.call(ctx, key) ? ctx[key] : m;
      });
    };
    var render = function () {
      ["fi", "en"].forEach(function (lang) {
        var box = compose.querySelector('[data-preview="' + lang + '"]');
        var sample = samples[lang];
        var ctx = Object.assign({}, sample || {}, { due_date: formatDue() });
        var body = field("body_" + lang) ? fill(field("body_" + lang).value, ctx) : "";
        if (box && sample) {
          box.querySelector("[data-preview-name]").textContent = sample.name;
          var subjectEl = box.querySelector("[data-preview-subject]");
          if (subjectEl) subjectEl.textContent = fill(field("subject_" + lang).value, ctx) || "(no subject)";
          box.querySelector("[data-preview-body]").textContent = body;
        }
        var counter = compose.querySelector('[data-sms-counter="' + lang + '"]');
        if (counter && rules) {
          var info = smsLength(body);
          var over = info.parts > rules.max;
          counter.classList.toggle("is-over", over);
          counter.textContent = describeSms(info) + (info.count && sample ? " · counted for " + sample.name : "");
        }
      });
    };

    // Switching Email/SMS reloads the form for that channel and keeps the text written so far.
    compose.querySelectorAll("input[name=channel]").forEach(function (radio) {
      radio.addEventListener("change", function () { compose.submit(); });
    });

    compose.querySelectorAll("input[type=text], textarea").forEach(function (el) {
      el.addEventListener("focus", function () { lastText = el; });
    });
    compose.querySelectorAll("[data-insert]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        if (!lastText) return;
        var token = btn.getAttribute("data-insert");
        var start = lastText.selectionStart || 0;
        var end = lastText.selectionEnd || 0;
        lastText.value = lastText.value.slice(0, start) + token + lastText.value.slice(end);
        lastText.focus();
        lastText.setSelectionRange(start + token.length, start + token.length);
        render();
      });
    });

    field("template").addEventListener("change", function (e) {
      var t = templates[e.target.value];
      if (!t) return;
      var hasText = ["subject_fi", "body_fi", "subject_en", "body_en"].some(function (k) { return field(k) && field(k).value.trim(); });
      if (hasText && !window.confirm("Replace the text you have written with this template?")) return;
      Object.keys(t).forEach(function (k) { if (field(k)) field(k).value = t[k]; });
      render();
    });
    compose.addEventListener("input", render);
    compose.addEventListener("change", render);
    render();
  }

  // Donut: hovering or focusing a segment or its legend row highlights it and shows its numbers in the centre.
  document.querySelectorAll("[data-donut]").forEach(function (block) {
    var value = block.querySelector("[data-center-value]");
    var label = block.querySelector("[data-center-label]");
    var legend = {};
    block.querySelectorAll(".legend [data-seg]").forEach(function (a) { legend[a.getAttribute("data-seg")] = a; });
    var show = function (seg) {
      var row = legend[seg];
      if (!row) return;
      block.classList.add("is-focus");
      block.querySelectorAll("[data-seg]").forEach(function (el) { el.classList.toggle("is-on", el.getAttribute("data-seg") === seg); });
      value.textContent = row.getAttribute("data-count");
      label.textContent = row.getAttribute("data-label");
    };
    var reset = function () {
      block.classList.remove("is-focus");
      block.querySelectorAll(".is-on").forEach(function (el) { el.classList.remove("is-on"); });
      value.textContent = value.getAttribute("data-default");
      label.textContent = label.getAttribute("data-default");
    };
    block.querySelectorAll("[data-seg]").forEach(function (el) {
      var seg = el.getAttribute("data-seg");
      el.addEventListener("mouseenter", function () { show(seg); });
      el.addEventListener("focus", function () { show(seg); });
      el.addEventListener("mouseleave", reset);
      el.addEventListener("blur", reset);
      if (el.tagName.toLowerCase() === "circle") {
        el.addEventListener("click", function () { legend[seg].click(); });
      }
    });
  });

  // Team member form: show/hide and generate a password.
  var toggle = document.querySelector("[data-password-toggle]");
  if (toggle) {
    var pw = toggle.parentNode.querySelector("input");
    var setVisible = function (visible) {
      pw.type = visible ? "text" : "password";
      toggle.textContent = visible ? "Hide" : "Show";
      toggle.setAttribute("aria-pressed", String(visible));
    };
    toggle.addEventListener("click", function () { setVisible(pw.type === "password"); });
    document.querySelector("[data-password-generate]").addEventListener("click", function () {
      var chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#%&*?";
      var bytes = new Uint32Array(16);
      window.crypto.getRandomValues(bytes);
      pw.value = Array.from(bytes, function (b) { return chars[b % chars.length]; }).join("");
      setVisible(true);
      pw.focus();
      pw.select();
    });
  }

  // Confirm page: stop a double click from sending twice (the server also guards this).
  document.querySelectorAll("[data-once]").forEach(function (btn) {
    btn.form.addEventListener("submit", function (e) {
      if (e.submitter === btn) {
        setTimeout(function () { btn.disabled = true; btn.textContent = "Sending…"; }, 0);
      }
    });
  });
})();
