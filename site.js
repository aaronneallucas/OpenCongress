/* Shared helpers and the top navigation for every page. */
(function () {
  var Site = {};
  Site.HEX = {dY: "#1f4e9c", dN: "#8fb4e8", rY: "#b21f1f", rN: "#eba0a0", iY: "#5b2a86", iN: "#b99ad6", P: "#8a8a8a", VAC: "#ffffff"};

  Site.esc = function (s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c];
    });
  };
  Site.ordinal = function (n) {
    var v = n % 100, s = (v >= 11 && v <= 13) ? "th" : ({1: "st", 2: "nd", 3: "rd"}[n % 10] || "th");
    return n + s;
  };
  Site.fmtDate = function (d) {
    if (!d) return "";
    var m = /^(\d{4})-(\d\d)-(\d\d)/.exec(d), t = m ? new Date(+m[1], +m[2] - 1, +m[3]) : new Date(d);
    return isNaN(t) ? d : t.toLocaleDateString(undefined, {year: "numeric", month: "short", day: "numeric"});
  };
  Site.json = async function (path) {
    var r = await fetch(path, {cache: "no-cache"});
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  };
  Site.qs = function () { return new URLSearchParams(location.search); };
  Site.chamberName = function (c) { return c === "senate" ? "Senate" : "House"; };
  Site.voteHref = function (ch, cg, ss, roll) { return "vote.html#" + ch + "-" + cg + "-" + ss + "-" + roll; };
  Site.memberHref = function (id, cg) { return "member.html?id=" + encodeURIComponent(id) + (cg ? "&congress=" + cg : ""); };

  var BT = {HR: "house-bill", S: "senate-bill", HRES: "house-resolution", SRES: "senate-resolution",
    HJRES: "house-joint-resolution", SJRES: "senate-joint-resolution",
    HCONRES: "house-concurrent-resolution", SCONRES: "senate-concurrent-resolution"};
  Site.billType = BT;
  Site.billUrl = function (type, number, congress) {
    var t = BT[String(type || "").toUpperCase().replace(/[.\s]/g, "")];
    return t ? "https://www.congress.gov/bill/" + Site.ordinal(congress) + "-congress/" + t + "/" + number : null;
  };
  Site.billLink = function (j) {
    if (j.billUrl && /^https:\/\//.test(j.billUrl)) return j.billUrl;
    var m = (j.bill || "").match(/^([A-Za-z]+)\s*(\d+)(?:-\d+)?$/);
    if (!m) return null;
    if (m[1].toUpperCase() === "PN") return "https://www.congress.gov/nomination/" + Site.ordinal(j.congress) + "-congress/" + m[2];
    return Site.billUrl(m[1], m[2], j.congress);
  };
  Site.resultPill = function (r) {
    var t = String(r || "").toLowerCase();
    if (!t) return null;
    if (/fail|not agreed|reject|defeat|not sustained|not passed|not invoked|not confirmed|lost/.test(t)) return {text: "FAILED", c: "n", known: true};
    if (/pass|agreed|adopt|sustain|confirm|concur|approv|invoked|upheld/.test(t)) return {text: "PASSED", c: "y", known: true};
    return {text: String(r).toUpperCase(), c: "g", known: false};
  };

  Site.congresses = function () {
    if (!Site._c) Site._c = Site.json("data/congresses.json").catch(function () { return null; });
    return Site._c;
  };

  /* Top navigation: Votes and Members tabs, each with a dropdown. */
  Site.nav = async function (active) {
    var host = document.getElementById("nav");
    if (!host) return;
    var c = await Site.congresses();
    var list = c ? c.congresses : [{congress: 119, years: "2025–2027", chambers: ["house", "senate"]}];
    var latest = c ? c.latest : 119;
    function link(page, ch, cg, text) {
      return '<a href="' + page + '?chamber=' + ch + '&congress=' + cg + '">' + text + "</a>";
    }
    function menu(page, label) {
      var cur = list.filter(function (x) { return x.congress === latest; })[0] || list[0];
      var h = '<div class="menu"><div class="mh">' + Site.ordinal(cur.congress) + " Congress (current)</div>";
      cur.chambers.forEach(function (ch) { h += link(page, ch, cur.congress, Site.chamberName(ch) + " " + label); });
      var prev = list.filter(function (x) { return x.congress !== cur.congress; });
      if (prev.length) {
        h += '<div class="mh">Previous Congresses</div>';
        prev.forEach(function (x) {
          h += '<div class="mrow"><span>' + Site.ordinal(x.congress) + " (" + x.years + ")</span>" +
            x.chambers.map(function (ch) { return link(page, ch, x.congress, Site.chamberName(ch)); }).join("") + "</div>";
        });
      }
      return h + "</div>";
    }
    function tab(name, text, page, label) {
      return '<div class="tab dd' + (active === name ? " on" : "") + '"><button type="button" aria-haspopup="true" aria-expanded="false">' +
        text + " ▾</button>" + menu(page, label) + "</div>";
    }
    host.innerHTML = '<nav class="topnav"><a class="brand" href="index.html">Congress Votes</a>' +
      tab("votes", "Votes", "index.html", "votes") + tab("members", "Members", "members.html", "members") + "</nav>";
    var tabs = host.querySelectorAll(".dd");
    function closeAll() {
      tabs.forEach(function (t) { t.classList.remove("open"); t.firstChild.setAttribute("aria-expanded", "false"); });
    }
    tabs.forEach(function (t) {
      t.firstChild.addEventListener("click", function (e) {
        e.stopPropagation();
        var was = t.classList.contains("open");
        closeAll();
        if (!was) { t.classList.add("open"); t.firstChild.setAttribute("aria-expanded", "true"); }
      });
    });
    document.addEventListener("click", closeAll);
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeAll(); });
  };

  window.Site = Site;
})();
