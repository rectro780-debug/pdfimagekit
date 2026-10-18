(function () {
  var cfgEl = document.getElementById('cfg');
  if (!cfgEl) return;
  var cfg = JSON.parse(cfgEl.textContent);
  var $ = function (id) { return document.getElementById(id); };
  var dz = $('dz'), fi = $('fi'), fl = $('fl'), go = $('go'), again = $('again');
  var files = [], vals = {}, resultUrl = null;
  var MAX = 50 * 1024 * 1024;

  fi.multiple = cfg.multi;
  fi.accept = cfg.accept.map(function (x) { return '.' + x; }).join(',');
  cfg.opts.forEach(function (o) { vals[o.name] = o.value; });

  function ext(n) { return (n.split('.').pop() || '').toLowerCase(); }
  function size(b) { return b >= 1048576 ? (b / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(b / 1024)) + ' KB'; }
  function esc(s) { var d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
  function status(msg, err) { var s = $('st'); s.textContent = msg || ''; s.className = 'status' + (err ? ' err' : ''); }
  function resetResult() {
    $('res').classList.remove('show');
    if (resultUrl) { URL.revokeObjectURL(resultUrl); resultUrl = null; }
  }

  function renderOpts() {
    $('opts').innerHTML = cfg.opts.map(function (o) {
      var inp;
      if (o.type === 'select') {
        inp = '<select name="' + o.name + '">' + o.options.map(function (x) {
          return '<option' + (x === o.value ? ' selected' : '') + '>' + x + '</option>';
        }).join('') + '</select>';
      } else if (o.type === 'range') {
        inp = '<input type="range" name="' + o.name + '" min="' + o.min + '" max="' + o.max + '" value="' + o.value + '"><small id="rv_' + o.name + '">' + o.value + '</small>';
      } else {
        inp = '<input type="' + o.type + '" name="' + o.name + '" value="' + esc(String(o.value || '')) + '" placeholder="' + esc(o.placeholder || '') + '">';
      }
      return '<label class="' + (o.wide ? 'wide' : '') + '">' + o.label + inp + (o.hint ? '<small>' + o.hint + '</small>' : '') + '</label>';
    }).join('');
  }
  $('opts').addEventListener('input', function (e) {
    vals[e.target.name] = e.target.value;
    var rv = $('rv_' + e.target.name); if (rv) rv.textContent = e.target.value;
    resetResult();
  });

  function renderFiles() {
    fl.innerHTML = files.map(function (f, i) {
      var move = cfg.multi && files.length > 1
        ? '<button type="button" data-a="up" data-i="' + i + '" aria-label="Move up">&uarr;</button><button type="button" data-a="dn" data-i="' + i + '" aria-label="Move down">&darr;</button>' : '';
      return '<li><span class="nm">' + esc(f.name) + '</span><span class="sz">' + size(f.size) + '</span>' + move +
        '<button type="button" data-a="rm" data-i="' + i + '" aria-label="Remove ' + esc(f.name) + '">&#10005;</button></li>';
    }).join('');
    var need = cfg.min - files.length;
    go.disabled = need > 0;
    go.textContent = need > 0 ? (files.length ? 'Add ' + need + ' more file' + (need > 1 ? 's' : '') : 'Convert') : 'Convert';
    $('dzTitle').textContent = files.length ? (cfg.multi ? 'Add more files' : 'Replace file') : 'Drop your file' + (cfg.multi ? 's' : '') + ' here';
  }

  function addFiles(list) {
    var ok = list.filter(function (f) { return cfg.accept.indexOf(ext(f.name)) > -1; });
    var skipped = list.length - ok.length;
    files = cfg.multi ? files.concat(ok) : ok.slice(0, 1);
    var total = files.reduce(function (a, f) { return a + f.size; }, 0);
    renderFiles(); resetResult();
    if (total > MAX) status('Total size is over 50 MB. Please remove some files.', true);
    else if (skipped) status(skipped + ' file' + (skipped > 1 ? 's were' : ' was') + ' skipped. Allowed types: ' + cfg.accept.join(', ') + '.', true);
    else status('');
  }

  fl.addEventListener('click', function (e) {
    var b = e.target.closest('button'); if (!b) return;
    var i = +b.dataset.i, a = b.dataset.a, t;
    if (a === 'rm') files.splice(i, 1);
    if (a === 'up' && i > 0) { t = files[i - 1]; files[i - 1] = files[i]; files[i] = t; }
    if (a === 'dn' && i < files.length - 1) { t = files[i + 1]; files[i + 1] = files[i]; files[i] = t; }
    renderFiles(); resetResult(); status('');
  });

  dz.addEventListener('click', function () { fi.click(); });
  dz.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fi.click(); } });
  fi.addEventListener('change', function () { addFiles([].slice.call(fi.files)); fi.value = ''; });
  ['dragenter', 'dragover'].forEach(function (ev) { dz.addEventListener(ev, function (e) { e.preventDefault(); dz.classList.add('over'); }); });
  ['dragleave', 'drop'].forEach(function (ev) { dz.addEventListener(ev, function (e) { e.preventDefault(); dz.classList.remove('over'); }); });
  dz.addEventListener('drop', function (e) { addFiles([].slice.call(e.dataTransfer.files)); });
  ['dragover', 'drop'].forEach(function (ev) { window.addEventListener(ev, function (e) { e.preventDefault(); }); });

  go.addEventListener('click', function () {
    var fd = new FormData();
    files.forEach(function (f) { fd.append('files', f); });
    cfg.opts.forEach(function (o) { fd.append(o.name, vals[o.name] == null ? '' : vals[o.name]); });
    go.disabled = true; $('bar').classList.add('on'); status('Converting your files...'); resetResult();
    fetch('/api/' + cfg.id, { method: 'POST', body: fd }).then(function (r) {
      if (!r.ok) {
        return r.json().catch(function () { return {}; }).then(function (j) { throw new Error(j.error || 'Something went wrong. Please try again.'); });
      }
      var cd = r.headers.get('Content-Disposition') || '';
      var m = cd.match(/filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/);
      var name = decodeURIComponent((m && (m[1] || m[2])) || 'converted-file');
      return r.blob().then(function (blob) {
        resultUrl = URL.createObjectURL(blob);
        $('rn').textContent = name; $('rs').textContent = size(blob.size);
        $('rl').href = resultUrl; $('rl').download = name;
        $('res').classList.add('show'); status('');
        again.hidden = false;
      });
    }).catch(function (err) {
      status(err.message, true);
    }).then(function () {
      $('bar').classList.remove('on'); go.disabled = files.length < cfg.min;
    });
  });

  again.addEventListener('click', function () {
    files = []; resetResult(); status(''); renderFiles(); again.hidden = true;
    window.scrollTo({ top: $('tool').offsetTop - 20, behavior: 'smooth' });
  });

  renderOpts(); renderFiles();
})();
