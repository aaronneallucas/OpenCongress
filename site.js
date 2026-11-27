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
    host.innerHTML = '<nav class="topnav"><a class="brand" href="index.html">Open Congress</a>' +
      tab("votes", "Votes", "votes.html", "votes") + tab("members", "Members", "members.html", "members") +
      '<div class="tab' + (active === "bills" ? " on" : "") + '"><button type="button" data-href="bills.html">Bills</button></div>' +
      '<div class="tab' + (active === "relationships" ? " on" : "") + '"><button type="button" data-href="relationships.html">Relationships</button></div>' +
      '<div class="tab' + (active === "compare" ? " on" : "") + '"><button type="button" data-href="compare.html">Compare</button></div>' +
      '<div class="tab' + (active === "data" ? " on" : "") + '"><button type="button" data-href="data.html">Data</button></div>' +
      '<div class="tab' + (active === "you" ? " on" : "") + '"><button type="button" data-href="you.html">Rep. You</button></div></nav>';
    host.querySelectorAll("[data-href]").forEach(function (b) { b.addEventListener("click", function () { location.href = b.dataset.href; }); });
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


  /* ---------- shared helpers: bill labels, tally bar, rankings, Maverick score ---------- */
  var BL = {HR: "H.R.", S: "S.", HJRES: "H.J.Res.", SJRES: "S.J.Res.", HCONRES: "H.Con.Res.", SCONRES: "S.Con.Res.", HRES: "H.Res.", SRES: "S.Res.", PN: "PN"};
  Site.billLabel = function (b) {
    var m = String(b || "").match(/^([A-Za-z]+)\s*(\d+(?:-\d+)?)$/);
    if (!m || !BL[m[1].toUpperCase()]) return String(b || "");
    return BL[m[1].toUpperCase()] + " " + m[2];
  };

  /* Bill titles and amendment purposes saved by the update script (data/bills/{cg}.json). */
  var BILLS = {};
  Site.bills = function (cg) {
    if (!BILLS[cg]) BILLS[cg] = Site.json("data/bills/" + cg + ".json").catch(function () { return {bills: {}, amendments: {}}; });
    return BILLS[cg];
  };
  /* One line of context for a vote: the bill's title, or for an amendment its purpose. */
  Site.context = function (v, T) {
    T = T || {};
    var am = v.amendment && T.amendments && T.amendments[v.amendment], b = v.bill && T.bills && T.bills[v.bill];
    if (v.amendment) {
      var to = v.bill ? Site.billLabel(v.bill) : (am && am.to ? Site.billLabel(am.to) : "");
      var what = am && am.p ? am.p : (b && b.t) || (am && am.tt) || "";
      return "Amendment" + (to ? " to " + to : "") + (what ? ": " + what : "");
    }
    return (b && b.t) || "";
  };
  Site.clip = function (s, n) { s = String(s || ""); return s.length > n ? s.slice(0, n - 1).replace(/\s+\S*$/, "") + "\u2026" : s; };
  Site.voteTitle = function (j) {
    return "Roll Call " + j.roll + (j.bill ? " \u2014 " + Site.billLabel(j.bill) : (j.question ? " \u2014 " + j.question : ""));
  };
  Site.tallyHTML = function (c, noPills) {
    var yes = c.yes != null ? c.yes : (c.dY || 0) + (c.rY || 0) + (c.iY || 0);
    var no = c.no != null ? c.no : (c.dN || 0) + (c.rN || 0) + (c.iN || 0);
    var tot = yes + no, segs;
    if ("dY" in c) segs = ["dY", "rY", "iY", "dN", "rN", "iN"].map(function (k) { return [c[k] || 0, Site.HEX[k]]; });
    else segs = [[yes, "#1e8e4e"], [no, "#c62828"]];
    var yp = tot ? (100 * yes / tot).toFixed(1) : "0.0", np = tot ? (100 - parseFloat(yp)).toFixed(1) : "0.0";
    var h = '<div class="tw">' + (noPills ? "" : '<div class="pills"><span class="pill y">YES ' + yes + '</span><span class="pill n">NO ' + no + "</span></div>");
    if (tot) {
      h += '<div class="brk">' +
        (yes ? '<div style="flex:' + yes + '"><span class="cy">' + yp + "%</span></div>" : "") +
        (no ? '<div style="flex:' + no + '"><span class="cn">' + np + "%</span></div>" : "") + "</div>";
    }
    h += '<div class="tbar">' + segs.map(function (s) {
      return s[0] ? '<i style="width:' + (s[0] / (tot || 1) * 100) + '%;background:' + s[1] + '"></i>' : "";
    }).join("") + "</div></div>";
    return h;
  };
  /* Represent-style tally table: Yes / No / Present / Not voting by party, with a check or X by the deciding total. */
  Site.partyTable = function (c, passed) {
    var rows = [["Democratic", "d"], ["Republican", "r"]];
    if ((c.iY || 0) + (c.iN || 0) + (c.iP || 0) + (c.iNV || 0)) rows.push(["Independent", "i"]);
    var tot = {Y: 0, N: 0, P: 0, NV: 0};
    var mark = function (k) { return passed === true && k === "Y" ? ' <span class="ck">&#10003;</span>' : passed === false && k === "N" ? ' <span class="xx">&#10007;</span>' : ""; };
    var h = '<table class="pt"><thead><tr><th></th><th>Yes</th><th>No</th><th>Present</th><th>Not voting</th></tr></thead><tbody>';
    rows.forEach(function (r) {
      var v = {Y: c[r[1] + "Y"] || 0, N: c[r[1] + "N"] || 0, P: c[r[1] + "P"] || 0, NV: c[r[1] + "NV"] || 0};
      Object.keys(v).forEach(function (k) { tot[k] += v[k]; });
      h += "<tr><th>" + r[0] + "</th><td>" + v.Y + "</td><td>" + v.N + "</td><td>" + v.P + "</td><td>" + v.NV + "</td></tr>";
    });
    h += '<tr class="tt"><th>Total</th>' + ["Y", "N", "P", "NV"].map(function (k) { return "<td>" + tot[k] + mark(k) + "</td>"; }).join("") + "</tr></tbody></table>";
    return h;
  };
  /* Maverick points for one vote: party members with the majority minus party members against.
     v = index entry (dY,dN,rY,rN); party = "D"/"R"; code = matrix character (uppercase = against party). */
  Site.mavPoints = function (v, party, code) {
    if (code !== "Y" && code !== "N") return 0;
    var a = party === "D" ? v.dY : party === "R" ? v.rY : null, b = party === "D" ? v.dN : party === "R" ? v.rN : null;
    if (a == null || b == null) return 0;
    return Math.abs(a - b);
  };
  /* Rankings among one chamber and Congress. Rank 1 = most missed / most against party / highest Maverick score.
     Ties share a rank. Missed and against-party use percentages and need at least 25% of the chamber's maximum
     number of votes, so members who served only briefly are not ranked. */
  Site.ranks = function (dir, ch, cg) {
    var list = dir.filter(function (e) { var s = e.c && e.c[cg]; return s && s.chamber === ch && s.eligible > 0; });
    var maxE = 0, maxP = 0;
    list.forEach(function (e) { var s = e.c[cg]; maxE = Math.max(maxE, s.eligible); maxP = Math.max(maxP, s.partyVotes || 0); });
    function rank(items, val) {
      items.sort(function (a, b) { return val(b) - val(a); });
      var out = {}, r = 0;
      items.forEach(function (e, i) { if (i === 0 || val(e) !== val(items[i - 1])) r = i + 1; out[e.id] = r; });
      return {map: out, n: items.length};
    }
    var m = rank(list.filter(function (e) { return e.c[cg].eligible >= 0.25 * maxE; }), function (e) { return e.c[cg].missed / e.c[cg].eligible; });
    var a = rank(list.filter(function (e) { var s = e.c[cg]; return s.partyVotes > 0 && s.partyVotes >= 0.25 * maxP; }), function (e) { var s = e.c[cg]; return s.against / s.partyVotes; });
    var v = rank(list.filter(function (e) { return e.c[cg].partyVotes > 0; }), function (e) { return e.c[cg].maverick || 0; });
    return {missed: m, against: a, maverick: v};
  };
  Site.rankText = function (R, kind, id) {
    var r = R[kind].map[id];
    return r ? "#" + r + " of " + R[kind].n : "\u2014";
  };


  /* ---------- roll call counts by Congress: cumulative lines by day since the Congress began ---------- */
  Site.COLORS = ["#1d1d1b", "#2f6fb5", "#c0504d", "#5a9a3a", "#8e5ba6", "#d98c1f", "#2a9d9d", "#8a8a8a"];
  Site.congressStart = function (cg) { return Date.UTC(1789 + 2 * (cg - 1), 0, 3); };
  Site.cumulative = function (index, cg) {
    var start = Site.congressStart(cg), days = [];
    index.forEach(function (v) {
      var t = Date.parse(String(v.date || "").slice(0, 10));
      if (!isNaN(t)) days.push(Math.max(0, Math.round((t - start) / 86400000)));
    });
    days.sort(function (a, b) { return a - b; });
    var pts = [[0, 0]];
    days.forEach(function (d, i) { pts.push([d, i + 1]); });
    return {pts: pts, total: days.length, last: days.length ? days[days.length - 1] : 0};
  };
  Site.countAt = function (c, day) {
    var n = 0;
    c.pts.forEach(function (p) { if (p[0] <= day) n = p[1]; });
    return n;
  };
  /* series: [{label, color, bold, c:cumulative}] ; draws into el (SVG) and wires a hover readout */
  Site.lineChart = function (el, series, opt) {
    opt = opt || {};
    var W = opt.w || 460, H = opt.h || 260, L = 44, R = 14, T = 12, B = 34, DAYS = 731;
    var ymax = 10;
    series.forEach(function (s) { ymax = Math.max(ymax, s.c.total); });
    var step = ymax <= 50 ? 10 : ymax <= 150 ? 25 : ymax <= 300 ? 50 : ymax <= 700 ? 100 : 200;
    ymax = Math.ceil(ymax / step) * step;
    function X(d) { return L + d / DAYS * (W - L - R); }
    function Y(v) { return T + (1 - v / ymax) * (H - T - B); }
    var g = "";
    for (var v = 0; v <= ymax; v += step)
      g += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + Y(v) + '" y2="' + Y(v) + '" stroke="#e6e6e0"/><text x="' + (L - 6) + '" y="' + (Y(v) + 4) + '" font-size="11" fill="#6b6b66" text-anchor="end">' + v + "</text>";
    [[0, "Jan 3"], [182, "Jul"], [365, "Jan, yr 2"], [547, "Jul"], [730, "Jan 3"]].forEach(function (t) {
      g += '<text x="' + X(t[0]) + '" y="' + (H - 12) + '" font-size="11" fill="#6b6b66" text-anchor="' + (t[0] === 0 ? "start" : t[0] === 730 ? "end" : "middle") + '">' + t[1] + "</text>";
    });
    series.slice().reverse().forEach(function (s) {
      var d = "", prev = 0;
      s.c.pts.forEach(function (p, i) {
        d += (i ? "L" : "M") + X(p[0]).toFixed(1) + " " + Y(prev).toFixed(1) + (i ? "L" + X(p[0]).toFixed(1) + " " + Y(p[1]).toFixed(1) : "");
        prev = p[1];
      });
      d += "L" + X(s.c.last).toFixed(1) + " " + Y(s.c.total).toFixed(1);
      g += '<path d="' + d + '" fill="none" stroke="' + s.color + '" stroke-width="' + (s.bold ? 3 : 1.8) + '" stroke-linejoin="round"/>' +
        '<circle cx="' + X(s.c.last).toFixed(1) + '" cy="' + Y(s.c.total).toFixed(1) + '" r="' + (s.bold ? 4 : 3) + '" fill="' + s.color + '"/>';
    });
    g += '<line id="cl" x1="0" x2="0" y1="' + T + '" y2="' + (H - B) + '" stroke="#999" stroke-dasharray="3 3" style="display:none"/>' +
      '<rect class="ov" x="' + L + '" y="' + T + '" width="' + (W - L - R) + '" height="' + (H - T - B) + '" fill="transparent"/>';
    el.innerHTML = '<svg viewBox="0 0 ' + W + " " + H + '" width="100%" role="img" aria-label="' + Site.esc(opt.label || "Roll call votes by Congress") + '">' + g + "</svg>" +
      '<div class="ctip" style="display:none"></div>';
    var svg = el.querySelector("svg"), line = svg.querySelector("#cl"), tip = el.querySelector(".ctip");
    function move(e) {
      var r = svg.getBoundingClientRect(), px = (e.clientX - r.left) / r.width * W;
      var day = Math.max(0, Math.min(DAYS - 1, Math.round((px - L) / (W - L - R) * DAYS)));
      line.setAttribute("x1", X(day)); line.setAttribute("x2", X(day)); line.style.display = "";
      tip.innerHTML = "<b>Day " + day + "</b> <span>(about month " + (Math.floor(day / 30.4) + 1) + ")</span>" + series.map(function (s) {
        var past = day > s.c.last + 20 && s.live;
        return '<div><i style="background:' + s.color + '"></i>' + Site.esc(s.label) + ": <b>" + (past ? "—" : Site.countAt(s.c, day)) + "</b></div>";
      }).join("");
      tip.style.display = "block";
      var left = (e.clientX - r.left) + 12;
      if (left + tip.offsetWidth > r.width) left = e.clientX - r.left - tip.offsetWidth - 12;
      tip.style.left = Math.max(0, left) + "px"; tip.style.top = Math.max(0, e.clientY - r.top - 20) + "px";
    }
    var ov = svg.querySelector(".ov");
    ov.addEventListener("mousemove", move);
    ov.addEventListener("mouseleave", function () { line.style.display = "none"; tip.style.display = "none"; });
    ov.addEventListener("touchmove", function (e) { if (e.touches[0]) move(e.touches[0]); }, {passive: true});
  };
  /* load a cumulative series for every Congress that has data for one chamber */
  Site.chamberSeries = async function (ch, info, latest) {
    var list = (info ? info.congresses : []).filter(function (x) { return x.chambers.indexOf(ch) > -1; });
    var out = [];
    await Promise.all(list.map(async function (x, i) {
      try {
        var idx = await Site.json("data/" + ch + "/" + x.congress + "/index.json");
        out.push({cg: x.congress, label: Site.ordinal(x.congress) + " Congress", c: Site.cumulative(idx, x.congress), live: x.congress === latest});
      } catch (e) {}
    }));
    out.sort(function (a, b) { return b.cg - a.cg; });
    out.forEach(function (s, i) { s.color = Site.COLORS[i % Site.COLORS.length]; s.bold = s.cg === latest; });
    return out;
  };


  /* ---------- how alike two members voted ---------- */
  function sgn(c) { return "yYa".indexOf(c) > -1 ? 1 : "nNb".indexOf(c) > -1 ? -1 : 0; }
  Site.sgn = sgn;
  /* share of roll calls, where both cast a Yea or Nay, on which they voted the same way */
  Site.agree = function (a, b) {
    var same = 0, common = 0, n = Math.min(a.length, b.length);
    for (var i = 0; i < n; i++) {
      var x = sgn(a[i]), y = sgn(b[i]);
      if (x && y) { common++; if (x === y) same++; }
    }
    return {same: same, common: common, pct: common ? 100 * same / common : null};
  };
  Site.castCount = function (s) { var n = 0; for (var i = 0; i < s.length; i++) if (sgn(s[i])) n++; return n; };
  /* every other member in the same matrix, with agreement; pairs need at least half of this member's Yea/Nay votes in common */
  Site.similar = function (mx, id) {
    var mine = mx.members[id];
    if (!mine) return [];
    var need = Math.max(10, 0.5 * Site.castCount(mine)), out = [];
    Object.keys(mx.members).forEach(function (o) {
      if (o === id) return;
      var r = Site.agree(mine, mx.members[o]);
      if (r.common >= need) out.push({id: o, pct: r.pct, same: r.same, common: r.common});
    });
    return out;
  };


  /* ---------- Rep. You: the visitor's own picks, kept only in this browser ---------- */
  var YK = "oc-you-v1";
  function yload() { try { var d = JSON.parse(localStorage.getItem(YK) || "null"); if (d && d.v) return d; } catch (e) {} return {on: false, v: {}}; }
  function ysave(d) { try { localStorage.setItem(YK, JSON.stringify(d)); return true; } catch (e) { return false; } }
  Site.you = {
    on: function () { return !!yload().on; },
    setOn: function (b) { var d = yload(); d.on = !!b; ysave(d); },
    key: function (cg, ch, ss, roll) { return cg + "-" + ch + "-" + ss + "-" + roll; },
    get: function (cg, ch, ss, roll) { return yload().v[Site.you.key(cg, ch, ss, roll)] || 0; },
    set: function (cg, ch, ss, roll, val) { var d = yload(), k = Site.you.key(cg, ch, ss, roll); if (val) d.v[k] = val; else delete d.v[k]; ysave(d); },
    count: function (cg, ch) { var n = 0, p = cg + "-" + ch + "-", v = yload().v; Object.keys(v).forEach(function (k) { if (k.indexOf(p) === 0) n++; }); return n; },
    clear: function () { var d = yload(); d.v = {}; ysave(d); },
    /* the picks as a string in the same format as a matrix row: y / n / - for each roll call, in matrix order */
    vec: function (mx, cg, ch) {
      var v = yload().v;
      return mx.votes.map(function (r) { var x = v[Site.you.key(cg, ch, r[0], r[1])]; return x > 0 ? "y" : x < 0 ? "n" : "-"; }).join("");
    },
    csv: function () {
      var v = yload().v, rows = [["Congress", "Chamber", "Session", "Roll", "Vote"]];
      Object.keys(v).sort().forEach(function (k) { var p = k.split("-"); rows.push([p[0], p[1], p[2], p[3], v[k] > 0 ? "Yes" : "No"]); });
      return "\ufeff" + rows.map(function (r) { return r.join(","); }).join("\r\n") + "\r\n";
    },
    /* read a CSV exported by csv(); only rows for this Congress are kept. Returns {added, skipped} */
    importCsv: function (text, cg) {
      var d = yload(), added = 0, skipped = 0;
      String(text).replace(/^\ufeff/, "").split(/\r?\n/).forEach(function (line, i) {
        var c = line.split(",").map(function (x) { return x.trim().replace(/^"|"$/g, ""); });
        if (c.length < 5 || (i === 0 && isNaN(parseInt(c[0], 10)))) return;
        var ch = c[1].toLowerCase(), val = c[4].toLowerCase(), ss = parseInt(c[2], 10), roll = parseInt(c[3], 10);
        var yv = /^(yes|y|yea|1)$/.test(val) ? 1 : /^(no|n|nay|-1)$/.test(val) ? -1 : 0;
        if (parseInt(c[0], 10) !== cg || (ch !== "house" && ch !== "senate") || !ss || !roll || !yv) { skipped++; return; }
        d.v[Site.you.key(cg, ch, ss, roll)] = yv; added++;
      });
      d.on = true; ysave(d); return {added: added, skipped: skipped};
    }
  };

  window.Site = Site;
})();
