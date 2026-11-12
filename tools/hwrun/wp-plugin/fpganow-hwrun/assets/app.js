/* FPGA Now - Run on Hardware: front end for the [fpganow_hwrun] shortcode.
   Talks to this site's REST proxy (fpganow-hwrun/v1), which forwards to the hwrun service. */
(function () {
  'use strict';
  var cfg = window.fpganowHwrun || {};
  var $ = function (id) { return document.getElementById(id); };
  var root = $('fpganow-hwrun');
  if (!root) { return; }

  var catalog = null, chart = null, run = null, timer = null;

  function api(path, opts) {
    opts = opts || {};
    var headers = Object.assign({ 'X-WP-Nonce': cfg.nonce || '', 'Accept': 'application/json' }, opts.headers || {});
    return fetch(cfg.restUrl + path, Object.assign({ credentials: 'same-origin' }, opts, { headers: headers }))
      .then(function (r) {
        return r.text().then(function (t) {
          var data = null;
          try { data = JSON.parse(t); } catch (e) { /* not JSON */ }
          if (!r.ok) {
            var msg = (data && (data.message || data.error)) || ('HTTP ' + r.status);
            throw new Error(msg);
          }
          return data;
        });
      });
  }

  function esc(s) {
    return String(s === null || s === undefined ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function fmt(v, d) { return (v === null || v === undefined || v === '') ? '' : Number(v).toLocaleString(undefined, { maximumFractionDigits: d === undefined ? 1 : d, minimumFractionDigits: d === undefined ? 1 : d }); }
  function price(v) { return (v === '' || v === null || v === undefined) ? '' : (Number(v) / 10000).toLocaleString(undefined, { minimumFractionDigits: 4, maximumFractionDigits: 4 }); }

  // ---- sign-in: runs need an account when cfg.auth.required is set
  var auth = cfg.auth || {};
  function mayRun() { return !auth.required || !!auth.mayRun; }
  function enableRun() { $('hwrun-run').disabled = !mayRun(); }

  function googleButton(el, tries) {
    if (!window.google || !google.accounts || !google.accounts.id) {   // Google's loader is async
      if ((tries || 0) < 40) { setTimeout(function () { googleButton(el, (tries || 0) + 1); }, 250); }
      else { el.textContent = 'Google sign-in could not be loaded (blocked by the browser?).'; }
      return;
    }
    google.accounts.id.initialize({ client_id: auth.googleClientId, callback: function (resp) {
      var note = $('hwrun-auth-note'); note.textContent = 'Signing in...';
      api('google-login', { method: 'POST', body: JSON.stringify({ credential: resp.credential }),
                            headers: { 'Content-Type': 'application/json', 'X-FPGANOW-HWRUN': '1' } })
        .then(function () { window.location.reload(); })   // reload: the page needs a fresh nonce for the new session
        .catch(function (e) { note.textContent = 'Sign-in failed: ' + e.message; });
    } });
    google.accounts.id.renderButton(el, { theme: 'outline', size: 'large', text: 'signin_with', shape: 'rectangular' });
  }

  function renderAuth() {
    var box = $('hwrun-auth');
    if (!auth.required) { return; }
    box.hidden = false;
    if (mayRun()) {
      box.innerHTML = 'Signed in as <strong>' + esc(auth.user) + '</strong>. <a href="' + esc(auth.logoutUrl) + '">Sign out</a>';
      return;
    }
    var h = '<p class="hwrun-auth-lead">' + (auth.loggedIn
      ? 'You are signed in as <strong>' + esc(auth.user) + '</strong>, but only accounts verified with Google can start runs. <a href="' + esc(auth.logoutUrl) + '">Sign out</a>'
      : 'Sign in to run a capture on the board. Earlier results stay viewable without an account.') + '</p>';
    h += auth.googleClientId ? '<div id="hwrun-google"></div>' : '<p>Google sign-in is being set up; please check back soon.</p>';
    if (!auth.loggedIn) {
      h += '<p class="hwrun-auth-alt">' + (auth.emailAccounts
        ? '<a href="' + esc(auth.loginUrl) + '">Log in with e-mail</a>' + (auth.registerUrl ? ' or <a href="' + esc(auth.registerUrl) + '">register</a>' : '')
        : '<a href="' + esc(auth.loginUrl) + '">Site staff login</a>') + '</p>';
    }
    h += '<p class="hwrun-auth-note" id="hwrun-auth-note"></p>';
    box.innerHTML = h;
    if (auth.googleClientId) { googleButton($('hwrun-google')); }
  }

  function setStatus(text, kind) {
    var el = $('hwrun-status'); el.textContent = text; el.className = 'hwrun-status' + (kind ? ' is-' + kind : '');
  }

  function fillSelect(sel, items, helpId) {
    sel.innerHTML = '';
    Object.keys(items).forEach(function (k) {
      var o = document.createElement('option'); o.value = k; o.textContent = items[k].label || k; sel.appendChild(o);
    });
    var help = function () { var it = items[sel.value]; $(helpId).textContent = it ? (it.description || '') : ''; };
    sel.addEventListener('change', help); help();
  }

  // Playback speeds come from the service; an implementation may allow only some of them.
  function fillSpeeds() {
    var field = $('hwrun-speed-field'), sel = $('hwrun-speed');
    if (!catalog || !catalog.speeds) { field.hidden = true; return; }
    var impl = catalog.implementations[$('hwrun-impl').value] || {};
    var allowed = impl.speeds || Object.keys(catalog.speeds);
    var keep = allowed.indexOf(sel.value) >= 0 ? sel.value : (allowed.indexOf(catalog.default_speed) >= 0 ? catalog.default_speed : allowed[0]);
    sel.innerHTML = '';
    Object.keys(catalog.speeds).forEach(function (k) {
      if (allowed.indexOf(k) < 0) { return; }
      var o = document.createElement('option'); o.value = k; o.textContent = catalog.speeds[k].label || k; sel.appendChild(o);
    });
    sel.value = keep; field.hidden = false; speedHelp();
  }
  function speedHelp() {
    var it = catalog && catalog.speeds && catalog.speeds[$('hwrun-speed').value];
    var impl = catalog ? (catalog.implementations[$('hwrun-impl').value] || {}) : {};
    var text = it ? (it.description || '') : '';
    if (impl.speeds && catalog.speeds && impl.speeds.length < Object.keys(catalog.speeds).length) {
      text += ' Faster speeds are not offered for this implementation on this page: its records are read out through a slow host FIFO.';
    }
    $('hwrun-speed-help').textContent = text;
  }

  function boardLine() {
    if (!catalog) { return ''; }
    var parts = [];
    Object.keys(catalog.boards).forEach(function (k) {
      var b = catalog.boards[k], loaded = b.loaded_app || 'unknown';
      Object.keys(catalog.implementations).forEach(function (i) { if (catalog.implementations[i].app === loaded) { loaded = catalog.implementations[i].label; } });
      parts.push(b.label + ': ' + loaded + ' loaded');
    });
    if (catalog.busy) { parts.push('a run is in progress'); }
    if (catalog.queued) { parts.push(catalog.queued + ' queued'); }
    return parts.join(' - ');
  }

  function loadCatalog() {
    setStatus('Contacting the run service...');
    return api('catalog').then(function (c) {
      catalog = c;
      fillSelect($('hwrun-pcap'), c.pcaps, 'hwrun-pcap-help');
      fillSelect($('hwrun-impl'), c.implementations, 'hwrun-impl-help');
      fillSelect($('hwrun-board'), c.boards, 'hwrun-board-help');
      $('hwrun-impl').addEventListener('change', fillSpeeds);
      $('hwrun-speed').addEventListener('change', speedHelp);
      fillSpeeds();
      setStatus(boardLine(), 'ok');
      enableRun();
    }).catch(function (e) {
      $('hwrun-pcap').innerHTML = '';
      setStatus('The hardware is not available right now (' + e.message + ').', 'error');
      $('hwrun-run').disabled = true;
    });
  }

  function start(ev) {
    ev.preventDefault();
    if (run && (run.status === 'queued' || run.status === 'running')) { return; }
    if (!mayRun()) { setStatus('Sign in to start a run.', 'warn'); return; }
    var body = { pcap: $('hwrun-pcap').value, implementation: $('hwrun-impl').value, board: $('hwrun-board').value };
    if (!$('hwrun-speed-field').hidden && $('hwrun-speed').value) { body.speed = $('hwrun-speed').value; }
    $('hwrun-run').disabled = true;
    $('hwrun-results').hidden = true;
    $('hwrun-log').hidden = false; $('hwrun-log').textContent = '';
    setStatus('Submitting...');
    api('runs', { method: 'POST', body: JSON.stringify(body),
                  headers: { 'Content-Type': 'application/json', 'X-FPGANOW-HWRUN': '1' } })
      .then(function (r) {
        run = { id: r.id, status: r.status };
        setStatus('Queued (position ' + r.position + ')...');
        poll();
      })
      .catch(function (e) { setStatus('Could not start the run: ' + e.message, 'error'); enableRun(); });
  }

  function poll() {
    api('runs/' + run.id).then(function (r) {
      run = r;
      $('hwrun-log').textContent = (r.log || []).join('\n');
      if (r.status === 'queued') { setStatus('Queued' + (r.position ? ' (position ' + r.position + ')' : '') + '...'); }
      else if (r.status === 'running') { setStatus('Running: ' + (r.step || '') + '...'); }
      if (r.status === 'done') {
        setStatus('Done. ' + (r.summary && r.summary.pass ? 'All messages parsed correctly.' : 'Finished with differences, see below.'), r.summary && r.summary.pass ? 'ok' : 'warn');
        render(r); enableRun();
        try { // a shareable link to this result: ?hwrun=<id> re-opens it
          var u = new URL(window.location.href); u.searchParams.set('hwrun', r.id); window.history.replaceState(null, '', u.toString());
        } catch (e) { /* ignore */ }
        return;
      }
      if (r.status === 'failed') { setStatus('Run failed: ' + (r.error || 'unknown error'), 'error'); enableRun(); return; }
      timer = setTimeout(poll, parseInt(cfg.pollMs, 10) || 1500);
    }).catch(function (e) {
      setStatus('Lost contact with the run service: ' + e.message, 'error'); enableRun();
    });
  }

  function card(label, value, cls) {
    return '<div class="hwrun-card' + (cls ? ' ' + cls : '') + '"><div class="hwrun-card-value">' + value + '</div><div class="hwrun-card-label">' + esc(label) + '</div></div>';
  }

  function render(r) {
    var s = r.summary, req = r.request, rows = r.rows || [];
    [['hwrun-pcap', req.pcap], ['hwrun-impl', req.implementation], ['hwrun-board', req.board]].forEach(function (p) {
      var el = $(p[0]); if (el && el.value !== p[1]) { el.value = p[1]; el.dispatchEvent(new Event('change')); }
    });
    var impl = catalog && catalog.implementations[req.implementation] ? catalog.implementations[req.implementation].label : req.implementation;
    var pc = catalog && catalog.pcaps[req.pcap] ? catalog.pcaps[req.pcap].label : req.pcap;
    var lat = s.latency_ns || {};
    $('hwrun-cards').innerHTML =
      card('implementation', esc(impl)) +
      card('capture', esc(pc)) +
      card('messages matched', esc(s.records_matching + ' / ' + s.messages_in_pcap), s.pass ? 'is-ok' : 'is-warn') +
      card('mismatches / extra / missing', esc(s.records_mismatching + ' / ' + s.records_extra + ' / ' + s.records_missing), (s.records_mismatching || s.records_extra || s.records_missing) ? 'is-warn' : '') +
      card('frames (headers seen)', esc(s.frames_in_pcap + ' (' + s.debug_header_records + ')')) +
      card('latency min / median / max', lat.min === undefined ? '-' : esc(fmt(lat.min) + ' / ' + fmt(lat.median) + ' / ' + fmt(lat.max) + ' ns')) +
      (s.records_without_recv_time ? card('records without recv.time', esc(s.records_without_recv_time), 'is-warn') : '') +
      card('run id', '<code>' + esc(r.id) + '</code>');
    $('hwrun-csv').href = cfg.restUrl + 'runs/' + encodeURIComponent(r.id) + '/csv';
    $('hwrun-csv').setAttribute('download', 'fpganow_hwrun_' + r.id + '.csv');
    $('hwrun-report').textContent = r.report || '';
    $('hwrun-report').hidden = true; $('hwrun-report-toggle').textContent = 'Show scorer report';

    var fh = '<thead><tr><th>frame</th><th>messages</th><th>first message (ns)</th><th>last message (ns)</th></tr></thead><tbody>';
    (s.per_frame || []).forEach(function (f) { fh += '<tr><td>' + f.frame + '</td><td>' + f.messages + '</td><td>' + fmt(f.first_ns) + '</td><td>' + fmt(f.last_ns) + '</td></tr>'; });
    $('hwrun-frames').innerHTML = fh + '</tbody>';

    var th = '<thead><tr><th>#</th><th>seq</th><th>frame</th><th>PITCH message</th><th>parsed as</th><th>order id</th><th>symbol</th><th>qty</th><th>price</th><th>recv.time (ticks)</th><th>parse.time (ticks)</th><th>latency (ns)</th><th>since frame start (ns)</th><th>check</th></tr></thead><tbody>';
    var tb = rows.map(function (x) {
      var cls = x.match === 'ok' ? '' : ' class="is-warn"';
      var chk = x.match === 'ok' ? 'ok' : (x.match === 'MISMATCH' ? 'mismatch: ' + Object.keys(x.mismatch || {}).map(function (k) { return k + ' ' + x.mismatch[k][0] + ' (expected ' + x.mismatch[k][1] + ')'; }).join(', ') : x.match);
      return '<tr' + cls + '><td>' + x.index + '</td><td>' + x.seq + '</td><td>' + esc(x.frame) + '</td><td>' + esc(x.pitch_name) + (x.pitch_type ? ' <small>' + esc(x.pitch_type) + '</small>' : '') + '</td><td>' + esc(x.cmd_type_name) +
        '</td><td><code>' + esc(x.order_id) + '</code></td><td>' + esc(x.symbol) + '</td><td>' + esc(x.quantity) + '</td><td>' + price(x.price) + '</td><td>' + esc(x.recv_ticks) + '</td><td>' + esc(x.parse_ticks) +
        '</td><td>' + (x.latency_ns === null ? '<span title="recv.time 0: no valid stamp">n/a</span>' : fmt(x.latency_ns)) + '</td><td>' + (x.since_frame_start_ns === null ? '' : fmt(x.since_frame_start_ns)) + '</td><td>' + esc(chk) + '</td></tr>';
    }).join('');
    $('hwrun-table').innerHTML = th + tb + '</tbody>';
    $('hwrun-results').hidden = false;
    drawChart();
  }

  var PALETTE = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf'];

  function drawChart() {
    if (!run || !run.rows || typeof Chart === 'undefined') { return; }
    var metric = $('hwrun-metric').value;
    var byFrame = {};
    run.rows.forEach(function (x) {
      if (x[metric] === null || x[metric] === undefined || x[metric] === '') { return; }
      var f = x.frame || 0;
      (byFrame[f] = byFrame[f] || []).push({ x: x.index, y: x[metric], row: x });
    });
    var datasets = Object.keys(byFrame).sort(function (a, b) { return a - b; }).map(function (f, i) {
      return { label: 'frame ' + f, data: byFrame[f], backgroundColor: PALETTE[i % PALETTE.length], pointRadius: run.rows.length > 300 ? 2.5 : 4, pointHoverRadius: 6 };
    });
    var title = metric === 'latency_ns' ? 'recv -> parse latency per message (ns)' : 'time since the first message of the frame (ns)';
    if (chart) { chart.destroy(); }
    chart = new Chart($('hwrun-chart').getContext('2d'), {
      type: 'scatter',
      data: { datasets: datasets },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        scales: { x: { title: { display: true, text: 'message # (order of arrival)' }, ticks: { precision: 0 } },
                  y: { title: { display: true, text: 'ns' }, beginAtZero: true } },
        plugins: {
          title: { display: true, text: title },
          legend: { display: datasets.length > 1 && datasets.length <= 30, position: 'bottom' },
          tooltip: { callbacks: { label: function (c) {
            var x = c.raw.row;
            return ['#' + x.index + ' seq ' + x.seq + ' frame ' + x.frame + ': ' + fmt(c.raw.y) + ' ns',
                    x.pitch_name + (x.order_id ? ' ' + x.order_id : '') + (x.symbol ? ' ' + x.symbol : '')];
          } } }
        }
      }
    });
  }

  root.querySelector('.hwrun-form').addEventListener('submit', start);
  $('hwrun-metric').addEventListener('change', drawChart);
  $('hwrun-report-toggle').addEventListener('click', function () {
    var p = $('hwrun-report'); p.hidden = !p.hidden; this.textContent = p.hidden ? 'Show scorer report' : 'Hide scorer report';
  });
  renderAuth(); enableRun();
  loadCatalog().then(function () {
    var id = null;
    try { id = new URL(window.location.href).searchParams.get('hwrun'); } catch (e) { /* ignore */ }
    if (id && /^[0-9a-f-]{1,40}$/.test(id)) {   // show an earlier run (link from a finished run)
      run = { id: id, status: 'queued' };
      $('hwrun-log').hidden = false; $('hwrun-run').disabled = true;
      poll();
    }
  });
})();
